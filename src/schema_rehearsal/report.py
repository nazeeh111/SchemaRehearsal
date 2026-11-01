"""A self-contained, escaped report without application result values."""

from html import escape


def _e(value):
    return escape(str(value), quote=True)


def _document(title, content):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Keepstep · {_e(title)}</title>
<style>{STYLE}</style></head><body><main>{content}<footer>Keepstep · Self-contained migration evidence</footer></main></body></html>"""


def _table_help():
    return '<p class="table-help" id="table-help">Scroll a comparison to see every column. Keyboard: focus the table and use arrow keys.</p>'


def _method_details(sequence=False):
    sequence_note = (
        '<p>Changed checkpoints keep the sequence changed even if later repaired. Errors stop the sequence; later checkpoints are not run. Every checkpoint compares with the frozen starting snapshot.</p>'
        if sequence else ''
    )
    return (
        '<details class="method"><summary>Method, privacy and limits</summary>'
        '<p>Each scenario starts with its own fresh copies of the same database snapshot. The same steps run before and after migration. Comparisons preserve value types, values and duplicate rows, using each observation’s declared ordering.</p>'
        '<p>Schema differences provide context. Passing integrity and foreign-key checks does not establish unchanged application behavior.</p>'
        f'{sequence_note}'
        '<p>Only declared scenarios were examined. A match is not a guarantee about other workloads, database versions, production concurrency or malicious input.</p>'
        '<p>This report omits the database snapshot, SQL, bound parameters, source paths, raw result cells and raw SQLite error messages. Scenario, observation and schema names, shapes and hashes remain visible metadata. Retain original input files privately.</p>'
        '<p>No external assets or requests.</p></details>'
    )


def render_html(report):
    title = {
        "matched": "Declared behaviors match",
        "changed": "A behavior changed",
        "invalid_baseline": "Baseline needs attention",
        "error": "Rehearsal could not finish",
    }[report["status"]]
    changed = sum(case["status"] == "changed" for case in report["scenarios"])
    matched = sum(case["status"] == "matched" for case in report["scenarios"])
    stats = (
        f'<p class="result-summary"><strong class="{"different" if changed else ""}">{changed} changed</strong><span>{matched} matched</span>'
        f'<span>{len(report["scenarios"])} scenarios recorded</span></p>'
        if report["scenarios"] else ''
    )
    checks = ''.join(
        f'<li><strong>{_e(side.capitalize())}</strong><span>Integrity {"passed" if check["integrity_ok"] else "failed"} · foreign keys {"passed" if check["foreign_keys_ok"] else "failed"}</span></li>'
        for side, check in report["database_checks"].items()
    ) or '<li>No database check completed.</li>'
    schema = ''.join(
        f'<li><span class="mono">{_e(item["type"])} {_e(item["name"])}</span><span>{_e(item["change"])}</span></li>'
        for item in report["schema_changes"]
    ) or '<li>No schema object differences recorded.</li>'
    hashes = ''.join(
        f'<dt>{_e(label)}</dt><dd class="mono">{_e(report.get(key, "Unavailable"))}</dd>'
        for key, label in [
            ("sqlite_version", "SQLite engine"),
            ("snapshot_sha256", "Copied snapshot SHA-256"),
            ("migration_sha256", "Migration SHA-256"),
            ("suite_sha256", "Suite SHA-256"),
        ]
    )
    content = f'''<header><div class="brand">Keepstep</div><h1>{_e(title)}</h1>{stats}<p class="lede">Only declared workloads were tested. “Same” compares values and types, not just row counts.</p></header>
{_fts5_notice(report)}{_diagnostic_html(report)}{_table_help()}{_scenario_sections(report)}
<div class="support"><section><h2>Database checks</h2><ul>{checks}</ul></section><section><h2>Schema changes</h2><ul>{schema}</ul></section></div>
<details class="evidence"><summary>Reproduction evidence</summary><dl>{hashes}</dl></details>{_method_details()}'''
    return _document(title, content)


def _shape(rows, columns):
    return (
        f'<strong class="row-count">{_e(rows)} row{"" if rows == 1 else "s"}</strong>'
        f'<span class="column-count">{_e(columns)} column{"" if columns == 1 else "s"}</span>'
    )


def _scenario_sections(report):
    parts = []
    for case in report["scenarios"]:
        rows = []
        for step in case["steps"]:
            state = "same" if step["equal"] else "different"
            rows.append(
                f'<tr class="{state}-row"><th scope="row">Step {_e(step["number"])}</th><td class="step-value">{_e(step["before"])}</td><td class="step-value">{_e(step["after"])}</td><td class="{state}">{state}</td></tr>'
            )
        if "commit" in case:
            commit = case["commit"]
            state = "same" if commit["equal"] else "different"
            rows.append(
                f'<tr class="{state}-row"><th scope="row">Commit<small>Engine-controlled transaction</small></th><td class="step-value">{_e(commit["before"])}</td><td class="step-value">{_e(commit["after"])}</td><td class="{state}">{state}</td></tr>'
            )
        for obs in case["observations"]:
            state = "same" if obs["equal"] else "different"
            rows.append(
                f'<tr class="{state}-row"><th scope="row">{_e(obs["name"])}<small>{_e(obs["order"])} comparison</small></th><td>{_shape(obs["before_rows"], obs["before_columns"])}</td><td>{_shape(obs["after_rows"], obs["after_columns"])}</td><td class="{state}">{state}</td></tr>'
            )
        state_class = ' scenario-changed' if case['status'] == 'changed' else ''
        parts.append(
            f'<section class="scenario{state_class}"><div class="scenario-heading"><h2>{_e(case["name"])}</h2><span class="pill">{_e(case["status"])}</span></div><div class="table-wrap" tabindex="0" role="region" aria-label="{_e(case["name"])} comparison" aria-describedby="table-help"><table><thead><tr><th scope="col">Witness</th><th scope="col">Before</th><th scope="col">After migration</th><th scope="col">Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>'
        )
    return ''.join(parts)


def render_sequence_html(report):
    title = {
        "matched": "Every checkpoint matches",
        "changed": "An intermediate behavior changed",
        "invalid_baseline": "Baseline needs attention",
        "error": "Sequence could not finish",
    }[report["status"]]
    first = report["first_changed"]
    summary = (
        f'First observed change: checkpoint {_e(first)}.'
        if first else 'No behavior change observed in completed checkpoints.'
    )
    rows, checkpoints = [], []
    for checkpoint in report["checkpoints"]:
        number, state = checkpoint["number"], checkpoint["status"]
        state_class = 'different' if state == 'changed' else ''
        rows.append(
            f'<tr><th scope="row"><a href="#checkpoint-{_e(number)}">Checkpoint {_e(number)}</a></th><td class="{state_class}">{_e(state)}</td></tr>'
        )
        child_content = '<p>No comparison report was produced for this checkpoint.</p>'
        if "report" in checkpoint:
            child = checkpoint["report"]
            checks = ' · '.join(
                f'{side}: integrity {"passed" if c["integrity_ok"] else "failed"}, foreign keys {"passed" if c["foreign_keys_ok"] else "failed"}'
                for side, c in child["database_checks"].items()
            )
            schema = ''.join(
                f'<li>{_e(x["type"])} {_e(x["name"])} · {_e(x["change"])}</li>'
                for x in child["schema_changes"]
            ) or '<li>No schema object differences.</li>'
            child_content = (
                f'<p class="checkpoint-checks">{_e(checks)}</p>{_diagnostic_html(child)}'
                f'{_scenario_sections(child)}<h3>Schema compared with starting snapshot</h3><ul>{schema}</ul>'
            )
        checkpoints.append(
            f'<details class="checkpoint" id="checkpoint-{_e(number)}" {"open" if state != "matched" else ""}>'
            f'<summary>Checkpoint {_e(number)} · {_e(state)}</summary>{child_content}'
            f'<dl class="checkpoint-identity"><dt>Migration SHA-256</dt><dd class="mono">{_e(checkpoint["migration_sha256"])}</dd></dl></details>'
        )
    hashes = ''.join(
        f'<dt>{_e(label)}</dt><dd class="mono">{_e(report.get(key) or "Unavailable")}</dd>'
        for key, label in [
            ("snapshot_sha256", "Starting snapshot SHA-256"),
            ("suite_sha256", "Suite SHA-256"),
            ("sequence_sha256", "Ordered migration hash list SHA-256"),
        ]
    )
    diagnostic = f'<p class="diagnostic">{_e(report["diagnostic"])}</p>' if 'diagnostic' in report else ''
    content = f'''<header><div class="brand">Keepstep · Migration sequence</div><h1>{_e(title)}</h1><p class="sequence-result">{summary} Final checkpoint: <strong>{_e(report["final_status"])}</strong>.</p><p class="lede">Only declared workloads were tested. A later repair does not erase an earlier change.</p></header>
{_fts5_notice(report)}{diagnostic}<section class="scenario"><div class="scenario-heading"><h2>Ordered checkpoints</h2><span class="pill">{_e(report["status"])}</span></div><table class="checkpoint-table"><thead><tr><th scope="col">Checkpoint</th><th scope="col">Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></section>
{_table_help()}{"".join(checkpoints)}<details class="evidence"><summary>Reproduction evidence</summary><dl><dt>SQLite engine</dt><dd class="mono">{_e(report["sqlite_version"])}</dd>{hashes}</dl></details>{_method_details(sequence=True)}'''
    return _document(title, content)


def _diagnostic_html(report):
    e = _e
    diagnostic = ""
    if "diagnostic" in report:
        context = ""
        if "scenario" in report:
            context += f"<p>Scenario: {e(report['scenario'])}</p>"
        if "commit" in report:
            context += f"<p>Baseline commit: {e(report['commit']['before'])} · expected {e(report['commit']['expected'])}</p>"
            context += (
                "<ul>"
                + "".join(
                    f"<li>Step {e(step['number'])}: {e(step['actual'])} · expected {e(step['expected'])}</li>"
                    for step in report.get("steps", [])
                )
                + "</ul>"
            )
        diagnostic = f'<aside class="diagnostic"><strong>{e(report.get("stage", ""))}</strong><p>{e(report["diagnostic"])}</p>{context}<p>{e(report.get("error_code", ""))}</p></aside>'
    return diagnostic


def _fts5_notice(report):
    if not report.get("fts5_enabled"):
        return ""
    return (
        '<aside class="notice"><strong>Built-in FTS5 enabled</strong>'
        '<p>Search comparisons cover declared observations, not full FTS5 index-to-content consistency.</p></aside>'
    )


STYLE = """/* Hallmark-informed evidence sheet; retained Keepstep light report identity. */
/* Critique: the actual before/after witness leads; method and privacy remain available in native disclosures. */
:root{--paper:#fff;--ink:#171923;--muted:#424957;--line:#cdd2df;--accent:#4a36b7;--warning:#9b2737;--changed:#fff3e4;--notice:#f3f0ff;--rule:#e2e5ed;--diagnostic:#fff0f3;--body:system-ui,sans-serif;--mono:ui-monospace,monospace}
*{box-sizing:border-box}html,body{overflow-x:clip}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 var(--body)}main{max-width:1120px;margin:auto;padding:40px 32px}header{border-top:5px solid var(--ink);padding-top:20px;margin-bottom:28px}.brand{font-size:18px;font-weight:700}h1{font-size:clamp(32px,5vw,58px);line-height:1.08;letter-spacing:-.045em;max-width:900px;margin:24px 0 18px}.lede{max-width:760px;margin:16px 0 0}.result-summary{display:flex;gap:12px 28px;flex-wrap:wrap;margin:0;font-size:18px}.sequence-result{font-size:20px;margin:0;max-width:800px}.scenario{margin:22px 0 30px;border:1px solid var(--line);background:var(--paper)}.scenario-changed{border-left:5px solid var(--warning)}.scenario-heading{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:18px 22px;border-bottom:1px solid var(--line)}h2{font-size:22px;margin:0;line-height:1.3}.pill{font-size:16px;font-weight:600}.table-help{display:none}.table-wrap{overflow-x:auto}.table-wrap:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:3px}table{border-collapse:collapse;width:100%;min-width:620px;text-align:left}th,td{padding:16px 22px;border-bottom:1px solid var(--rule);font-size:16px;vertical-align:top}thead th{font-weight:650;font-size:16px;color:var(--ink)}tbody th{font-weight:600;width:37%}small{display:block;color:var(--muted);font-size:16px;font-weight:400;margin-top:3px}.row-count{display:block;font-size:22px;line-height:1.35;white-space:nowrap}.column-count{display:block;font-size:16px;color:var(--muted);white-space:nowrap}.same{color:var(--ink)}.different{color:var(--warning);font-weight:750}.different-row{background:var(--changed)}.step-value{overflow-wrap:anywhere}.support{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:34px;margin:38px 0}.support h2{padding-bottom:12px;border-bottom:1px solid var(--line)}ul{list-style:none;padding:0;margin:12px 0}li{padding:7px 0;overflow-wrap:anywhere}.support li span{display:block}.mono{font:16px/1.6 var(--mono);overflow-wrap:anywhere}details{border-top:1px solid var(--line);padding:20px 0}summary{cursor:pointer;font-size:18px;font-weight:650;scroll-margin-top:20px}details p{max-width:780px}dt{font-size:16px;font-weight:600;margin-top:16px}dd{margin:5px 0}.checkpoint-table{min-width:0}.checkpoint-table th{width:65%}a{color:var(--accent);text-underline-offset:4px}.checkpoint{padding:22px 0}.checkpoint>summary{font-size:22px}.checkpoint-checks{color:var(--muted)}.checkpoint-identity{margin-top:24px}h3{font-size:18px;margin-top:26px}footer{border-top:1px solid var(--line);margin-top:12px;padding-top:18px;font-size:16px}.diagnostic,.notice{padding:14px 20px;margin:24px 0;border-left:4px solid var(--warning);background:var(--diagnostic)}.diagnostic p,.notice p{margin:4px 0;max-width:780px}.notice{border-color:var(--accent);background:var(--notice)}
@media(max-width:700px){main{padding:24px 16px}.support{grid-template-columns:minmax(0,1fr);gap:22px}.scenario-heading{align-items:flex-start;padding:16px}.table-help{display:block;margin:18px 0;font-size:16px}.result-summary{gap:8px 18px}.scenario-heading h2{font-size:21px}th,td{padding:14px 16px}.checkpoint>summary{font-size:21px}}
@media print{body{background:var(--paper)}main{padding:0}.table-help{display:none}.table-wrap{overflow:visible}table{min-width:0}details{display:block;break-inside:auto}details>*{display:block}details::details-content{display:block;content-visibility:visible}.scenario{break-inside:avoid}h1{font-size:32px}th,td{padding:10px 12px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""
