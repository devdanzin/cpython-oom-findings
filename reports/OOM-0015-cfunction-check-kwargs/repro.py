"""
Minimal reproducer: abort under OOM because sys._baserepl() returns None
while leaving a MemoryError pending on the thread state.

Affected:   CPython 3.16.0a0 (main), commit 15d7406.
Crash:      SIGABRT on assertions-enabled builds.
              - ft_debug_asan / jit: Fatal Python error: _Py_CheckFunctionResult
                ("a function returned a result with an exception set"),
                object type name: MemoryError.
              - fuzzer vehicles reach the equivalent assertion one frame later:
                Objects/methodobject.c:409
                  Assertion `!_PyErr_Occurred(tstate)' failed.
                in cfunction_check_kwargs(), on the *next* NOARGS sys call.
Requires:   a debug / assertions build exposing _testcapi.set_nomemory.

Root cause (Python/sysmodule.c):

    sys._baserepl  ->  sys__baserepl_impl()  (sysmodule.c:2620):

        PyCompilerFlags cf = _PyCompilerFlags_INIT;
        PyRun_AnyFileExFlags(stdin, "<stdin>", 0, &cf);   // L2624: result IGNORED
        Py_RETURN_NONE;                                   // L2625: always None

    PyRun_AnyFileExFlags -> _PyRun_InteractiveLoopObject -> ... ->
    pyrun_one_parse_ast / run_mod allocate freely.  Under OOM one of those
    allocations fails and a MemoryError is raised.  The interactive loop's
    error handling (PyErr_Print / PyErr_Clear, pythonrun.c:152-178) does not
    guarantee a clean thread-state on every OOM path, and _baserepl discards
    both the int return code AND the pending exception, returning None.

    On a debug build the bad result is caught the moment _baserepl returns
    (_Py_CheckFunctionResult, pycore_call.h:145).  In the dense fuzzer sweep
    the leak instead surfaces at the entry of the following NOARGS builtin,
    tripping assert(!_PyErr_Occurred(tstate)) in cfunction_check_kwargs
    (Objects/methodobject.c:409).  Same defect, two adjacent assertions.

Likely fix: in sys__baserepl_impl, propagate failure:

        if (PyRun_AnyFileExFlags(stdin, "<stdin>", 0, &cf) != 0) {
            return NULL;   // an exception is (or should be) set
        }
        Py_RETURN_NONE;

    and/or ensure _PyRun_InteractiveLoopObject never returns with a stale
    exception still set on the thread state.

The OOM sweep is needed so initialization succeeds (start small) while an
allocation deep inside the REPL/parse machinery fails.  Deterministic at
start=1 on the FT debug+ASan build with stdin at EOF.

Self-sweeping: `python repro.py` runs the trigger under set_nomemory(N, 0) for N in a
sweep, each in a FRESH subprocess (a fresh process avoids cache warm-up shifting the OOM
window), and stops at the first N that crashes. Needs a debug build (the check is compiled
out under NDEBUG). The trigger needs stdin at EOF, so each child is fed /dev/null. Bare
trigger (fixed N=1):
    import sys, _testcapi
    _testcapi.set_nomemory(1, 0)
    try:
        sys._baserepl()         # returns None with MemoryError still pending
        sys._clear_type_cache() # next C call observes the leaked exception
    finally:
        _testcapi.remove_mem_hooks()
    # run with stdin at EOF: python repro.py < /dev/null
"""
import os
import sys
import subprocess

TRIGGER = r"""
import sys
import _testcapi

_testcapi.set_nomemory({n}, 0)   # fail every allocation from #{n} onward
try:
    sys._baserepl()              # returns None with MemoryError still pending
    sys._clear_type_cache()      # next C call observes the leaked exception
finally:
    _testcapi.remove_mem_hooks()
"""

SIGNATURE = "a function returned a result with an exception set"

def main():
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=0"}
    # This bug is NOT free-threading-only; it aborts on every assertions build.
    for n in range(80):
        out = subprocess.run([sys.executable, "-c", TRIGGER.format(n=n)],
                             capture_output=True, text=True, env=env,
                             stdin=subprocess.DEVNULL)
        if SIGNATURE in out.stdout + out.stderr:
            print("reproduced at set_nomemory(%d, 0):" % n)
            sys.stdout.write(out.stderr or out.stdout)
            return 1
    print("no crash in range(80); widen it for your build")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
