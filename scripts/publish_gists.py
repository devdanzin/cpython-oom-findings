#!/usr/bin/env python3
"""Publish each report as a PUBLIC gist and record the URL back into its meta.json.

Per report it creates one gist containing `report.md` + `repro.py` + `backtrace.txt`
(`gh gist create --public --desc "<id>: <title>"`), then writes `gist_url` into the
report's `meta.json` and flips `status` to `gisted`. The meta.json edit is a surgical
string replace (only the two fields) so your hand-formatting is preserved.

Idempotent: a report that already has a `gist_url` is skipped unless `--force`. Use
`--dry-run` to see exactly what would be published without creating anything.

After publishing, run `python3 scripts/gen_index.py` to relink INDEX.md to the gists.

Requires `gh` authenticated (`gh auth status`). Gists are PUBLIC and indexable — only run
this once the reports have been reviewed and the maintainer has approved.

  python3 scripts/publish_gists.py --dry-run                 # show the plan
  python3 scripts/publish_gists.py OOM-0001 OOM-0028         # publish a specific subset
  python3 scripts/publish_gists.py                           # publish all not-yet-gisted
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
GIST_FILES = ("report.md", "repro.py", "backtrace.txt")


def gh_gist_create(files, desc, dry):
    cmd = ["gh", "gist", "create", "--public", "--desc", desc] + [str(f) for f in files]
    if dry:
        print("    would run:", " ".join(["gh", "gist", "create", "--public",
                                          "--desc", repr(desc), *[f.name for f in files]]))
        return None
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print("    ERROR:", out.stderr.strip(), file=sys.stderr)
        return None
    # gh prints the gist URL as the last line of stdout
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    url = lines[-1] if lines else None
    if not url or not url.startswith("https://"):
        print("    ERROR: could not parse gist URL from gh output:", out.stdout, file=sys.stderr)
        return None
    return url


def record(meta_path, url):
    """Set gist_url + status=gisted in meta.json without reformatting the rest."""
    text = meta_path.read_text()
    text, n1 = re.subn(r'"gist_url":\s*(?:null|"[^"]*")', f'"gist_url": {json.dumps(url)}', text, count=1)
    text, n2 = re.subn(r'"status":\s*"[^"]*"', '"status": "gisted"', text, count=1)
    if n1 != 1 or n2 != 1:
        print(f"    WARN: meta.json field replace touched gist_url={n1} status={n2} (expected 1 each)")
    json.loads(text)  # fail loudly rather than write invalid JSON
    meta_path.write_text(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="OOM-#### ids to publish (default: all not-yet-gisted)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, create nothing")
    ap.add_argument("--force", action="store_true", help="recreate even if gist_url is already set")
    args = ap.parse_args()

    published, skipped, failed, would = [], 0, 0, 0
    for mp in sorted(REPORTS.glob("*/meta.json")):
        d = json.loads(mp.read_text())
        oid = d["id"]
        if args.ids and oid not in args.ids:
            continue
        if d.get("gist_url") and not args.force:
            print(f"{oid}: already gisted ({d['gist_url']}) — skip")
            skipped += 1
            continue
        files = [mp.parent / f for f in GIST_FILES]
        missing = [f.name for f in files if not f.exists()]
        if missing:
            print(f"{oid}: MISSING {missing} — skip")
            failed += 1
            continue
        desc = f"{oid}: {d.get('title', '')}".strip()[:250]
        print(f"{oid}: {desc[:78]}")
        url = gh_gist_create(files, desc, args.dry_run)
        if args.dry_run:
            would += 1
            continue
        if url:
            record(mp, url)
            published.append((oid, url))
            print(f"    -> {url}  (meta.json updated)")
        else:
            failed += 1

    n = would if args.dry_run else len(published)
    verb = "(dry-run) would publish" if args.dry_run else "published"
    print(f"\n{verb}: {n}  |  skipped(already-gisted): {skipped}  |  failed: {failed}")
    if published and not args.dry_run:
        print("Next: python3 scripts/gen_index.py   # relink INDEX.md to the gists")


if __name__ == "__main__":
    main()
