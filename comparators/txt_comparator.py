"""
Plain-text file comparator — MINUS-equivalent (set-difference on lines).

Each line is treated as a "record".  Two files are compared by computing the
symmetric difference of their line sets, exactly as SQL MINUS does on rows:
  • order-independent
  • duplicate-insensitive

Supports direct file paths and directory + regex pattern matching.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List

from comparators.base import resolve_file_pairs
from models import ComparisonResult, DiffDetail, DiffType

logger = logging.getLogger(__name__)


class TxtComparator:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config           = config
        self.pair_id: str     = config.get("id", "unnamed_txt")
        self.encoding: str    = config.get("encoding", "utf-8")
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
            pair_type="txt",
            source_name=str(src_path),
            target_name=str(tgt_path),
        )

        try:
            src_text = src_path.read_text(encoding=self.encoding)
            tgt_text = tgt_path.read_text(encoding=self.encoding)

            src_all = src_text.splitlines()
            tgt_all = tgt_text.splitlines()

            src_set = set(src_all)
            tgt_set = set(tgt_all)

            only_src = sorted(src_set - tgt_set)
            only_tgt = sorted(tgt_set - src_set)
            total_src, total_tgt = len(only_src), len(only_tgt)
            max_d = self.max_diffs

            result.stats.update({
                "righe_source":  len(src_all),
                "righe_target":  len(tgt_all),
                "solo_in_source": total_src,
                "solo_in_target": total_tgt,
            })

            src_records = only_src[:max_d]
            tgt_records = only_tgt[:max_d]

            result.report_data = {
                "check_type":       "set_minus",
                "only_in_source":   src_records,   # list of plain strings
                "only_in_target":   tgt_records,
                "truncated_source": total_src > max_d,
                "truncated_target": total_tgt > max_d,
            }

            for i, line in enumerate(src_records):
                result.differences.append(DiffDetail(
                    diff_type=DiffType.DATA_REMOVED,
                    location=f"line:{i + 1}",
                    source_value=line,
                    description="Riga presente in source ma non in target (MINUS)",
                ))
            for i, line in enumerate(tgt_records):
                result.differences.append(DiffDetail(
                    diff_type=DiffType.DATA_ADDED,
                    location=f"line:{i + 1}",
                    target_value=line,
                    description="Riga presente in target ma non in source (MINUS)",
                ))
            if total_src > max_d or total_tgt > max_d:
                result.differences.append(DiffDetail(
                    diff_type=DiffType.DATA_CHANGED,
                    location="...",
                    description=f"Output troncato — max {max_d} righe per lato mostrate",
                ))

        except Exception as exc:
            logger.exception("Errore nel confronto TXT pair '%s'", pair_id)
            result.errors.append(f"{type(exc).__name__}: {exc}")

        return result
