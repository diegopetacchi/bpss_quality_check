"""
Report generator — HTML (default), JSON, plain text.

HTML report features:
  - Sticky top-bar with title and generation timestamp
  - Summary section: KPI counters + overview table with anchors
  - Per-pair detail cards:
      • Header (ID, type, status badge, source → target)
      • Stats bar
      • Schema differences table  (purple header)
      • "Solo in Source" table    (red header)    — MINUS result A \ B
      • "Solo in Target" table    (blue header)   — MINUS result B \ A
      • Errors list
"""
import html as _html
import json
from datetime import datetime
from typing import Any, Dict, List

from models import ComparisonResult, DiffType

_SCHEMA_TYPES = {DiffType.SCHEMA_ADDED, DiffType.SCHEMA_REMOVED, DiffType.SCHEMA_CHANGED}
_DATA_TYPES   = {DiffType.DATA_ADDED, DiffType.DATA_REMOVED, DiffType.DATA_CHANGED}


def _e(s: Any) -> str:
    return _html.escape(str(s))


def _anchor(pair_id: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9_-]", "_", pair_id)


# ─────────────────────────────────────────────────────────────────────────────
class Reporter:
    def __init__(self, format: str = "html") -> None:
        self.format = format.lower()

    def generate(self, results: List[ComparisonResult]) -> str:
        if self.format == "json":
            return self._json(results)
        if self.format == "text":
            return self._text(results)
        return self._html(results)

    # ── Plain text ────────────────────────────────────────────────────────────
    def _text(self, results: List[ComparisonResult]) -> str:
        W = 80
        lines: List[str] = []

        def sep(ch="="):
            lines.append(ch * W)

        sep(); lines.append("VERIFICA QUALITÀ DATI — REPORT"); sep()
        lines.append("")
        total     = len(results)
        identical = sum(1 for r in results if not r.has_differences)
        with_diff = sum(1 for r in results if r.differences and not r.errors)
        errors    = sum(1 for r in results if r.errors)
        lines += [
            f"  Coppie verificate : {total}",
            f"  Identiche         : {identical}",
            f"  Con differenze    : {with_diff}",
            f"  Errori            : {errors}", "",
        ]
        for r in results:
            sep("-")
            lines += [
                f"  ID      : {r.pair_id}",
                f"  Tipo    : {r.pair_type.upper()}",
                f"  Source  : {r.source_name}",
                f"  Target  : {r.target_name}",
                f"  Stato   : {r.status}",
            ]
            if r.stats:
                lines.append("  Stats   : " + "  |  ".join(f"{k}={v}" for k, v in r.stats.items()))
            for err in r.errors:
                lines.append(f"  [ERRORE] {err}")
            schema_d = [d for d in r.differences if d.diff_type in _SCHEMA_TYPES]
            data_d   = [d for d in r.differences if d.diff_type in _DATA_TYPES]
            if schema_d:
                lines.append(f"\n  Diff schema ({len(schema_d)}):")
                for d in schema_d:
                    lines.append(f"    [{d.diff_type.value}] {d.location} — {d.description}")
                    if d.source_value: lines.append(f"      Source: {d.source_value}")
                    if d.target_value: lines.append(f"      Target: {d.target_value}")
            if data_d:
                lines.append(f"\n  Diff dati ({len(data_d)}):")
                for d in data_d:
                    lines.append(f"    [{d.diff_type.value}] {d.location}")
                    lines.append(f"      {d.description}")
                    if d.source_value: lines.append(f"      Source: {d.source_value}")
                    if d.target_value: lines.append(f"      Target: {d.target_value}")
            lines.append("")
        sep(); lines.append("FINE REPORT"); sep()
        return "\n".join(lines)

    # ── JSON ──────────────────────────────────────────────────────────────────
    def _json(self, results: List[ComparisonResult]) -> str:
        def to_dict(r: ComparisonResult) -> Dict:
            return {
                "pair_id":     r.pair_id,
                "pair_type":   r.pair_type,
                "source_name": r.source_name,
                "target_name": r.target_name,
                "status":      r.status,
                "stats":       r.stats,
                "errors":      r.errors,
                "differences": [
                    {"diff_type": d.diff_type.value, "location": d.location,
                     "source_value": d.source_value, "target_value": d.target_value,
                     "description": d.description}
                    for d in r.differences
                ],
                "report_data": r.report_data,
            }
        payload = {
            "summary": {
                "total": len(results),
                "identiche": sum(1 for r in results if not r.has_differences),
                "con_differenze": sum(1 for r in results if r.differences and not r.errors),
                "errori": sum(1 for r in results if r.errors),
            },
            "results": [to_dict(r) for r in results],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False, default=str)

    # ── HTML ──────────────────────────────────────────────────────────────────
    def _html(self, results: List[ComparisonResult]) -> str:
        total     = len(results)
        identical = sum(1 for r in results if not r.has_differences)
        with_diff = sum(1 for r in results if r.differences and not r.errors)
        errors    = sum(1 for r in results if r.errors)
        now       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Summary table rows
        summary_rows = ""
        for r in results:
            badge = self._badge(r)
            anch  = _anchor(r.pair_id)
            summary_rows += (
                f"<tr>"
                f"<td><a href='#{anch}'>{_e(r.pair_id)}</a></td>"
                f"<td>{_e(r.pair_type.upper())}</td>"
                f"<td class='mono'>{_e(r.source_name)}</td>"
                f"<td class='mono'>{_e(r.target_name)}</td>"
                f"<td>{badge}</td>"
                f"</tr>"
            )

        pair_cards = "\n".join(self._render_pair(r) for r in results)

        return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Check Qualità Dati — Report</title>
  <style>{_CSS}</style>
