#!/bin/bash
# Drive repro_collect.sh over a list of vehicles (default: the NOREPRO set) across the
# full local build matrix, in parallel, then aggregate which builds reproduced.
# Usage: norepro_matrix.sh [labels.txt] [out-root] [vehicle-parallelism] [timeout_s]
set -u
LIST="${1:-/tmp/norepro.txt}"
OUTROOT="${2:-catalog/norepro_repro}"
J="${3:-4}"; T="${4:-120}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUTROOT"
echo "# $(wc -l < "$LIST") vehicles x matrix; vehicle-parallelism=$J timeout=${T}s" >&2

xargs -P "$J" -I{} bash -c '
  lbl="{}"; safe="${lbl//\//__}"
  bash "'"$HERE"'/repro_collect.sh" "$HOME/crashers/$lbl" "'"$OUTROOT"'/$safe" "'"$T"'" >/dev/null 2>&1
  echo "done: $lbl" >&2
' < "$LIST"

echo "=== AGGREGATE ==="
python3 - "$OUTROOT" "$LIST" <<'PY'
import sys, os, collections
outroot, listf = sys.argv[1], sys.argv[2]
labels = open(listf).read().split()
repro_any, by_site = [], collections.Counter()
none = []
for lbl in labels:
    safe = lbl.replace("/", "__")
    sm = os.path.join(outroot, safe, "summary.tsv")
    if not os.path.exists(sm):
        continue
    crashed = []
    for line in open(sm):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 5 and f[2] == "crash":
            crashed.append((f[0], f"{f[4]} ({f[3]})"))
            by_site[f[4]] += 1
    if crashed:
        repro_any.append((lbl, crashed))
    else:
        none.append(lbl)
print(f"\nreproduced on >=1 build: {len(repro_any)} / {len(labels)}   |   still no-repro: {len(none)}\n")
for lbl, crashed in repro_any:
    tag = " ".join(f"{b}:{s}" for b, s in crashed)
    print(f"  REPRO  {lbl}\n         {tag}")
print("\n-- crash sites discovered across the matrix --")
for site, n in by_site.most_common():
    print(f"  {n:3}  {site}")
print(f"\n-- still no-repro on ANY build ({len(none)}) --")
for lbl in none:
    print(f"  {lbl}")
PY
