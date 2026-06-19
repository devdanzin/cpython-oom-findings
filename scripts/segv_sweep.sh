#!/bin/bash
# Sweep every segv vehicle through segv_worker.sh in parallel and collect a TSV of
# deterministic local crash sites. Resumable: skips vehicles already in the out file.
# Usage: segv_sweep.sh [out.tsv] [parallelism]
set -u
OUT="${1:-/tmp/segv_sites.tsv}"
J="${2:-6}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Collect the segv crash dirs (stdout shows a segfault/SEGV).
mapfile -t DIRS < <(
  for sp in ~/crashers/python-*/*/stdout; do
    grep -qE 'Segmentation fault|AddressSanitizer: SEGV' "$sp" 2>/dev/null \
      && dirname "$sp"
  done
)
echo "# ${#DIRS[@]} segv vehicles; parallelism=$J; out=$OUT" >&2
touch "$OUT"
printf '%s\n' "${DIRS[@]}" | \
  xargs -P "$J" -I{} bash -c '
    lbl="$(basename "$(dirname "{}")")/$(basename "{}")"
    grep -qP "^\Q$lbl\E\t" "'"$OUT"'" 2>/dev/null && exit 0
    bash "'"$HERE"'/segv_worker.sh" "{}" >> "'"$OUT"'"
    echo "done: $lbl" >&2
  '
echo "# sweep complete: $(wc -l < "$OUT") lines in $OUT" >&2
