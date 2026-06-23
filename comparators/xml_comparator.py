"""
XML file comparator — MINUS-equivalent (set-difference on flattened node pairs).

Each XML file is flattened to a set of ``(xpath, value)`` tuples:
  • element text  → ``("/root/elem", "text value")``
  • attribute     → ``("/root/elem/@attr", "attr value")``

The comparison is then a plain set-difference (like SQL MINUS):
  • order-independent (a reordered tree with same values = identical)
  • duplicate-insensitive

Tags and/or attributes listed in ``exclude_tags`` / ``exclude_attributes``
are skipped during flattening.

Supports direct file paths and directory + regex pattern matching.
"""
import logging
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Set, Tuple

from lxml import etree

from comparators.base import resolve_file_pairs
from models import ComparisonResult, DiffDetail, DiffType

logger = logging.getLogger(__name__)

_COMMENT_TYPE = type(etree.Comment(""))
_NodePair     = Tuple[str, str]   # (xpath, value)


class XmlComparator:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config               = config
        self.pair_id: str         = config.get("id", "unnamed_xml")
        self.exclude_tags: Set[str]  = set(config.get("exclude_tags",       []))
        self.exclude_attrs: Set[str] = set(config.get("exclude_attributes", []))
        self.max_diffs: int       = config.get("max_diffs", 100)

    # ──────────────────────────────────────────────────────────────────────────
    def compare(self) -> List[ComparisonResult]:
        pairs = resolve_file_pairs(self.config, self.pair_id)
        return [self._compare_pair(src, tgt) for src, tgt in pairs]

    # ──────────────────────────────────────────────────────────────────────────
    def _compare_pair(self, src_path: Path, tgt_path: Path) -> ComparisonResult:
        pair_id = f"{self.pair_id}:{src_path.name}"
        result  = ComparisonResult(
            pair_id=pair_id,
            pair_type="xml",
            source_name=str(src_path),
            target_name=str(tgt_path),
        )

        try:
            src_root = etree.parse(str(src_path)).getroot()
            tgt_root = etree.parse(str(tgt_path)).getroot()

            src_pairs = self._flatten(src_root)
            tgt_pairs = self._flatten(tgt_root)

            only_src = sorted(src_pairs - tgt_pairs)
            only_tgt = sorted(tgt_pairs - src_pairs)
            total_src, total_tgt = len(only_src), len(only_tgt)
            max_d = self.max_diffs

            result.stats.update({
                "coppie_source":  len(src_pairs),
                "coppie_target":  len(tgt_pairs),
                "solo_in_source": total_src,
                "solo_in_target": total_tgt,
            })

            src_records = [{"path": p, "value": v} for p, v in only_src[:max_d]]
            tgt_records = [{"path": p, "value": v} for p, v in only_tgt[:max_d]]

            result.report_data = {
                "check_type":       "xml_minus",
                "only_in_source":   src_records,
                "only_in_target":   tgt_records,
                "truncated_source": total_src > max_d,
                "truncated_target": total_tgt > max_d,
            }

            for i, rec in enumerate(src_records):
                result.differences.append(DiffDetail(
                    diff_type=DiffType.DATA_REMOVED,
                    location=rec["path"],
                    source_value=rec["value"],
                    description="Coppia (path, valore) presente in source ma non in target (MINUS)",
                ))
            for i, rec in enumerate(tgt_records):
                result.differences.append(DiffDetail(
                    diff_type=DiffType.DATA_ADDED,
                    location=rec["path"],
                    target_value=rec["value"],
                    description="Coppia (path, valore) presente in target ma non in source (MINUS)",
                ))
            if total_src > max_d or total_tgt > max_d:
                result.differences.append(DiffDetail(
                    diff_type=DiffType.DATA_CHANGED,
                    location="...",
                    description=f"Output troncato — max {max_d} coppie per lato mostrate",
                ))

        except Exception as exc:
            logger.exception("Errore nel confronto XML pair '%s'", pair_id)
            result.errors.append(f"{type(exc).__name__}: {exc}")

        return result

    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _local(element) -> str:
        tag = element.tag
        return tag.split("}", 1)[1] if isinstance(tag, str) and tag.startswith("{") else str(tag)

    def _skip(self, element) -> bool:
        return isinstance(element.tag, _COMMENT_TYPE) or self._local(element) in self.exclude_tags

    def _flatten(self, element, path: str = "") -> FrozenSet[_NodePair]:
        """Recursively flatten element tree to a frozenset of (xpath, value) pairs."""
        if self._skip(element):
            return frozenset()

        cur    = f"{path}/{self._local(element)}"
        pairs: Set[_NodePair] = set()

        # Attributes
        for k, v in element.attrib.items():
            if k not in self.exclude_attrs:
                pairs.add((f"{cur}/@{k}", v))

        # Text content
        text = (element.text or "").strip()
        if text:
            pairs.add((cur, text))

        # Children
        for child in element:
            if not self._skip(child):
                pairs.update(self._flatten(child, cur))

        return frozenset(pairs)
