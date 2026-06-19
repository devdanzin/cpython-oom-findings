# Abort: stale exception in `cfunction_check_kwargs` (`methodobject.c:409`)

*Under OOM, `sys._baserepl()` ignores `PyRun_AnyFileExFlags`'s failure and returns `None` with a `MemoryError` still pending; the next NOARGS `sys` C-call trips `assert(!_PyErr_Occurred(tstate))` at its entry.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`sys._baserepl()` (`sys__baserepl_impl`, `Python/sysmodule.c:2620`) calls `PyRun_AnyFileExFlags(stdin, ...)`, **ignores its return value**, and unconditionally does `Py_RETURN_NONE`. Under OOM, an allocation deep inside the interactive REPL/parse machinery fails and raises `MemoryError`, but the interactive loop's error handling does not guarantee a clean thread state on every OOM path. `_baserepl` then returns a valid `None` object while a `MemoryError` is still live on the thread state. The very next C-call boundary trips a debug-only "exception pending" assertion: in the fuzzer vehicles, `assert(!_PyErr_Occurred(tstate))` in `cfunction_check_kwargs` (`Objects/methodobject.c:409`) at the entry of the following NOARGS `sys` builtin.

## Reproducer

```python
import sys
import _testcapi

_testcapi.set_nomemory(1, 0)   # fail every allocation from #1 onward
try:
    sys._baserepl()            # returns None with MemoryError still pending
    sys._clear_type_cache()    # next C call observes the leaked exception
finally:
    _testcapi.remove_mem_hooks()
```

Run with stdin at EOF: `python repro.py < /dev/null`. Deterministic at `start=1` on the free-threaded debug+ASan build (and on the JIT build, which also has assertions enabled). The minimal repro aborts one frame earlier than the vehicles — the bad result is caught on `_baserepl`'s own return by `_Py_CheckFunctionResult` (`Fatal Python error: ... a function returned a result with an exception set`, `object type name: MemoryError`). It is the identical defect; in the dense fuzzer sweep the leaked exception instead surfaces at the entry of the *next* NOARGS `sys` call and hits `methodobject.c:409`.

## Backtrace

```
#8  cfunction_check_kwargs        Objects/methodobject.c:409   <- assert(!_PyErr_Occurred(tstate))
#9  cfunction_vectorcall_NOARGS   Objects/methodobject.c:491
#10 _PyObject_VectorcallTstate    Include/internal/pycore_call.h:144
#11 _Py_VectorCall_StackRefSteal  Python/ceval.c:726
#12 _PyEval_EvalFrameDefault      Python/generated_cases.c.h:4559   (CALL_NON_PY_GENERAL)
```

`object type name: MemoryError` in the stdout dump confirms a live `MemoryError` is pending when the NOARGS call enters. The faulting condition is a leaked exception, not a NULL/freed pointer.

## Root cause

`Python/sysmodule.c`, `sys__baserepl_impl()` (L2620):

```c
static PyObject *
sys__baserepl_impl(PyObject *module)
{
    PyCompilerFlags cf = _PyCompilerFlags_INIT;
    PyRun_AnyFileExFlags(stdin, "<stdin>", 0, &cf);   /* L2624: return value IGNORED */
    Py_RETURN_NONE;                                   /* L2625: always returns None */
}
```

`PyRun_AnyFileExFlags` -> `_PyRun_AnyFileObject` -> `_PyRun_InteractiveLoopObject` -> `PyRun_InteractiveOneObjectEx` -> `pyrun_one_parse_ast` / `run_mod` (`Python/pythonrun.c`) all allocate. Under OOM one of those allocations fails and sets `MemoryError`. The interactive loop (`pythonrun.c:152-178`) only sometimes clears the error (`PyErr_Print()` / `PyErr_Clear()`), and on EOF/OOM interleavings can return with the exception still set. Because `_baserepl` discards both the `int` return code *and* the pending exception and returns `None`, the interpreter is left in the illegal state "non-NULL result + exception set". The next C call asserts `!_PyErr_Occurred(tstate)` and aborts.

## Suggested fix

Propagate the failure in `sys__baserepl_impl` instead of swallowing it:

```c
    PyCompilerFlags cf = _PyCompilerFlags_INIT;
    if (PyRun_AnyFileExFlags(stdin, "<stdin>", 0, &cf) != 0) {
        /* An exception is (or should be) set; surface it to the caller. */
        if (!PyErr_Occurred()) {
            PyErr_SetNone(PyExc_RuntimeError);   /* defensive */
        }
        return NULL;
    }
    Py_RETURN_NONE;
```

Additionally harden `_PyRun_InteractiveLoopObject` (`Python/pythonrun.c`) so it never returns with a stale exception on the thread state (clear or print on every exit path, including the EOF/OOM paths). Either change alone closes the assertion; doing both is safest.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). **Not** free-threading-specific: this is a generic exception-discard bug in `sys._baserepl`. It aborts on every assertions-enabled build — both the free-threaded debug+ASan build *and* the JIT build abort; the FT-release and upstream builds compile the assert out (`-DNDEBUG`) and instead let a normal `MemoryError` propagate cleanly (exit 1). Per the OOM-catalog convention for assert-based aborts, the non-assert builds are recorded as `n/a`.

Four fuzzer vehicles abort at the identical `Objects/methodobject.c:409` assertion; the two `python-7/sys-*` vehicles pin the leak to `sys._baserepl`, and the `asyncio_format_helpers` vehicle shows the same leaked-exception state surfacing during a later `traceback.walk_stack`. The minimal stdlib repro hits the same defect one frame earlier (`_Py_CheckFunctionResult` on `_baserepl`'s own return), which more directly identifies the culprit function. Minimization is therefore **partial**: the minimal repro is deterministic and stdlib-only but lands on the sibling assertion; the exact `methodobject.c:409` frame is reproduced by the vehicle.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build and the JIT build. FT-release / upstream builds: assert compiled out, clean `MemoryError` (`n/a`).
