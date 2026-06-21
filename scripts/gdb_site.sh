#!/bin/bash
# Resolve the real (symbolized) crash site of a fusil OOM repro by running it under
# the local free-threaded debug+ASan build in gdb. Prints the trimmed backtrace and,
# on the last line, SITE= the first frame in a CPython source file (the crash site).
#
# Usage: gdb_site.sh <source.py> [frames]
set -u
. "$(cd "$(dirname "$0")" && pwd)/env.sh"   # OOM_PY = workhorse interpreter (overridable)
SRC="${1:?usage: gdb_site.sh <source.py> [frames]}"
N="${2:-20}"
PY="$OOM_PY"
ASAN_OPTIONS=detect_leaks=0:abort_on_error=0 timeout 180 gdb -q -batch \
  -ex 'set pagination off' -ex 'set print frame-arguments none' \
  -ex 'set debuginfod enabled off' -ex run -ex "bt $N" \
  --args "$PY" "$SRC" 2>&1 | grep -E 'Program received|signal SIG|^#[0-9]' \
  | sed -E 's/ \(.*\) at / at /' | tee /tmp/gdb_site_bt.txt
# crash site = first frame located in Objects/ Python/ Modules/ Include/ (skip libc/asan/dump)
awk '/ at (Objects|Python|Modules|Include|Parser)\// {sub(/^#[0-9]+ +/,""); print "SITE= " $0; exit}' /tmp/gdb_site_bt.txt
