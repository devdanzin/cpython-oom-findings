"""
Minimal reproducer: Fatal Python error `_PyMem_DebugRawFree: bad ID` in
free_threadstate() when free-threaded sub-interpreter thread-state setup
fails under OOM.

Affected:   CPython 3.16.0a0 (main), free-threaded (Py_GIL_DISABLED) builds only.
            On the FT DEBUG build the debug allocator detects the bad free and
            aborts ("bad ID"); on the FT release build the same bad free
            corrupts the heap and segfaults (see Notes). GIL-enabled builds
            (jit, upstream) lack the affected path entirely.
Crash:      Fatal Python error / SIGABRT, Python/pystate.c:1527
            _PyMem_DebugRawFree: bad ID: Allocated using API ' ',
            verified using API 'r'
Requires:   a free-threaded debug build exposing _testcapi.set_nomemory.

Backtrace (gdb):
    #8  _PyMem_DebugCheckAddress  Objects/obmalloc.c:3347  ("bad ID")
    #9  _PyMem_DebugRawFree       Objects/obmalloc.c:3166
    #10 free_threadstate         Python/pystate.c:1527     (PyMem_RawFree(tstate))
    #11 new_threadstate          Python/pystate.c:1668     (qsbr/tlbc reserve failed)
    #12 new_interpreter          Python/pylifecycle.c:2728
    #13 _PyXI_NewInterpreter     Python/crossinterp.c:3269
    #14 _interpreters_create_impl Modules/_interpretersmodule.c:878

Root cause (Python/pystate.c):

    init_interpreter() (L568) publishes the interpreter-embedded thread state
    as the preallocated one:

        interp->threads.preallocated = &interp->_initial_thread;

    but never sets interp->_initial_thread.base.interp = interp.

    A new sub-interpreter calls new_threadstate(); alloc_threadstate() (L1498)
    hands out that preallocated &interp->_initial_thread. On free-threaded
    builds new_threadstate() then reserves a QSBR slot and a TLBC index:

        Py_ssize_t qsbr_idx = _Py_qsbr_reserve(interp);          // L1666
        if (qsbr_idx < 0) { free_threadstate(tstate); ... }      // L1668
        int32_t tlbc_idx = _Py_ReserveTLBCIndex(interp);         // L1671
        if (tlbc_idx < 0) { free_threadstate(tstate); ... }      // L1673

    Under OOM one of these fails and free_threadstate(tstate) runs. It reads
    the interpreter back-pointer from the thread state itself:

        PyInterpreterState *interp = tstate->base.interp;        // L1514: NULL
        if (tstate == &interp->_initial_thread) {                // L1520: FALSE
            reset_threadstate(tstate);
        } else {
            PyMem_RawFree(tstate);                               // L1527: BAD FREE
        }

    But tstate->base.interp is still NULL here -- it is only set later, in
    init_threadstate() (L1558), which runs *after* the reservations. So
    &interp->_initial_thread degenerates to the field offset of a NULL
    pointer (~0x387a0), the identity check is false, and PyMem_RawFree() is
    handed the interpreter-embedded _initial_thread, which was never returned
    by the raw allocator. The debug allocator flags the untagged block and
    Py_FatalError()s.

The OOM sweep is needed so the interpreter/obmalloc state is built and the
preallocated _initial_thread is taken, while a later free-threaded-only
reservation allocation fails.

Likely fix: set interp->_initial_thread.base.interp = interp before publishing
it as preallocated (init_interpreter), or make free_threadstate() identify the
embedded thread state without trusting tstate->base.interp.

Self-sweeping: `python repro.py` runs the trigger under set_nomemory(N, 0) for N in a
sweep, each in a FRESH subprocess (a fresh process avoids cache warm-up shifting the OOM
window), and stops at the first N that crashes. Needs a free-threaded debug build (the
check is compiled out under NDEBUG) and the free-threaded interpreter (PYTHON_GIL=0; this
bug lives on a Py_GIL_DISABLED-only path). Bare trigger (fixed N=31):
    import _interpreters, _testcapi
    _testcapi.set_nomemory(31, 0)
    _interpreters.create(reqrefs=True)
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
    try:
        _testcapi.remove_mem_hooks()
    except Exception:
        pass
"""

SIGNATURE = "_PyMem_DebugRawFree: bad ID"

def main():
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=0"}
    env["PYTHON_GIL"] = "0"   # free-threading-only bug: force the GIL off
    for n in range(100):
        out = subprocess.run([sys.executable, "-c", TRIGGER.format(n=n)],
                             capture_output=True, text=True, env=env)
        if SIGNATURE in out.stdout + out.stderr:
            print("reproduced at set_nomemory(%d, 0):" % n)
            sys.stdout.write(out.stderr or out.stdout)
            return 1
    print("no crash in range(100); widen it for your build")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
