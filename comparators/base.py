"""
Shared file-pair resolution logic used by CSV, TXT and XML comparators.
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def resolve_file_pairs(
    config: Dict[str, Any],
    pair_id: str,
) -> List[Tuple[Path, Path]]:
    """
    Return a list of (source_path, target_path) tuples from a pair config block.

    Two modes are supported:
      - Direct paths  : ``source.path`` and ``target.path`` both set.
      - Pattern match : ``source.directory`` + ``source.pattern`` and
                        ``target.directory`` + ``target.pattern``.

    When ``match_by: name`` (default) files are paired by filename.
    When ``match_by: index`` they are sorted and paired positionally.
    """
    src_cfg = config.get("source", {})
    tgt_cfg = config.get("target", {})

    # ── Direct file paths ──────────────────────────────────────────────────────
    if "path" in src_cfg and "path" in tgt_cfg:
        src = Path(src_cfg["path"])
        tgt = Path(tgt_cfg["path"])
        if not src.is_file():
            raise FileNotFoundError(f"Source file not found: {src}")
        if not tgt.is_file():
            raise FileNotFoundError(f"Target file not found: {tgt}")
        return [(src, tgt)]

    # ── Directory + pattern ────────────────────────────────────────────────────
    src_dir = Path(src_cfg["directory"])
    tgt_dir = Path(tgt_cfg["directory"])
    src_pattern = src_cfg.get("pattern", ".*")
    tgt_pattern = tgt_cfg.get("pattern", ".*")

    if not src_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src_dir}")
    if not tgt_dir.is_dir():
        raise FileNotFoundError(f"Target directory not found: {tgt_dir}")

    src_files: Dict[str, Path] = {
        f.name: f
        for f in src_dir.iterdir()
        if f.is_file() and re.fullmatch(src_pattern, f.name)
    }
    tgt_files: Dict[str, Path] = {
        f.name: f
        for f in tgt_dir.iterdir()
        if f.is_file() and re.fullmatch(tgt_pattern, f.name)
    }

    pairs: List[Tuple[Path, Path]] = []
    match_by = config.get("match_by", "name")

    if match_by == "name":
        for name in sorted(set(src_files) | set(tgt_files)):
            if name in src_files and name in tgt_files:
                pairs.append((src_files[name], tgt_files[name]))
            elif name in src_files:
                logger.warning("[%s] '%s' exists only in source (%s)", pair_id, name, src_dir)
            else:
                logger.warning("[%s] '%s' exists only in target (%s)", pair_id, name, tgt_dir)
    else:  # index
        src_sorted = sorted(src_files.values(), key=lambda p: p.name)
        tgt_sorted = sorted(tgt_files.values(), key=lambda p: p.name)
        n = min(len(src_sorted), len(tgt_sorted))
        pairs = list(zip(src_sorted[:n], tgt_sorted[:n]))
        if len(src_sorted) != len(tgt_sorted):
            logger.warning(
                "[%s] Source has %d files, target has %d — only %d pairs compared.",
                pair_id, len(src_sorted), len(tgt_sorted), n,
            )

    if not pairs:
        logger.warning("[%s] No matching file pairs found.", pair_id)

    return pairs
