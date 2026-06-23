from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DiffType(str, Enum):
    SCHEMA_ADDED   = "schema_added"    # column/tag/attribute present in target only
    SCHEMA_REMOVED = "schema_removed"  # column/tag/attribute present in source only
    SCHEMA_CHANGED = "schema_changed"  # definition/type changed
    DATA_ADDED     = "data_added"      # row/element present in target only
    DATA_REMOVED   = "data_removed"    # row/element present in source only
    DATA_CHANGED   = "data_changed"    # value changed
    CONTENT_DIFF   = "content_diff"    # raw text/unified-diff content
    FILE_MISSING   = "file_missing"    # file found in one side only


@dataclass
class DiffDetail:
    diff_type: DiffType
    location: str          # e.g. "column:name", "row:42", "/root/item[2]/@id", "line:10"
    source_value: Any = None
    target_value: Any = None
    description: str = ""


@dataclass
class ComparisonResult:
    pair_id: str
    pair_type: str         # "database" | "csv" | "txt" | "xml"
    source_name: str
    target_name: str
    differences: List[DiffDetail] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    # Structured data used by the HTML reporter for rich table rendering.
    # Keys vary by check_type: "minus" | "set_minus" | "xml_minus"
    report_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_differences(self) -> bool:
        return bool(self.differences or self.errors)

    @property
    def status(self) -> str:
        if self.errors:
            return "ERROR"
        if self.differences:
            return "DIFFERENCES FOUND"
        return "IDENTICAL"
