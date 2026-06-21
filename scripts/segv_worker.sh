#!/bin/bash
# Resolve ONE vehicle's deterministic local crash under the ft_debug_asan build and
# emit a single TSV line:  <vehicle>\t<signal>\t<site>\t<fingerprint>
# - signal:      SIGSEGV / SIGABRT / ... , or NOREPRO if it exited without crashing
# - site:        first CPython-source frame (func@file:line) = the crash site
# - fingerprint: first 3 CPython-source frames joined by ';' (for finer dedupe)
# Usage: segv_worker.sh <crash-dir>            (expects <dir>/source.py)
set -u
. "$(cd "$(dirname "$0")" && pwd)/env.sh"   # OOM_PY = workhorse interpreter (overridable)
DIR="${1:?usage: segv_worker.sh <crash-dir>}"
SRC="$DIR/source.py"
LABEL="$(basename "$(dirname "$DIR")")/$(basename "$DIR")"
PY="$OOM_PY"
BT="$(mktemp)"
ASAN_OPTIONS=detect_leaks=0:abort_on_error=0 timeout "${WORKER_TIMEOUT:-180}" gdb -q -batch \
  -ex 'set pagination off' -ex 'set print frame-arguments none' \
  -ex 'set debuginfod enabled off' -ex run -ex 'bt 30' \
  --args "$PY" "$SRC" 2>&1 | grep -E 'Program received signal|^#[0-9]' \
  | sed -E 's/ \(.*\) at / at /' > "$BT"
sig="$(grep -oE 'signal SIG[A-Z]+' "$BT" | head -1 | sed 's/signal //')"
[ -z "$sig" ] && sig="NOREPRO"
# True crash site = innermost CPython frame. gdb prints the innermost frame(s)
# WITHOUT a leading address, deeper ones as "0x.. in func"; match both, in order.
# Skip the fatal/assert-reporting plumbing so frames[0] is the real crash/assert site.
mapfile -t frames < <(grep -oP '^#\d+\s+(?:0x[0-9a-fA-F]+ in )?\K[A-Za-z_]\w+ at (?:Objects|Python|Modules|Include|Parser)/\S+' "$BT" \
                      | sed -E 's/ at /@/' \
                      | grep -vE '^(fatal_error(_exit)?|_Py_FatalError\w*|_PyObject_AssertFailed|_Py_NegativeRefcount|_Py_DumpStack|faulthandler\w*|_Py_DumpExtensionModules)@')
site="${frames[0]:-?}"
fp="$(printf '%s;' "${frames[@]:0:6}")"   # top frames for chain-aware dedupe in ingest.py
printf '%s\t%s\t%s\t%s\n' "$LABEL" "$sig" "$site" "$fp"
rm -f "$BT"
