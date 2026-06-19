#!/usr/bin/env python3
"""Generate INDEX.md (the umbrella-issue draft) from reports/*/meta.json.

Source of truth is the per-report meta.json. Run after any report changes or
after publishing gists. Mirrors python/cpython#146102: a table of
Report | Description | Builds | Status, grouped by crash kind.
"""
import json, pathlib, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
KIND_TITLE = {"segv": "Segfaults", "abort": "Assertion / abort", "fatal": "Fatal Python error"}


def status_cell(d):
    s = d.get("status", "drafted")
    iss = d.get("upstream_issue")
    if s.startswith("fixed"):
        return f"**FIXED** {s.split(':',1)[1] if ':' in s else ''}".strip()
    if iss:
        return f"[#{iss}](https://github.com/python/cpython/issues/{iss})"
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
    by_kind = {}
    for d in metas:
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
    out.append(f"_{len(metas)} unique bug(s). Generated {datetime.date.today().isoformat()}._\n")
    out.append("_Found with [fusil](https://github.com/devdanzin/fusil)'s OOM-injection mode "
               "(fusil originally by Victor Stinner). Reports drafted by Claude Code; "
               "reproducers machine-generated._\n")
    out.append("Status legend: `draft` (not yet filed) · `report` (gist published) · "
               "`#N` (issue open) · **FIXED** `commit` · `dup:OOM-####` · `false alarm`.\n")

    for kind in ("segv", "abort", "fatal"):
        rows = by_kind.get(kind)
        if not rows:
            continue
        out.append(f"\n## {KIND_TITLE[kind]}\n")
        out.append("| Report | Description | Builds | Status |")
        out.append("|---|---|---|---|")
        for d in rows:
            builds = ",".join(k for k, v in d.get("matrix", {}).items()
                              if v not in (None, "n/a", "no-repro"))
            out.append(f"| {report_link(d)} | {d['description']} | {builds} | {status_cell(d)} |")

    (ROOT / "INDEX.md").write_text("\n".join(out) + "\n")
    print(f"wrote INDEX.md ({len(metas)} reports)")


if __name__ == "__main__":
    main()
