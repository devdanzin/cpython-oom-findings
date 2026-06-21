"""
OOM-0038 — free-threaded sub-interpreter creation crashes under OOM when the per-interpreter
TLBC index reservation fails: _PyIndexPool_AllocIndex() calls PyErr_NoMemory() with no active
thread state.

A sub-interpreter is created under allocation failure. new_interpreter() (Python/pylifecycle.c)
DETACHES the calling thread's thread state before building the new interpreter's first thread
state, so there is no active thread state in that window. new_threadstate() (pystate.c:1671)
then reserves a TLBC index via _Py_ReserveTLBCIndex() -> _PyIndexPool_AllocIndex(); for a fresh
interpreter the pool is empty, so it grows with PyMem_RawCalloc(), which fails under OOM and
calls PyErr_NoMemory() (index_pool.c:167). PyErr_NoMemory() -> get_memory_error() ->
get_exc_state() -> _PyInterpreterState_GET(), which REQUIRES an active thread state:

  - free-threaded DEBUG build:  Fatal Python error: _PyInterpreterState_GET: ... without an
                                active thread state   (SIGABRT)
  - free-threaded RELEASE build: SIGSEGV (NULL interp -> &((PyInterpreterState*)0)->
                                exc_state.memerrors_lock inside MEMERRORS_LOCK).
  - GIL-enabled builds:         not affected (the TLBC index pool is Py_GIL_DISABLED-only).

Requires a free-threaded build exposing _testcapi.set_nomemory; run free-threaded
(PYTHON_GIL=0).

DISTINCT from OOM-0020 (same function new_threadstate, ADJACENT allocation index): OOM-0020 is
the _Py_qsbr_reserve cleanup path where free_threadstate() bad-frees the embedded
_initial_thread (_PyMem_DebugRawFree "bad ID" / heap-corruption segv). This bug is the
_Py_ReserveTLBCIndex path raising PyErr_NoMemory() with no thread state. OOM-0020 fires ONE
allocation index earlier and masks this under a naive "stop at first crash" sweep -- so this
self-sweep explicitly SKIPS the OOM-0020 "bad ID" signature and stops only on THIS bug.

Bare trigger (start index is allocation-preamble sensitive, ~30-31 here; no windowing needed):
    import _interpreters, _testcapi
    _testcapi.set_nomemory(30, 0)
    _interpreters.create(reqrefs=True)

Run:
    ./python repro.py        # debug: SIGABRT (_PyInterpreterState_GET) ; release: SIGSEGV
"""
import os
import sys
import subprocess

TRIGGER = r"""
import _interpreters
import _testcapi
_testcapi.set_nomemory({n}, 0)
try:
    _interpreters.create(reqrefs=True)
finally:
    try: _testcapi.remove_mem_hooks()
    except Exception: pass
"""

CANDIDATE_TEXT = "_PyInterpreterState_GET"          # this bug (debug fatal text)
OOM0020_TEXT = "_PyMem_DebugRawFree: bad ID"        # adjacent, different bug -- do NOT stop on it


def main():
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=0"}
    env["PYTHON_GIL"] = "0"   # free-threading-only bug: force the GIL off
    for n in range(100):
        out = subprocess.run([sys.executable, "-c", TRIGGER.format(n=n)],
                             capture_output=True, text=True, env=env)
        text = out.stdout + out.stderr
        if OOM0020_TEXT in text:
            continue   # adjacent OOM-0020; keep sweeping for THIS bug
        hit_debug = CANDIDATE_TEXT in text
        hit_release_segv = (out.returncode == -11) or ("SEGV" in text and "get_memory_error" in text)
        if hit_debug or hit_release_segv:
            kind = "Fatal (_PyInterpreterState_GET)" if hit_debug else "SIGSEGV (release NULL interp)"
            print("reproduced at set_nomemory(%d, 0): %s" % (n, kind))
            sys.stdout.write(text or "")
            return 1
    print("no crash in range(100); widen it for your build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
