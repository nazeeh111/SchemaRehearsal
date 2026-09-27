"""A self-contained, escaped report without application result values."""

from html import escape


def render_html(report):
    e = lambda value: escape(str(value), quote=True)
    status = report["status"]
    title = {
        "matched": "Declared behaviors match",
        "changed": "A behavior changed",
        "invalid_baseline": "Baseline needs attention",
        "error": "Rehearsal could not finish",
    }[status]
    shape = lambda rows, columns: (
        f"{rows} row{'' if rows == 1 else 's'} · {columns} column{'' if columns == 1 else 's'}"
    )
    parts = []
    for case in report["scenarios"]:
        rows = []
        for step in case["steps"]:
            state = "same" if step["equal"] else "different"
            rows.append(
                f'<tr><th>Step {step["number"]}</th><td>{e(step["before"])}</td><td>{e(step["after"])}</td><td class="{state}">{state}</td></tr>'
            )
        for obs in case["observations"]:
            state = "same" if obs["equal"] else "different"
            a = shape(obs["before_rows"], obs["before_columns"])
            b = shape(obs["after_rows"], obs["after_columns"])
            rows.append(
                f'<tr><th>{e(obs["name"])}<small>{e(obs["order"])} comparison</small></th><td>{a}</td><td>{b}</td><td class="{state}">{state}</td></tr>'
            )
        parts.append(
            f'<section class="scenario"><div class="scenario-heading"><h2>{e(case["name"])}</h2><span class="pill">{e(case["status"])}</span></div><p class="scroll-hint">Scroll horizontally to compare Before, After and Result. Keyboard: focus the table and use arrow keys.</p><div class="table-wrap" tabindex="0" role="region" aria-label="{e(case["name"])} comparison"><table><thead><tr><th>Witness</th><th>Before</th><th>After migration</th><th>Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>'
        )
    checks = []
    for side, check in report["database_checks"].items():
        checks.append(
            f"<li><strong>{e(side.capitalize())}</strong> · integrity {'passed' if check['integrity_ok'] else 'failed'} · foreign keys {'passed' if check['foreign_keys_ok'] else 'failed'}</li>"
        )
    schema = (
        "".join(
            f'<li><span class="mono">{e(item["type"])} {e(item["name"])}</span> · {e(item["change"])}</li>'
            for item in report["schema_changes"]
        )
        or "<li>No schema object differences recorded.</li>"
    )
    hashes = "".join(
        f'<dt>{e(label)}</dt><dd class="mono">{e(report.get(key, "Unavailable"))}</dd>'
        for key, label in [
            ("sqlite_version", "SQLite engine"),
            ("snapshot_sha256", "Copied snapshot SHA-256"),
            ("migration_sha256", "Migration SHA-256"),
            ("suite_sha256", "Suite SHA-256"),
        ]
    )
    diagnostic = ""
    if "diagnostic" in report:
        diagnostic = f'<aside class="diagnostic"><strong>{e(report.get("stage", ""))}</strong><p>{e(report["diagnostic"])}</p><p>{e(report.get("error_code", ""))}</p></aside>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>SchemaRehearsal · {e(title)}</title>
<style>
:root{{--paper:#f5f3eb;--ink:#222e29;--muted:#59665c;--line:#c9d0c4;--accent:#255c46;--warning:#934128}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:48px 28px}}header{{border-top:7px solid var(--ink);padding-top:22px;margin-bottom:38px}}.brand{{font:700 13px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}}h1{{font-size:clamp(30px,5vw,56px);line-height:1.1;letter-spacing:-.045em;max-width:780px;margin:25px 0 18px}}.lede{{max-width:740px;color:var(--muted)}}.route{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;font:14px ui-monospace,monospace;margin-top:26px}}.route b{{border:1px solid var(--line);padding:8px 12px;background:#fff9}}.scenario{{margin:24px 0;border:1px solid var(--line);background:#fff8}}.scenario-heading{{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:18px 20px;border-bottom:1px solid var(--line)}}h2{{font-size:20px;margin:0;line-height:1.3}}.pill{{font:12px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.06em;padding:5px 9px;border:1px solid var(--line)}}.scroll-hint{{display:none}}.table-wrap{{overflow-x:auto}}.table-wrap:focus-visible{{outline:3px solid var(--accent);outline-offset:2px}}table{{border-collapse:collapse;width:100%;min-width:640px;text-align:left}}th,td{{padding:13px 20px;border-bottom:1px solid #dfe3d9;font-size:14px}}thead th{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}tbody th{{font-weight:500}}small{{display:block;color:var(--muted);font-size:11px}}.same{{color:var(--accent)}}.different{{color:var(--warning);font-weight:700}}.support{{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin:40px 0}}.support h2{{padding-bottom:12px;border-bottom:1px solid var(--line)}}ul{{list-style:none;padding:0}}li{{padding:7px 0;overflow-wrap:anywhere}}.mono{{font:12px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}}details{{border-top:1px solid var(--line);padding:20px 0}}summary{{cursor:pointer;font-weight:600}}dt{{font-size:12px;color:var(--muted);margin-top:14px}}dd{{margin:4px 0}}footer{{border-top:1px solid var(--line);padding-top:18px;font-size:13px;color:var(--muted)}}.diagnostic{{border-left:4px solid var(--warning);padding:12px 20px;background:#f0e5da}}@media(max-width:700px){{.scroll-hint{{display:block;font-size:12px;color:var(--muted);padding:0 20px}}main{{padding:25px 16px}}.support{{grid-template-columns:1fr}}.scenario-heading{{align-items:flex-start}}}}@media print{{body{{background:white}}main{{padding:0}}details{{display:block}}.scenario{{break-inside:avoid}}}}
</style></head><body><main><header><div class="brand">SchemaRehearsal / migration evidence</div><h1>{e(title)}</h1><p class="lede">Each scenario starts with its own copies of the same database snapshot. The same steps run before and after the migration. Results compare value types, values and duplicate rows.</p><div class="route"><b>Read-only source</b><span>→</span><b>Snapshot</b><span>→</span><b>Before / migrated copies</b><span>→</span><b>Behavior comparison</b></div></header>{diagnostic}{"".join(parts)}<div class="support"><section><h2>Database checks</h2><ul>{"".join(checks) or "<li>No database check completed.</li>"}</ul><p>Passing these checks does not establish unchanged application behavior.</p></section><section><h2>Schema context</h2><ul>{schema}</ul><p>Schema differences are context. The declared scenarios decide whether behavior matched.</p></section></div><details><summary>Reproduce this result</summary><dl>{hashes}</dl><p>Retain your original input files privately. This report contains no database snapshot, SQL, bound parameters, raw result cells, or raw SQLite error messages.</p></details><footer>Only declared scenarios were examined. A match is not a guarantee about other workloads, database versions, production concurrency, or malicious input. Scenario and schema names remain visible metadata. Local tool · no external assets or requests.</footer></main></body></html>"""
