"""
Minimal reproducer: abort on
    assert((res != NULL) ^ (PyErr_Occurred() != NULL))
in _Py_BuiltinCallFastWithKeywords_StackRef() when a builtin (compile)
breaks the return/error contract under OOM.

Affected:   CPython 3.16.0a0 (main). Aborts on builds with assertions
            compiled in: free-threaded debug+ASan and JIT debug.
            Release builds (-DNDEBUG) raise a clean MemoryError (see Notes).
Crash:      SIGABRT, Python/ceval.c:843
            Assertion `(res != NULL) ^ (PyErr_Occurred() != NULL)' failed.
Requires:   a debug build exposing _testcapi.set_nomemory.

Run:
    python repro_ceval_843_builtin_call_contract_oom.py
    # aborts (rc 134) on the FT debug+ASan build and the JIT debug build.

Backtrace (gdb):
    #8  _Py_BuiltinCallFastWithKeywords_StackRef  Python/ceval.c:843
            (assert (res != NULL) ^ (PyErr_Occurred() != NULL))
    #9  _PyEval_EvalFrameDefault   Python/generated_cases.c.h:2603
            (_CALL_BUILTIN_FAST_WITH_KEYWORDS)
    #11 _PyEval_Vector            Python/ceval.c:2141
    #12 PyEval_EvalCode           Python/ceval.c:679

Root cause (Python/ceval.c + Python/bltinmodule.c):

    The specialized CALL_BUILTIN_FAST_WITH_KEYWORDS opcode dispatches
    METH_FASTCALL|METH_KEYWORDS builtins through
    _Py_BuiltinCallFastWithKeywords_StackRef() (ceval.c:827), which asserts
    the CPython contract after the call (ceval.c:843):

        res = cfunc(self, args_o, total_args, NULL);
        assert((res != NULL) ^ (PyErr_Occurred() != NULL));

    A C callable must return non-NULL XOR set an exception. Under OOM the
    builtin compile() (builtin_compile_impl, bltinmodule.c:844, via
    _Py_CompileStringObjectWithModule) fails an internal allocation, returns
    NULL, but the MemoryError does not survive in the indicator the wrapper
    observes -> res == NULL AND PyErr_Occurred() == NULL -> assert fails.

    The defect is in the builtin's OOM error handling, not in ceval.c; the
    assert is correct and merely surfaces it.

Why the warm-up loop:

    The abort lands on ceval.c:843 only once the compile() call site is
    specialized to CALL_BUILTIN_FAST_WITH_KEYWORDS. The for-loop warms it up.
    Without specialization the identical contract violation is caught one
    frame deeper, in _Py_CheckFunctionResult (Objects/call.c:43,
    "a function returned NULL without setting an exception").

    The original fuzzer vehicles (timeit, dis, zipfile._path) reach the
    specialized state naturally: the fuzzer calls each target repeatedly in
    an OOM sweep, and timeit.Timer.__init__ (Lib/timeit.py:82) calls
    compile(setup, dummy_src_name, "exec").

Observed crash at start=19 on this build (with the 2000-iteration warm-up).

Likely fix: make builtin_compile_impl / the AST-compile path never return
NULL without a live exception under OOM (defensively PyErr_NoMemory() on the
finally path). Keep the ceval.c:843 assert.
"""
import _testcapi
import faulthandler

faulthandler.enable()


def hot():
    # Specialize this call site to CALL_BUILTIN_FAST_WITH_KEYWORDS.
    return compile("pass", "<timeit-src>", "exec")


# Warm up so the bytecode CALL specializes to the builtin-fast-with-keywords path.
for _ in range(2000):
    hot()

_testcapi.set_nomemory(19, 0)   # fail every allocation from #19 onward
try:
    hot()                       # specialized call -> _Py_BuiltinCallFastWithKeywords_StackRef
                                # -> compile() fails under OOM -> assert -> SIGABRT
finally:
    _testcapi.remove_mem_hooks()
