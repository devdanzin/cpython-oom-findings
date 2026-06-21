#!/bin/bash
# Portable OOM-crasher reproduction collector. Runs one fuzzing vehicle's source.py
# across a configurable set of CPython builds, faithfully mirroring how fusil invoked
# it, and collects per build: full stdout/stderr, exit code, a crash classification, a
# crash rate over N runs (flakiness), and a gdb backtrace + resolved site for any
# build that crashes. Writes <out>/summary.tsv and per-build logs.
#
# Faithful to fusil's invocation (see a crash dir's replay.py / session.log):
#   env PYTHON_GIL=0 ASAN_OPTIONS=detect_leaks=0 ; python -u source.py ; cwd = source dir.
#
# DEPLOYABLE TO THE FUZZING HOST -- the host's own crashing binary is the most faithful
# target. Override the build map via $REPRO_BUILDS:
#   REPRO_BUILDS="host=/home/ubuntu/projects/upstream_cpython/python" \
#     REPRO_RUNS=10 repro_collect.sh <crash-dir> <out-dir>
#
# Env knobs:
#   REPRO_BUILDS  "name=/abs/python ..."   (default: $MATRIX_BUILDS from env.sh)
#   REPRO_RUNS    N runs per build for flakiness (default 1)
#   REPRO_GIL     0 | 1 | both   GIL mode(s) to try (default both; matters -- some OOM
#                 crashes reproduce only GIL-off, others only GIL-on). Host used 0.
# Usage: repro_collect.sh <source.py | crash-dir> <out-dir> [timeout_s]
set -u
. "$(cd "$(dirname "$0")" && pwd)/env.sh"   # MATRIX_BUILDS default (overridable)
SRC="${1:?usage: repro_collect.sh <source.py|crash-dir> <out-dir> [timeout_s]}"
OUT="${2:?need out-dir}"; T="${3:-120}"
[ -d "$SRC" ] && { SRCDIR="$SRC"; SRC="$(cd "$SRC" && pwd)/source.py"; } || SRCDIR="$(cd "$(dirname "$SRC")" && pwd)"
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
RUNS="${REPRO_RUNS:-1}"
case "${REPRO_GIL:-both}" in 0) GILS="0";; 1) GILS="1";; *) GILS="0 1";; esac

BUILDS="${REPRO_BUILDS:-$MATRIX_BUILDS}"

run_once() {  # <bin> <gil> <logfile> ; writes combined output, returns rc
  ( cd "$SRCDIR" && PYTHON_GIL="$2" ASAN_OPTIONS=detect_leaks=0:abort_on_error=0 \
      timeout "$T" "$1" -u "$SRC" ) > "$3" 2>&1
}
is_crash() {  # <logfile> <rc>
  grep -qE 'AddressSanitizer|Segmentation fault|Assertion .* failed|Fatal Python error: (Segmentation|Aborted)|core dumped' "$1" && return 0
  [ "$2" -ge 128 ] && return 0
  return 1
}

SUM="$OUT/summary.tsv"; : > "$SUM"
for kv in $BUILDS; do
  name="${kv%%=*}"; bin="${kv#*=}"
  if [ ! -x "$bin" ]; then printf '%s\tMISSING\t-\t-\t%s\n' "$name" "$bin" >> "$SUM"; continue; fi
  for gil in $GILS; do
    tag="${name}_gil${gil}"; log="$OUT/$tag.out"; hits=0; lastrc=0
    for i in $(seq 1 "$RUNS"); do
      run_once "$bin" "$gil" "$log"; lastrc=$?
      if is_crash "$log" "$lastrc"; then hits=$((hits+1)); cp "$log" "$OUT/$tag.crash.out"; fi
    done
    crash=""; [ "$hits" -gt 0 ] && crash="crash"
    [ -z "$crash" ] && [ "$lastrc" -eq 124 ] && crash="timeout"
    site="-"
    if [ "$crash" = "crash" ]; then
      bt="$OUT/$tag.bt"
      ( cd "$SRCDIR" && PYTHON_GIL="$gil" ASAN_OPTIONS=detect_leaks=0:abort_on_error=0 timeout "$T" gdb -q -batch \
          -ex 'set pagination off' -ex 'set print frame-arguments none' -ex 'set debuginfod enabled off' \
          -ex run -ex 'bt 30' --args "$bin" -u "$SRC" ) 2>&1 \
        | grep -E 'Program received|Assertion .* failed|^#[0-9]' | sed -E 's/ \(.*\) at / at /' > "$bt"
      site=$(grep -oP '^#\d+\s+(?:0x[0-9a-fA-F]+ in )?\K[A-Za-z_]\w+ at (?:Objects|Python|Modules|Include|Parser)/\S+' "$bt" \
             | sed -E 's/ at /@/' \
             | grep -vE '^(fatal_error(_exit)?|_Py_FatalError\w*|_PyObject_AssertFailed|_Py_NegativeRefcount|_Py_DumpStack)@' \
             | head -1)
      [ -z "$site" ] && site="?"
    fi
    printf '%s\trc=%s\t%s\t%s/%s\t%s\n' "$tag" "$lastrc" "${crash:-no-repro}" "$hits" "$RUNS" "$site" >> "$SUM"
  done
done
[ -f "$SRCDIR/stdout" ] && cp "$SRCDIR/stdout" "$OUT/host_stdout.txt" 2>/dev/null
cat "$SUM"
