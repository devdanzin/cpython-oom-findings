#!/bin/bash
# Run a reproducer across the local CPython build matrix and capture a gdb
# backtrace from the free-threaded debug+ASan build.
#
# Usage: triage_matrix.sh <repro.py> [bt_out.txt]
#
# Prints one line per build. Interpretation: ASan builds exit rc=1 on SIGSEGV
# ("ABORTING"); non-ASan builds exit rc=139 (or negative). rc=0 ("no crash") or a
# clean Python traceback means that build did not reproduce. Compare crashes by
# the gdb backtrace, NOT by exit code or the ASan re-raise pc.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env.sh"          # MATRIX_BUILDS (name=path pairs), OOM_PY (workhorse)
REPRO="${1:?usage: triage_matrix.sh <repro.py> [bt_out.txt]}"
BT_OUT="${2:-/dev/stdout}"

declare -A PY=(); NAMES=()
for pair in $MATRIX_BUILDS; do        # intentional word-split; each pair is name=path
  PY[${pair%%=*}]="${pair#*=}"; NAMES+=("${pair%%=*}")
done
for name in "${NAMES[@]}"; do
  bin="${PY[$name]}"
  [ -x "$bin" ] || { printf '%-16s MISSING\n' "$name"; continue; }
  ASAN_OPTIONS=detect_leaks=0 timeout 200 "$bin" "$REPRO" >/tmp/triage_$name.out 2>&1
  rc=$?
  tail=$(grep -m1 -oE 'AddressSanitizer: SEGV|no crash|Error|Traceback' /tmp/triage_$name.out)
  printf '%-16s rc=%-4s %s\n' "$name" "$rc" "$tail"
done
# Authoritative backtrace from the workhorse (FT debug+ASan) build:
ASAN_OPTIONS=detect_leaks=0:abort_on_error=0 timeout 200 gdb -q -batch \
  -ex 'set pagination off' -ex 'set print frame-arguments none' -ex 'set debuginfod enabled off' \
  -ex run -ex 'bt 12' --args "$OOM_PY" "$REPRO" 2>&1 \
  | grep -E 'Program received|^#[0-9]' > "$BT_OUT"
