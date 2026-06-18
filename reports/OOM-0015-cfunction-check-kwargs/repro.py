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

Run:
    python repro.py < /dev/null
    # aborts (rc 134) on the FT debug+ASan and JIT builds.
    # On ft_release / upstream the assert is compiled out: a normal
    # MemoryError propagates and the process exits cleanly (rc 1).

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
"""
import sys
import _testcapi

_testcapi.set_nomemory(1, 0)   # fail every allocation from #1 onward
try:
    sys._baserepl()            # returns None with MemoryError still pending
    sys._clear_type_cache()    # next C call observes the leaked exception
finally:
    _testcapi.remove_mem_hooks()
