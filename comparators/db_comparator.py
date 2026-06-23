"""
Database table comparator — Oracle edition.

Schema comparison: uses SQLAlchemy inspection.
Data comparison:
  • Same Oracle instance (same connection_string) → SQL MINUS executed on DB.
  • Different instances                          → Python set-difference after
                                                   loading both tables into memory.

Connection info is read from the YAML config. All string values support
``${CHECK_TOOL_XXX}`` placeholders resolved from environment variables.

Connection block accepts either:
  connection_string: oracle+oracledb://...   (full SQLAlchemy URL)
or individual fields:
  user / password / host / port (default 1521) / service
"""
import logging
from typing import Any, Dict, List, Set
from urllib.parse import quote_plus

import pandas as pd

from models import ComparisonResult, DiffDetail, DiffType

logger = logging.getLogger(__name__)


class DatabaseComparator:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config    = config
        self.pair_id   = config.get("id", "unnamed_db")
        # Normalise to upper-case for Oracle (unquoted identifiers are uppercase)
        self.exclude_columns: Set[str] = {
            c.upper() for c in config.get("exclude_columns", [])
        }
        self.max_diffs: int      = config.get("max_diffs", 100)
        self.row_limit: int | None = config.get("row_limit")

    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _build_conn_str(cfg: Dict[str, Any]) -> str:
        """Return a SQLAlchemy URL from the config block."""
        if "connection_string" in cfg:
            return cfg["connection_string"]
        user    = cfg["user"]
        pwd     = quote_plus(str(cfg["password"]))
        host    = cfg["host"]
        port    = str(cfg.get("port", 1521))
        service = cfg["service"]
        return f"oracle+oracledb://{user}:{pwd}@{host}:{port}/?service_name={service}"

    # ──────────────────────────────────────────────────────────────────────────
    def compare(self) -> ComparisonResult:
        from sqlalchemy import create_engine, inspect

        src_cfg    = self.config["source"]
        tgt_cfg    = self.config["target"]
        src_schema = src_cfg.get("schema")
        src_table  = src_cfg["table"]
        tgt_schema = tgt_cfg.get("schema")
        tgt_table  = tgt_cfg["table"]

        src_label = f"{src_schema}.{src_table}" if src_schema else src_table
        tgt_label = f"{tgt_schema}.{tgt_table}" if tgt_schema else tgt_table

        result = ComparisonResult(
            pair_id=self.pair_id,
            pair_type="database",
            source_name=src_label,
            target_name=tgt_label,
        )

        try:
            src_conn_str = self._build_conn_str(src_cfg)
            tgt_conn_str = self._build_conn_str(tgt_cfg)

            src_engine = create_engine(src_conn_str)
            tgt_engine = create_engine(tgt_conn_str)

            src_insp = inspect(src_engine)
            tgt_insp = inspect(tgt_engine)

            # ── Schema ──────────────────────────────────────────────────────
            common_cols = self._compare_schema(
                src_insp, tgt_insp,
                src_schema, src_table,
                tgt_schema, tgt_table,
                result,
            )

            if not common_cols:
                result.errors.append("Nessuna colonna comune per il confronto dati")
                return result

            # ── Row counts ──────────────────────────────────────────────────
            result.stats.update(
                self._row_counts(src_engine, tgt_engine, src_label, tgt_label)
            )

            # ── Data MINUS ──────────────────────────────────────────────────
            same_db = (src_conn_str == tgt_conn_str)
            if same_db:
                logger.debug("[%s] Same DB → SQL MINUS", self.pair_id)
                self._minus_sql(
                    src_engine, src_label, tgt_label, common_cols, result
                )
            else:
                logger.debug("[%s] Different DBs → Python set-difference", self.pair_id)
                self._minus_python(
                    src_engine, tgt_engine,
                    src_schema, src_table,
                    tgt_schema, tgt_table,
                    common_cols, result,
                )

        except Exception as exc:
            logger.exception("Errore nel confronto DB pair '%s'", self.pair_id)
            result.errors.append(f"{type(exc).__name__}: {exc}")

        return result

    # ──────────────────────────────────────────────────────────────────────────
    def _get_cols(self, inspector, schema, table) -> Dict[str, Any]:
        return {
            col["name"]: col
            for col in inspector.get_columns(table, schema=schema)
            if col["name"].upper() not in self.exclude_columns
        }

    def _compare_schema(
        self,
        src_insp, tgt_insp,
        src_schema, src_table,
        tgt_schema, tgt_table,
        result: ComparisonResult,
    ) -> List[str]:
        src_cols = self._get_cols(src_insp, src_schema, src_table)
        tgt_cols = self._get_cols(tgt_insp, tgt_schema, tgt_table)

        for col in sorted(set(tgt_cols) - set(src_cols)):
            result.differences.append(DiffDetail(
                diff_type=DiffType.SCHEMA_ADDED,
                location=f"column:{col}",
                source_value=None,
                target_value=str(tgt_cols[col]["type"]),
                description=f"Colonna '{col}' presente in target ma assente in source",
            ))
        for col in sorted(set(src_cols) - set(tgt_cols)):
            result.differences.append(DiffDetail(
                diff_type=DiffType.SCHEMA_REMOVED,
                location=f"column:{col}",
                source_value=str(src_cols[col]["type"]),
                target_value=None,
                description=f"Colonna '{col}' presente in source ma assente in target",
            ))
        for col in sorted(set(src_cols) & set(tgt_cols)):
            s_type     = str(src_cols[col]["type"])
            t_type     = str(tgt_cols[col]["type"])
            s_null     = src_cols[col].get("nullable", True)
            t_null     = tgt_cols[col].get("nullable", True)
            if s_type != t_type or s_null != t_null:
                result.differences.append(DiffDetail(
                    diff_type=DiffType.SCHEMA_CHANGED,
                    location=f"column:{col}",
                    source_value={"type": s_type, "nullable": s_null},
                    target_value={"type": t_type, "nullable": t_null},
                    description=f"Definizione colonna '{col}' modificata",
                ))

        common = sorted(set(src_cols) & set(tgt_cols))
        result.stats.update({
            "colonne_source": len(src_cols),
            "colonne_target": len(tgt_cols),
            "colonne_comuni": len(common),
        })
        return common

    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _row_counts(src_engine, tgt_engine, src_label, tgt_label) -> Dict[str, Any]:
        from sqlalchemy import text
        stats: Dict[str, Any] = {}
        for label, engine, key in [
            (src_label, src_engine, "righe_source"),
            (tgt_label, tgt_engine, "righe_target"),
        ]:
            try:
                with engine.connect() as conn:
                    stats[key] = conn.execute(
                        text(f"SELECT COUNT(*) FROM {label}")
                    ).scalar()
            except Exception as exc:
                logger.warning("COUNT(*) fallito per %s: %s", label, exc)
                stats[key] = "n/a"
        return stats

    # ──────────────────────────────────────────────────────────────────────────
    def _minus_sql(
        self, engine, src_label, tgt_label, common_cols, result
    ) -> None:
        """Execute MINUS directly in Oracle (same DB instance)."""
        from sqlalchemy import text

        col_list = ", ".join(common_cols)
        sql_s = text(
            f"SELECT {col_list} FROM {src_label} "
            f"MINUS "
            f"SELECT {col_list} FROM {tgt_label}"
        )
        sql_t = text(
            f"SELECT {col_list} FROM {tgt_label} "
            f"MINUS "
            f"SELECT {col_list} FROM {src_label}"
        )
        with engine.connect() as conn:
            only_src = pd.read_sql(sql_s, conn)
            only_tgt = pd.read_sql(sql_t, conn)

        self._store_minus_results(
            only_src.astype(str).to_dict(orient="records"),
            only_tgt.astype(str).to_dict(orient="records"),
            len(only_src), len(only_tgt),
            common_cols, result,
        )

    # ──────────────────────────────────────────────────────────────────────────
    def _minus_python(
        self,
        src_engine, tgt_engine,
        src_schema, src_table,
        tgt_schema, tgt_table,
        common_cols, result,
    ) -> None:
        """Python set-difference for cross-instance comparison."""
        from sqlalchemy import MetaData, Table, select

        def load(engine, schema, table) -> pd.DataFrame:
            meta = MetaData()
            tbl  = Table(table, meta, schema=schema, autoload_with=engine)
            cols = [tbl.c[c] for c in common_cols if c in tbl.c]
            stmt = select(*cols)
            if self.row_limit:
                stmt = stmt.limit(self.row_limit)
            with engine.connect() as conn:
                return pd.read_sql(stmt, conn).fillna("").astype(str)

        src_df = load(src_engine, src_schema, src_table)
        tgt_df = load(tgt_engine, tgt_schema, tgt_table)

        # Normalise column names to match common_cols case
        src_df.columns = common_cols[: len(src_df.columns)]
        tgt_df.columns = common_cols[: len(tgt_df.columns)]

        src_set = {tuple(r) for r in src_df[common_cols].values.tolist()}
        tgt_set = {tuple(r) for r in tgt_df[common_cols].values.tolist()}

        only_src = sorted(src_set - tgt_set)
        only_tgt = sorted(tgt_set - src_set)

        max_d = self.max_diffs
        self._store_minus_results(
            [dict(zip(common_cols, r)) for r in only_src[:max_d]],
            [dict(zip(common_cols, r)) for r in only_tgt[:max_d]],
            len(only_src), len(only_tgt),
            common_cols, result,
        )

    # ──────────────────────────────────────────────────────────────────────────
    def _store_minus_results(
        self,
        src_records: List[Dict],
        tgt_records: List[Dict],
        total_src: int,
        total_tgt: int,
        columns: List[str],
        result: ComparisonResult,
    ) -> None:
        max_d = self.max_diffs
        result.stats.update({
            "solo_in_source": total_src,
            "solo_in_target": total_tgt,
        })
        result.report_data.update({
            "check_type":       "minus",
            "columns":          columns,
            "only_in_source":   src_records,
            "only_in_target":   tgt_records,
            "truncated_source": total_src > len(src_records),
            "truncated_target": total_tgt > len(tgt_records),
        })
        for i, rec in enumerate(src_records):
            result.differences.append(DiffDetail(
                diff_type=DiffType.DATA_REMOVED,
                location=f"row:{i + 1}",
                source_value=rec,
                description="Riga presente in source ma non in target (MINUS)",
            ))
        for i, rec in enumerate(tgt_records):
            result.differences.append(DiffDetail(
                diff_type=DiffType.DATA_ADDED,
                location=f"row:{i + 1}",
                target_value=rec,
                description="Riga presente in target ma non in source (MINUS)",
            ))
        if total_src > max_d or total_tgt > max_d:
            result.differences.append(DiffDetail(
                diff_type=DiffType.DATA_CHANGED,
                location="...",
                description=f"Output troncato — max {max_d} record per lato mostrati",
            ))
