# Abort: `assert((res != NULL) ^ (PyErr_Occurred() != NULL))` in `_Py_BuiltinCallFastWithKeywords_StackRef` (`Python/ceval.c`) when a builtin (`compile`) breaks the return/error contract under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

The specialized `CALL_BUILTIN_FAST_WITH_KEYWORDS` bytecode dispatches `METH_FASTCALL | METH_KEYWORDS` builtins through `_Py_BuiltinCallFastWithKeywords_StackRef()`, which after the call asserts the CPython API contract `(res != NULL) ^ (PyErr_Occurred() != NULL)` (exactly one of "result" / "error set" must hold). Under OOM, the builtin `compile()` (reached from `timeit.Timer.__init__` at `Lib/timeit.py:82`) violates that contract -- it returns `NULL` after an internal allocation failure without the error indicator surviving in the state the wrapper observes -- so the debug-only assert at `Python/ceval.c:843` fires and aborts the interpreter.

## Reproducer

```python
import _testcapi, faulthandler
faulthandler.enable()

def hot():
    # Specialize this call site to CALL_BUILTIN_FAST_WITH_KEYWORDS.
    return compile("pass", "<timeit-src>", "exec")

for _ in range(2000):        # warm up so the CALL specializes to the builtin-fast path
    hot()

_testcapi.set_nomemory(19, 0)   # fail every allocation from #19 onward
try:
    hot()                       # -> _Py_BuiltinCallFastWithKeywords_StackRef -> assert
finally:
    _testcapi.remove_mem_hooks()
```

Deterministic at `start=19` on the free-threaded debug+ASan build (and on the JIT debug build). The warm-up loop is load-bearing: the abort only lands on `ceval.c:843` once the `compile()` call site is specialized to `CALL_BUILTIN_FAST_WITH_KEYWORDS`. Without specialization the identical contract violation is caught one frame deeper in `_Py_CheckFunctionResult` (`Objects/call.c:43`, "a function returned NULL without setting an exception"). The fuzzer reaches the specialized state naturally via its repeated `oom_call` sweep over `timeit` (whose `Timer.__init__` calls `compile`).

## Backtrace

```
#8  _Py_BuiltinCallFastWithKeywords_StackRef  Python/ceval.c:843              <- assert (res != NULL) ^ (PyErr_Occurred() != NULL)
#9  _PyEval_EvalFrameDefault                  Python/generated_cases.c.h:2603 <- _CALL_BUILTIN_FAST_WITH_KEYWORDS
#11 _PyEval_Vector                            Python/ceval.c:2141
#12 PyEval_EvalCode                           Python/ceval.c:679
```

faulthandler Python stack (timeit vehicle): `File ".../Lib/timeit.py", line 82 in __init__` -> `compile(setup, dummy_src_name, "exec")`.

## Root cause

`Python/ceval.c`, `_Py_BuiltinCallFastWithKeywords_StackRef()` (L827):

```c
    res = cfunc(PyCFunction_GET_SELF(callable_o), args_o, total_args, NULL);
    STACKREFS_TO_PYOBJECTS_CLEANUP(args_o);
    assert((res != NULL) ^ (PyErr_Occurred() != NULL));   /* L843 */
    return res;
```

The assert encodes the standard rule that a C callable must return non-NULL **xor** leave an exception set. The defect is not in `ceval.c` itself -- it is the called builtin. For the `compile` vehicle, `builtin_compile_impl` (`Python/bltinmodule.c:844`) runs the parser/compiler (`_Py_CompileStringObjectWithModule`, L963) which, on an allocation failure deep inside, returns `NULL` while the `MemoryError` it set does not survive in the indicator the wrapper checks (an inner cleanup/`PyErr_Clear`-style path swallows it, or normalization of the pending `MemoryError` itself fails). The result is `res == NULL` **and** `PyErr_Occurred() == NULL`, breaking the xor and aborting. This is an OOM-robustness bug in the builtin's error handling, surfaced (not caused) by the debug assert; the same family is hit by the `dis` and `zipfile._path` vehicles through other builtins on the same specialized dispatch path.

## Suggested fix

The contract must be restored by the builtin, not by relaxing the assert. In `builtin_compile_impl` ensure every `NULL`-returning error path leaves an exception set (and every success path leaves none): on the `error:`/`finally:` exits, if the compiler returned `NULL` with no exception, set `MemoryError` (mirroring `_PyErr_NoMemory`), e.g.

```c
finally:
    if (result == NULL && !PyErr_Occurred()) {
        PyErr_NoMemory();   /* defensive: never return NULL without an exception */
    }
    return result;
```

A broader fix is to audit `_Py_CompileStringObjectWithModule` / the AST-compile path so an OOM there always propagates a live exception. (The `ceval.c:843` assert is correct and should stay.)

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). The crash is an **abort only on builds with assertions compiled in**: the free-threaded debug+ASan build and the JIT debug build both abort at the identical `Python/ceval.c:843` assertion. The free-threaded release and upstream (GIL) builds define `-DNDEBUG`, so the assert is a no-op; there the same OOM path raises a clean `MemoryError` and exits normally (rc 1). Per the OOM-catalog convention for assert-based aborts, the non-debug builds are recorded as `n/a`.

Six fuzzer vehicles abort at the identical `ceval.c:843` assertion (`timeit` x2, `dis` x2, `zipfile._path` x2); each merely calls a `METH_FASTCALL | METH_KEYWORDS` builtin (`compile`, etc.) on an already-specialized call site under OOM. Specialization is what routes the failure to `ceval.c:843`; the unspecialized variant of the same defect aborts one frame deeper in `_Py_CheckFunctionResult` (`Objects/call.c:43`) and is tracked as the related "function returned NULL without setting an exception" signature.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build and the JIT debug build. Free-threaded release and upstream builds: assertion compiled out, clean `MemoryError` (`n/a`).
