#!/bin/bash
# Signature-pinned interestingness oracle for shrinkray / creduce.
#
# Exits 0 (INTERESTING) iff the candidate still crashes with the TARGET signature on the
# debug build within N runs. Pinning the signature is essential: the fuzzer vehicles are
# multi-bug, so an "any crash" oracle would happily reduce toward a *different* bug.
#
# Config via env:
#   OOM_PY   target interpreter (default: ft_debug_asan build)
#   OOM_GIL  PYTHON_GIL value    (default: 1)
#   OOM_SIG  signature regex     (REQUIRED -- the bug's distinctive assert/site, e.g.
#                                 '_PyUnicode_NONCOMPACT_DATA' or '_excinfo_clear_type')
#   OOM_N    runs per candidate  (default: 20; use ~5 for deterministic vehicles, 30-50 for flaky)
#   OOM_T    per-run timeout sec (default: 60)
#
# Usage (shrinkray --input-type arg):  min_oracle.sh <candidate.py>
set -u
CAND="${1:?candidate file}"
PY="${OOM_PY:-/home/danzin/projects/3.16_ft_debug_asan_cpython/python}"
GIL="${OOM_GIL:-1}"
SIG="${OOM_SIG:?set OOM_SIG to the signature regex}"
N="${OOM_N:-20}"
T="${OOM_T:-60}"

# Fast-reject syntactically-broken reductions (cheap, avoids N wasted runs).
"$PY" -c "compile(open('$CAND','rb').read(), '$CAND', 'exec')" 2>/dev/null || exit 1

for _ in $(seq 1 "$N"); do
    out=$(PYTHON_GIL="$GIL" ASAN_OPTIONS=detect_leaks=0:abort_on_error=0 \
          timeout "$T" "$PY" -u "$CAND" 2>&1)
    printf '%s' "$out" | grep -qaE "$SIG" && exit 0
done
exit 1
