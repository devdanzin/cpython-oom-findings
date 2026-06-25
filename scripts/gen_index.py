#!/usr/bin/env python3
"""Generate INDEX.md (the umbrella-issue draft) from reports/*/meta.json.

Source of truth is the per-report meta.json. Run after any report changes or
after publishing gists. Mirrors python/cpython#146102: a table of
Report | Title | Crashing builds | Status, grouped by crash kind.
"""
import json
import pathlib
import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
KIND_TITLE = {"segv": "Segfaults", "abort": "Assertion / abort", "fatal": "Fatal Python error"}


def issue_link(iss):
    return f"[#{iss}](https://github.com/python/cpython/issues/{iss})"


def status_cell(d, by_id):
    s = d.get("status", "drafted")
    if s == "folded":
        # retired duplicate: point at the bug it was folded into, and that bug's issue if filed
        tgt = d.get("folded_into", "?")
        t = by_id.get(tgt, {})
        suffix = f" → {issue_link(t['upstream_issue'])}" if t.get("upstream_issue") else ""
        return f"\U0001f501 dup of {tgt}{suffix}"
    iss = d.get("upstream_issue")
    if s.startswith("fixed"):
        return f"**FIXED** {s.split(':',1)[1] if ':' in s else ''}".strip()
    if iss:
        return issue_link(iss)
    if s == "false_alarm":
        return "false alarm"
    if s.startswith("dup"):
        return s
    return {"gisted": "report", "drafted": "draft"}.get(s, s)


def report_link(d):
    url = d.get("gist_url")
    target = url if url else f"reports/{d['id']}-{d['slug']}/report.md"
    return f"[{d['id']}]({target})"


def main():
    metas = sorted((json.loads(p.read_text()) for p in REPORTS.glob("*/meta.json")),
                   key=lambda d: d["id"])
    by_id = {d["id"]: d for d in metas}
    # 'folded' entries are retired IDs merged into another bug (which carries the dedup
    # keys). They are NOT distinct bugs, so they don't count toward the unique total -- but
    # we still LIST them (marked as duplicates, with their dup target) so the published gist
    # link isn't lost and nobody re-investigates one. Mirrors how the live umbrella marks them.
    active = [d for d in metas if d.get("status") != "folded"]
    folded = [d for d in metas if d.get("status") == "folded"]
    by_kind = {}
    for d in metas:  # include folded: they render as marked dup rows within their kind table
        by_kind.setdefault(d.get("crash_kind", "segv"), []).append(d)

    out = []
    out.append("# CPython OOM-injection findings (fusil)\n")
    out.append("Crashes found by allocation-failure fuzzing (`_testcapi.set_nomemory`) of "
               "CPython 3.16.0a0. Each row links to a self-contained report (gist) with a "
               "minimal reproducer, backtrace, root cause, and suggested fix.\n")
    out.append("**Pick anything to work on** — open a CPython issue if one doesn't exist, "
               "comment with the issue/PR, and the Status column will be updated. Reports are "
               "deduped by crash signature; one row = one underlying bug (vehicles listed in "
               "the report).\n")
    folded_note = f" (+{len(folded)} folded duplicate(s), marked \U0001f501)" if folded else ""
    out.append(f"_{len(active)} unique bug(s){folded_note}. "
               f"Generated {datetime.date.today().isoformat()}._\n")
    out.append("_Found with [fusil](https://github.com/devdanzin/fusil)'s OOM-injection mode "
               "(fusil originally by Victor Stinner). Reports drafted by Claude Code; "
               "reproducers machine-generated._\n")
    out.append("Status legend: `draft` (not yet filed) · `report` (gist published) · "
               "`#N` (issue open) · **FIXED** `commit` · \U0001f501 `dup of OOM-####` "
               "(folded duplicate — don't pursue) · `false alarm`.\n")

    for kind in ("segv", "abort", "fatal"):
        rows = by_kind.get(kind)
        if not rows:
            continue
        out.append(f"\n## {KIND_TITLE[kind]}\n")
        out.append("| Report | Title | Crashing builds | Status |")
        out.append("|---|---|---|---|")
        for d in rows:
            builds = ",".join(k for k, v in d.get("matrix", {}).items()
                              if v not in (None, "n/a", "no-repro"))
            # the concise title (== the report's H1); the gist holds the full detail
            title = d.get("title") or d["description"]
            if d.get("status") == "folded":  # strike + tag so it reads as a dup at a glance
                title = f"~~{title}~~ _(superseded)_"
            out.append(f"| {report_link(d)} | {title} | {builds} | {status_cell(d, by_id)} |")

    (ROOT / "INDEX.md").write_text("\n".join(out) + "\n")
    print(f"wrote INDEX.md ({len(active)} unique + {len(folded)} folded)")


if __name__ == "__main__":
    main()
