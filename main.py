#!/usr/bin/env python3
"""
diff_checker — Data Structure & Content Diff Tool
==================================================
Compares database tables, CSV, TXT and XML file pairs defined in a YAML config.

Usage
-----
    python main.py config.yml
    python main.py config.yml -o report.html -f html
    python main.py config.yml -f json -v

Exit codes
----------
    0  All pairs are identical
    1  At least one pair has differences or errors
    2  Configuration / startup error
"""

import argparse
import logging
import sys
from pathlib import Path

from utils.config_loader import load_config
from comparators.db_comparator  import DatabaseComparator
from comparators.csv_comparator import CsvComparator
from comparators.txt_comparator import TxtComparator
from comparators.xml_comparator import XmlComparator
from reporter import Reporter
from models import ComparisonResult


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diff_checker",
        description="Compare DB tables, CSV / TXT / XML file pairs via a YAML config.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "config",
        metavar="CONFIG",
        help="Path to the YAML configuration file",
    )
    p.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write report to FILE instead of stdout",
    )
    p.add_argument(
        "-f", "--format",
        choices=["text", "json", "html"],
        default=None,
        help="Report format: html (default) | text | json",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("diff_checker")

    config_path = Path(args.config)
    if not config_path.is_file():
        log.error("Config file not found: %s", config_path)
        return 2

    config = load_config(config_path)
    all_results: list[ComparisonResult] = []

    # ── Database pairs ─────────────────────────────────────────────────────────
    for pair_cfg in config.get("database_pairs", []):
        pid = pair_cfg.get("id", "unnamed_db")
        log.info("Comparing database pair: %s", pid)
        try:
            all_results.append(DatabaseComparator(pair_cfg).compare())
        except Exception as exc:
            log.exception("Unexpected error for database pair '%s'", pid)
            r = ComparisonResult(pair_id=pid, pair_type="database",
                                 source_name="?", target_name="?")
            r.errors.append(str(exc))
            all_results.append(r)

    # ── File pairs ─────────────────────────────────────────────────────────────
    _COMPARATORS = {
        "csv": CsvComparator,
        "txt": TxtComparator,
        "xml": XmlComparator,
    }

    for pair_cfg in config.get("file_pairs", []):
        pid   = pair_cfg.get("id", "unnamed_file")
        ftype = pair_cfg.get("type", "").lower()
        log.info("Comparing file pair [%s]: %s", ftype, pid)

        cls = _COMPARATORS.get(ftype)
        if cls is None:
            log.warning("Unknown file type '%s' for pair '%s' — skipping.", ftype, pid)
            continue

        try:
            results = cls(pair_cfg).compare()
            if isinstance(results, list):
                all_results.extend(results)
            else:
                all_results.append(results)
        except Exception as exc:
            log.exception("Unexpected error for file pair '%s'", pid)
            r = ComparisonResult(pair_id=pid, pair_type=ftype,
                                 source_name="?", target_name="?")
            r.errors.append(str(exc))
            all_results.append(r)

    # ── Generate report ────────────────────────────────────────────────────────
    output_cfg  = config.get("output", {})
    fmt         = args.format or output_cfg.get("format", "html")
    output_file = args.output or output_cfg.get("file")

    report = Reporter(fmt).generate(all_results)

    if output_file:
        Path(output_file).write_text(report, encoding="utf-8")
        log.info("Report written to: %s", output_file)
    else:
        print(report)

    return 1 if any(r.has_differences for r in all_results) else 0


if __name__ == "__main__":
    sys.exit(main())