</head>
<body id="top">
<div class="topbar">
  <div class="topbar-title">&#128269; Check Qualità Dati</div>
  <div class="topbar-meta">Generato: {now}</div>
</div>
<div class="container">

  <section class="card summary-card">
    <h2 class="card-title">Riepilogo</h2>
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-val">{total}</div><div class="kpi-lbl">Totale</div></div>
      <div class="kpi kpi-ok"><div class="kpi-val">{identical}</div><div class="kpi-lbl">Identiche</div></div>
      <div class="kpi kpi-diff"><div class="kpi-val">{with_diff}</div><div class="kpi-lbl">Differenze</div></div>
      <div class="kpi kpi-err"><div class="kpi-val">{errors}</div><div class="kpi-lbl">Errori</div></div>
    </div>
    <div class="tbl-scroll">
    <table class="tbl">
      <thead><tr><th>Pair ID</th><th>Tipo</th><th>Source</th><th>Target</th><th>Stato</th></tr></thead>
      <tbody>{summary_rows}</tbody>
    </table>
    </div>
  </section>

  {pair_cards}

</div>
</body>
</html>"""

    # ── Per-pair card ─────────────────────────────────────────────────────────
    @staticmethod
    def _badge(r: ComparisonResult) -> str:
        if r.errors:      return '<span class="badge badge-err">ERRORE</span>'
        if r.differences: return '<span class="badge badge-diff">DIFFERENZE</span>'
        return '<span class="badge badge-ok">IDENTICO</span>'

    @staticmethod
    def _card_class(r: ComparisonResult) -> str:
        if r.errors:      return "card card-err"
        if r.differences: return "card card-diff"
        return "card card-ok"

    def _render_pair(self, r: ComparisonResult) -> str:
        anch       = _anchor(r.pair_id)
        card_cls   = self._card_class(r)
        badge      = self._badge(r)

        # Stats bar
        stats_html = ""
        if r.stats:
            items = "".join(
                f"<span class='stat'><span class='stat-lbl'>{_e(k)}</span>"
                f"<span class='stat-val'>{_e(str(v))}</span></span>"
                for k, v in r.stats.items()
            )
            stats_html = f"<div class='stats-bar'>{items}</div>"

        # Errors
        errors_html = ""
        if r.errors:
            items = "".join(f"<li>{_e(e)}</li>" for e in r.errors)
            errors_html = (
                f"<div class='sub-section'>"
                f"<div class='sub-title err-title'>Errori</div>"
                f"<ul class='err-list'>{items}</ul></div>"
            )

        schema_html = self._render_schema(r)
        data_html   = self._render_data(r)

        return f"""
