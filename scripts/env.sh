#!/bin/bash
# env.sh — single source of truth for the machine-specific paths the triage /
# minimization scripts need. Source it from a script:
#
#     . "$(dirname "$0")/env.sh"
#
# Every value is overridable from the environment, so nothing here is a hard
# dependency: export OOM_PY / MATRIX_ROOT / MATRIX_BUILDS / SHRINKRAY to point at
# a different layout without touching the scripts.

# Root of the CPython build matrix. The expected layout is one dir per build,
# each containing a ./python:
#   {debug,release}-{ft,gil}-{nojit,jit}[-asan]
: "${MATRIX_ROOT:=$HOME/projects/python_build_matrix/builds}"

# Workhorse interpreter: free-threaded debug + ASan (the fleet / triage build,
# the analog of the old "ft_debug_asan"). Used by the oracle and the gdb helpers.
: "${OOM_PY:=$MATRIX_ROOT/debug-ft-nojit-asan/python}"
export OOM_PY MATRIX_ROOT

# Default cross-build triage set as "logical_name=path" pairs (override via
# $MATRIX_BUILDS). Logical names are stable labels for output; map them to
# whatever matrix dirs you like. Workhorse first; gil_debug_asan included because
# FT-vs-GIL is a recurring discriminator (e.g. per-thread-freelist bugs).
: "${MATRIX_BUILDS:=ft_debug_asan=$MATRIX_ROOT/debug-ft-nojit-asan/python gil_debug_asan=$MATRIX_ROOT/debug-gil-nojit-asan/python ft_release=$MATRIX_ROOT/release-ft-nojit/python jit=$MATRIX_ROOT/debug-gil-jit-asan/python upstream=$MATRIX_ROOT/release-gil-nojit/python}"
export MATRIX_BUILDS

# Locate shrinkray without hardcoding a venv name: prefer $SHRINKRAY, then PATH,
# then any ~/venvs/*/bin/shrinkray. Echoes the path; returns 1 if not found.
find_shrinkray() {
  if [ -n "${SHRINKRAY:-}" ]; then printf '%s\n' "$SHRINKRAY"; return 0; fi
  if command -v shrinkray >/dev/null 2>&1; then command -v shrinkray; return 0; fi
  local v
  for v in "$HOME"/venvs/*/bin/shrinkray; do
    [ -x "$v" ] && { printf '%s\n' "$v"; return 0; }
  done
  return 1
}
