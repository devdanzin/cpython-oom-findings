#!/usr/bin/env python3
"""Append the umbrella-issue backlink footer to each report.md and push it to the gist.

Run once the umbrella issue is live. For each gisted report it appends a one-line
"part of <umbrella>" footer to report.md (on disk) and updates the published gist's
`OOM-####-report.md` file to match, via `PATCH /gists/{id}` (non-interactive; `gh gist
edit` opens an editor, so we use the API instead).

Idempotent: a report.md that already contains the umbrella marker is skipped and not
re-pushed unless `--force`.

  python3 scripts/add_umbrella_backlink.py --dry-run            # show the plan
  python3 scripts/add_umbrella_backlink.py OOM-0002             # one gist
  python3 scripts/add_umbrella_backlink.py                      # all gisted reports
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
UMBRELLA_URL = "https://github.com/python/cpython/issues/151763"
MARKER = "python/cpython#151763"
FOOTER = (f"\n---\n\n*Part of [{MARKER}]({UMBRELLA_URL}) — an umbrella tracking 35 "
          f"OOM-related crash findings.*\n")


def gist_id(url):
    return url.rstrip("/").split("/")[-1]


def patch_gist(gid, gist_filename, content):
    payload = json.dumps({"files": {gist_filename: {"content": content}}})
    out = subprocess.run(["gh", "api", "-X", "PATCH", f"/gists/{gid}", "--input", "-"],
                         input=payload, capture_output=True, text=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="OOM-#### ids (default: all gisted)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ap.add_argument("--force", action="store_true", help="re-push even if footer present")
    args = ap.parse_args()

    edited, skipped, failed = [], 0, 0
    for mp in sorted(REPORTS.glob("*/meta.json")):
        d = json.loads(mp.read_text())
        oid = d["id"]
        if args.ids and oid not in args.ids:
            continue
        url = d.get("gist_url")
        if not url:
            print(f"{oid}: no gist_url — skip")
            skipped += 1
            continue
        rp = mp.parent / "report.md"
        text = rp.read_text()
        present = MARKER in text
        if present and not args.force:
            print(f"{oid}: backlink already present — skip")
            skipped += 1
            continue
        new = text if present else text.rstrip() + "\n" + FOOTER
        gist_filename = f"{oid}-report.md"
        if args.dry_run:
            print(f"{oid}: would {'re-push' if present else 'append footer + push'} "
                  f"{gist_filename} -> {url}")
            edited.append(oid)
            continue
        if not present:
            rp.write_text(new)
        out = patch_gist(gist_id(url), gist_filename, new)
        if out.returncode != 0:
            print(f"{oid}: ERROR {out.stderr.strip()}", file=sys.stderr)
            failed += 1
            continue
        print(f"{oid}: pushed backlink -> {url}")
        edited.append(oid)

    verb = "(dry-run) would edit" if args.dry_run else "edited"
    print(f"\n{verb}: {len(edited)}  |  skipped: {skipped}  |  failed: {failed}")


if __name__ == "__main__":
    main()
