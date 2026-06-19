#!/bin/bash
# Reduce a fuzzer vehicle to a minimal reproducer with shrinkray, pinned to the bug's
# crash signature (so it can't drift to a different bug). creduce is the fallback.
#
# Usage: minimize.sh <report-dir | vehicle.py> <signature-regex> [out.py]
#   env: OOM_N (runs/candidate, default 20), OOM_GIL (default 1), OOM_PY (interpreter)
#
# Always re-verify the reduced output at a higher OOM_N before trusting it.
set -eu
SRC="${1:?report dir or vehicle.py}"
SIG="${2:?signature regex}"
OUT="${3:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -d "$SRC" ] && SRC="$SRC/vehicle_source.py"
[ -f "$SRC" ] || { echo "no such source: $SRC"; exit 2; }

WORK="$(mktemp -d)"
cp "$SRC" "$WORK/cand.py"
export OOM_SIG="$SIG" OOM_N="${OOM_N:-20}" OOM_GIL="${OOM_GIL:-1}"

echo "[minimize] oracle sanity-check on the full vehicle (OOM_N=$OOM_N, GIL=$OOM_GIL, sig=/$SIG/)..."
if ! "$HERE/min_oracle.sh" "$WORK/cand.py"; then
    echo "[minimize] ORACLE FAILS ON THE VEHICLE -- adjust OOM_SIG / OOM_GIL / OOM_N before reducing."
    exit 3
fi
echo "[minimize] vehicle reproduces ($(wc -l <"$WORK/cand.py") lines). Reducing with shrinkray (niced)..."
nice -n 19 ~/venvs/shrinkray_venv/bin/shrinkray --input-type arg --volume normal \
    "$HERE/min_oracle.sh" "$WORK/cand.py" || true
echo "[minimize] reduced to $(wc -l <"$WORK/cand.py") lines -> $WORK/cand.py"
if [ -n "$OUT" ]; then cp "$WORK/cand.py" "$OUT"; echo "[minimize] copied -> $OUT"; fi
echo "[minimize] RE-VERIFY before trusting:  OOM_N=50 OOM_SIG='$SIG' $HERE/min_oracle.sh $WORK/cand.py && echo OK"