<section class="{card_cls}" id="{anch}">
  <div class="pair-header">
    <div>
      <span class="pair-id">{_e(r.pair_id)}</span>
      <span class="pair-type">{_e(r.pair_type.upper())}</span>
      {badge}
    </div>
    <a href="#top" class="back-top">&#8593; Su</a>
  </div>
  <div class="pair-meta">
    <span>Source:</span> <code>{_e(r.source_name)}</code>
    &nbsp;&#8594;&nbsp;
    <span>Target:</span> <code>{_e(r.target_name)}</code>
  </div>
  {stats_html}
  {errors_html}
  {schema_html}
  {data_html}
</section>"""

    # ── Schema differences ────────────────────────────────────────────────────
    def _render_schema(self, r: ComparisonResult) -> str:
        diffs = [d for d in r.differences if d.diff_type in _SCHEMA_TYPES]
        if not diffs:
            return ""
        _OP = {
            DiffType.SCHEMA_ADDED:   '<span class="op-add">&#43; AGGIUNTO</span>',
            DiffType.SCHEMA_REMOVED: '<span class="op-rem">&#8722; RIMOSSO</span>',
            DiffType.SCHEMA_CHANGED: '<span class="op-chg">&#8776; MODIFICATO</span>',
        }
        _BG = {
            DiffType.SCHEMA_ADDED:   "#eaffea",
            DiffType.SCHEMA_REMOVED: "#ffeaea",
            DiffType.SCHEMA_CHANGED: "#fffbea",
        }
        rows = ""
        for d in diffs:
            name = _e(d.location.split(":", 1)[-1])
            src  = _e(str(d.source_value)) if d.source_value is not None else "—"
            tgt  = _e(str(d.target_value)) if d.target_value is not None else "—"
            rows += (
                f"<tr style='background:{_BG.get(d.diff_type,'#fff')}'>"
                f"<td class='mono'>{name}</td>"
                f"<td>{_OP.get(d.diff_type,'')}</td>"
                f"<td class='mono'>{src}</td>"
                f"<td class='mono'>{tgt}</td></tr>"
            )
        return (
            f"<div class='sub-section'>"
            f"<div class='sub-title schema-title'>&#128196; Differenze Schema ({len(diffs)})</div>"
            f"<div class='tbl-scroll'>"
            f"<table class='tbl tbl-schema'>"
            f"<thead><tr><th>Elemento</th><th>Operazione</th><th>Source</th><th>Target</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></div>"
        )

    # ── Data differences ──────────────────────────────────────────────────────
    def _render_data(self, r: ComparisonResult) -> str:
        rd = r.report_data
        if not rd:
            return ""
        ct = rd.get("check_type", "")
        if ct in ("minus", "set_minus"):
            return self._render_minus_tables(r, rd)
        if ct == "xml_minus":
            return self._render_xml_minus(r, rd)
        return ""

    def _render_minus_tables(self, r: ComparisonResult, rd: Dict) -> str:
        columns   = rd.get("columns")
        only_src  = rd.get("only_in_source", [])
        only_tgt  = rd.get("only_in_target", [])
        trunc_s   = rd.get("truncated_source", False)
        trunc_t   = rd.get("truncated_target", False)
        total_s   = r.stats.get("solo_in_source", len(only_src))
        total_t   = r.stats.get("solo_in_target", len(only_tgt))

        if not only_src and not only_tgt:
            return ""

        is_str = bool(only_src) and isinstance(only_src[0], str)

        src_html = self._tabular_block(
            only_src, columns, total_s, trunc_s,
            title=f"Solo in Source ({total_s} righe)",
            title_class="src-title",
            th_class="tbl-src",
            is_str=is_str,
        )
        tgt_html = self._tabular_block(
            only_tgt, columns, total_t, trunc_t,
            title=f"Solo in Target ({total_t} righe)",
            title_class="tgt-title",
            th_class="tbl-tgt",
            is_str=is_str,
        )
        return src_html + tgt_html

    def _render_xml_minus(self, r: ComparisonResult, rd: Dict) -> str:
        only_src = rd.get("only_in_source", [])
        only_tgt = rd.get("only_in_target", [])
        trunc_s  = rd.get("truncated_source", False)
        trunc_t  = rd.get("truncated_target", False)
        total_s  = r.stats.get("solo_in_source", len(only_src))
        total_t  = r.stats.get("solo_in_target", len(only_tgt))

        if not only_src and not only_tgt:
            return ""

        def xml_table(records, title, title_class, th_class, total, truncated):
            if not records:
                return (
                    f"<div class='sub-section'>"
                    f"<div class='sub-title {title_class}'>{title}: nessuna</div></div>"
                )
            rows = "".join(
                f"<tr><td class='mono'>{_e(rec['path'])}</td>"
                f"<td>{_e(rec['value'])}</td></tr>"
                for rec in records
            )
            note = (
                f"<p class='trunc-note'>&#9888; Mostrate {len(records)} su {total} coppie</p>"
                if truncated else ""
            )
            return (
                f"<div class='sub-section'>"
                f"<div class='sub-title {title_class}'>{title}</div>"
                f"{note}"
                f"<div class='tbl-scroll'>"
                f"<table class='tbl {th_class}'>"
                f"<thead><tr><th>XPath</th><th>Valore</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div></div>"
            )

        return (
            xml_table(only_src, f"Solo in Source ({total_s})", "src-title", "tbl-src", total_s, trunc_s)
            + xml_table(only_tgt, f"Solo in Target ({total_t})", "tgt-title", "tbl-tgt", total_t, trunc_t)
        )

    @staticmethod
    def _tabular_block(
        records, columns, total, truncated,
        title, title_class, th_class, is_str=False,
    ) -> str:
        if not records:
            return (
                f"<div class='sub-section'>"
                f"<div class='sub-title {title_class}'>{_e(title)}: nessuna</div></div>"
            )
        note = (
            f"<p class='trunc-note'>&#9888; Mostrate {len(records)} su {total} righe</p>"
            if truncated else ""
        )
        if is_str:
            # TXT comparator — records are plain strings
            rows = "".join(
                f"<tr><td class='mono'>{_e(str(rec))}</td></tr>" for rec in records
            )
            header = "<tr><th>Riga</th></tr>"
        else:
            # DB / CSV comparator — records are dicts
            cols = columns or (list(records[0].keys()) if records else [])
            header = "".join(f"<th>{_e(str(c))}</th>" for c in cols)
            header = f"<tr>{header}</tr>"
            rows = ""
            for rec in records:
                cells = "".join(
                    f"<td class='mono'>{_e(str(rec.get(c, '')))}</td>" for c in cols
                )
                rows += f"<tr>{cells}</tr>"

        return (
            f"<div class='sub-section'>"
            f"<div class='sub-title {title_class}'>{_e(title)}</div>"
            f"{note}"
            f"<div class='tbl-scroll'>"
            f"<table class='tbl {th_class}'>"
            f"<thead>{header}</thead>"
            f"<tbody>{rows}</tbody></table></div></div>"
        )


# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
*, *::before, *::after { box-sizing: border-box; }
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0;
       background: #f0f2f5; color: #1a1a2e; font-size: 14px; }
a { color: #0057b8; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Top bar */
.topbar { background: #1a1a2e; color: #fff; padding: 12px 24px;
          display: flex; justify-content: space-between; align-items: center;
          position: sticky; top: 0; z-index: 100;
          box-shadow: 0 2px 8px rgba(0,0,0,.35); }
.topbar-title { font-size: 1.1em; font-weight: 700; letter-spacing: .4px; }
.topbar-meta  { font-size: .8em; opacity: .65; }

/* Layout */
.container { max-width: 1600px; margin: 0 auto; padding: 20px 24px; }

/* Cards */
.card { background: #fff; border-radius: 8px; padding: 20px 24px;
        margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.1);
        border-left: 5px solid #ccc; }
.card-ok   { border-left-color: #28a745; }
.card-diff { border-left-color: #ffc107; }
.card-err  { border-left-color: #dc3545; }
.summary-card { border-left-color: #0057b8; }
.card-title { margin-top: 0; font-size: 1.05em; }

/* KPI */
.kpi-row { display: flex; gap: 14px; flex-wrap: wrap; margin: 12px 0 18px; }
.kpi { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px;
       padding: 12px 20px; min-width: 90px; text-align: center; }
.kpi-ok   { border-color: #28a745; background: #f0fff4; }
.kpi-diff { border-color: #ffc107; background: #fffdf0; }
.kpi-err  { border-color: #dc3545; background: #fff5f5; }
.kpi-val  { font-size: 2em; font-weight: 700; line-height: 1.1; }
.kpi-lbl  { font-size: .72em; color: #6c757d; margin-top: 3px; }

/* Badges */
.badge { display: inline-block; padding: 3px 9px; border-radius: 4px;
         font-size: .73em; font-weight: 700; letter-spacing: .4px; vertical-align: middle; }
.badge-ok   { background: #28a745; color: #fff; }
.badge-diff { background: #ffc107; color: #1a1a2e; }
.badge-err  { background: #dc3545; color: #fff; }

/* Pair card header */
.pair-header { display: flex; justify-content: space-between;
               align-items: flex-start; margin-bottom: 6px; }
.pair-id   { font-size: 1.05em; font-weight: 700; margin-right: 8px; }
.pair-type { font-size: .75em; background: #495057; color: #fff;
             padding: 2px 7px; border-radius: 3px; margin-right: 6px;
             vertical-align: middle; }
.pair-meta { color: #495057; margin-bottom: 12px; font-size: .9em; }
.back-top  { font-size: .8em; white-space: nowrap; }

/* Stats bar */
.stats-bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.stat { background: #f0f2f5; border-radius: 5px; padding: 3px 10px;
        font-size: .8em; border: 1px solid #dee2e6; }
.stat-lbl { color: #6c757d; }
.stat-val { font-weight: 600; margin-left: 4px; }

/* Sub-sections */
.sub-section  { margin-top: 18px; }
.sub-title    { font-size: .78em; font-weight: 700; text-transform: uppercase;
                letter-spacing: .6px; padding-bottom: 4px; margin-bottom: 8px; }
.schema-title { color: #6f42c1; border-bottom: 2px solid #6f42c1; }
.src-title    { color: #c0392b; border-bottom: 2px solid #c0392b; }
.tgt-title    { color: #0057b8; border-bottom: 2px solid #0057b8; }
.err-title    { color: #dc3545; }

/* Tables */
.tbl-scroll { overflow-x: auto; }
.tbl { width: 100%; border-collapse: collapse; font-size: .84em; }
.tbl th { padding: 7px 10px; background: #495057; color: #fff;
           text-align: left; white-space: nowrap; }
.tbl td { padding: 6px 10px; border: 1px solid #dee2e6; vertical-align: top; }
.tbl tbody tr:nth-child(even) td { background: #f8f9fa; }
.tbl tbody tr:hover td { background: #e9ecef; }
.tbl-schema th { background: #6f42c1; }
.tbl-src    th { background: #c0392b; }
.tbl-tgt    th { background: #0057b8; }

/* Operation labels */
.op-add { color: #28a745; font-weight: 700; }
.op-rem { color: #dc3545; font-weight: 700; }
.op-chg { color: #856404; font-weight: 700; }

/* Error list */
.err-list { margin: 4px 0; padding-left: 18px; color: #dc3545; font-size: .9em; }

/* Misc */
.mono { font-family: 'Consolas', 'Courier New', monospace; font-size: .88em; }
code  { background: #f0f2f5; padding: 1px 5px; border-radius: 3px; font-size: .88em; }
.trunc-note { color: #856404; font-style: italic; font-size: .82em; margin: 3px 0 6px; }
"""
