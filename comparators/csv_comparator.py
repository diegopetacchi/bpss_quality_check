"""
CSV file comparator — MINUS-equivalent (set-difference on rows).

Two rows are equal when ALL their cell values (for the common columns,
excluding the excluded ones) are identical as strings.  The comparison is
order-independent, exactly as SQL MINUS.

Supports direct file paths and directory + regex pattern matching.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Set

import pandas as pd

from comparators.base import resolve_file_pairs
from models import ComparisonResult, DiffDetail, DiffType

logger = logging.getLogger(__name__)


class CsvComparator:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config           = config
        self.pair_id: str     = config.get("id", "unnamed_csv")
        self.exclude_cols: Set[str] = set(config.get("exclude_columns", []))
        self.delimiter: str   = config.get("delimiter", ",")
        self.encoding: str    = config.get("encoding", "utf-8")
        self.has_header: bool = config.get("has_header", True)
        self.max_diffs: int   = config.get("max_diffs", 100)

    # ──────────────────────────────────────────────────────────────────────────
    def compare(self) -> List[ComparisonResult]:
        pairs = resolve_file_pairs(self.config, self.pair_id)
        return [self._compare_pair(src, tgt) for src, tgt in pairs]

    # ──────────────────────────────────────────────────────────────────────────
    def _compare_pair(self, src_path: Path, tgt_path: Path) -> ComparisonResult:
        pair_id = f"{self.pair_id}:{src_path.name}"
        result  = ComparisonResult(
            pair_id=pair_id,
            pair_type="csv",
            source_name=str(src_path),
            target_name=str(tgt_path),
        )

        try:
            header = 0 if self.has_header else None
            src_df = pd.read_csv(
                src_path, sep=self.delimiter, encoding=self.encoding,
                header=header, dtype=str, keep_default_na=False,
            )
            tgt_df = pd.read_csv(
                tgt_path, sep=self.delimiter, encoding=self.encoding,
                header=header, dtype=str, keep_default_na=False,
            )

            src_df = src_df.drop(columns=[c for c in self.exclude_cols if c in src_df.columns], errors="ignore")
            tgt_df = tgt_df.drop(columns=[c for c in self.exclude_cols if c in tgt_df.columns], errors="ignore")

            src_cols_set = set(src_df.columns)
            tgt_cols_set = set(tgt_df.columns)

            # ── Schema diff ───────────────────────────────────────────────────
            for col in sorted(tgt_cols_set - src_cols_set):
                result.differences.append(DiffDetail(
                    diff_type=DiffType.SCHEMA_ADDED,
                    location=f"column:{col}",
                    description=f"Colonna '{col}' presente in target ma assente in source",
                ))
            for col in sorted(src_cols_set - tgt_cols_set):
                result.differences.append(DiffDetail(
                    diff_type=DiffType.SCHEMA_REMOVED,
                    location=f"column:{col}",
                    description=f"Colonna '{col}' presente in source ma assente in target",
                ))

            common_cols = [c for c in src_df.columns if c in tgt_cols_set]

            result.stats.update({
                "righe_source":    len(src_df),
                "righe_target":    len(tgt_df),
                "colonne_source":  len(src_df.columns),
                "colonne_target":  len(tgt_df.columns),
                "colonne_comuni":  len(common_cols),
            })

            if not common_cols:
                result.errors.append("Nessuna colonna comune per il confronto dati")
                return result

            # ── MINUS-equivalent (set-difference) ─────────────────────────────
            src_set = {tuple(r) for r in src_df[common_cols].values.tolist()}
            tgt_set = {tuple(r) for r in tgt_df[common_cols].values.tolist()}

            only_src = sorted(src_set - tgt_set)
            only_tgt = sorted(tgt_set - src_set)
            total_src, total_tgt = len(only_src), len(only_tgt)
            max_d = self.max_diffs

            src_records = [dict(zip(common_cols, r)) for r in only_src[:max_d]]
            tgt_records = [dict(zip(common_cols, r)) for r in only_tgt[:max_d]]

            result.stats.update({
                "solo_in_source": total_src,
                "solo_in_target": total_tgt,
            })
            result.report_data = {
                "check_type":       "set_minus",
                "columns":          common_cols,
                "only_in_source":   src_records,
                "only_in_target":   tgt_records,
                "truncated_source": total_src > max_d,
                "truncated_target": total_tgt > max_d,
            }

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
                    description=f"Output troncato — max {max_d} righe per lato mostrate",
                ))

        except Exception as exc:
            logger.exception("Errore nel confronto CSV pair '%s'", pair_id)
            result.errors.append(f"{type(exc).__name__}: {exc}")

        return result
