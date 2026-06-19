# Fatal: NULL returned without an exception set in `_Py_CheckFunctionResult` (`call.c:43`)

*The pegen parser's error-recovery pass (`_PyPegen_run_parser`, `pegen.c:966`) `PyErr_Clear()`s a `MemoryError` while upgrading a `SyntaxError`, then returns NULL with no exception; `symtable.symtable()`'s C call propagates it out and trips `_Py_CheckFunctionResult`, aborting debug builds.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Calling `symtable.symtable(code, filename, "exec")` under OOM drives `_symtable.symtable()` -> `_Py_SymtableStringObjectFlags` -> `_PyParser_ASTFromString` -> `_PyPegen_run_parser`. When the first parse fails, pegen runs a *second*, heavier "error-recovery" pass to build a nicer `SyntaxError`. Under continued allocation failure that recovery path calls `PyErr_Clear()` and then itself fails to allocate, so the C call returns `NULL` with **no exception set**. The eval loop's `_Py_CheckFunctionResult` detects the broken invariant and, on debug builds, calls `Py_FatalError`, aborting the interpreter (SIGABRT).

## Reproducer

```python
import symtable, _testcapi, faulthandler
faulthandler.enable()
_testcapi.set_nomemory(4, 0)        # fail every allocation from #4 onward
try:
    symtable.symtable("def f(x):\n    return x + 1\n", "<min>", "exec")
finally:
    _testcapi.remove_mem_hooks()
```

Deterministic at `start=4` on both the free-threaded debug+ASan build and the JIT (GIL) debug build. A single `set_nomemory(4, 0)` is enough: the code-object/parse machinery makes a few allocations succeed, then the failing allocation lands inside the parser's error-recovery pass.

## Backtrace

```
#8  _Py_CheckFunctionResult        Objects/call.c:43           <- Py_FatalError("a function returned NULL without setting an exception")
#9  _Py_VectorCall_StackRefSteal   Python/ceval.c:726
#10 _PyEval_EvalFrameDefault       Python/generated_cases.c.h:3686   (calls _symtable.symtable, result == NULL, no exc)
#11 _PyEval_EvalFrame              Include/internal/pycore_ceval.h:122
#12 _PyEval_Vector                 Python/ceval.c:2141
#13 PyEval_EvalCode                Python/ceval.c:679
```

faulthandler Python stack (the actual culprit C call):

```
File ".../Lib/symtable.py", line 26 in symtable   ->  _symtable.symtable(code, filename, compile_type, module=module)
File ".../Lib/symtable.py", line 412 in main
```

The object dumped by faulthandler is a `MemoryError` instance, `refcount 1`, with an **empty repr** -- a `MemoryError` whose normalization/repr could not allocate. That is the exception the parser's recovery pass cleared: the C call returns NULL but the live error state was wiped, so `_Py_CheckFunctionResult` sees `result == NULL && !PyErr_Occurred()`.

## Root cause

`_symtable_symtable_impl` (`Modules/symtablemodule.c:66`) calls `_Py_SymtableStringObjectFlags`, which parses the source via `_PyParser_ASTFromString` -> `_PyPegen_run_parser` (`Parser/pegen.c:939`). When the first `_PyPegen_parse` returns NULL, pegen runs a second diagnostic pass:

```c
    Token *last_token = p->tokens[p->fill - 1];
    reset_parser_state_for_error_pass(p);
    _PyPegen_parse(p);                       /* second pass, allocates heavily */
    _Pypegen_set_syntax_error(p, last_token);
    if (PyErr_ExceptionMatches(PyExc_SyntaxError)) {
        _PyPegen_set_syntax_error_metadata(p);
    }
    return NULL;                              /* Parser/pegen.c:966 */
```

The recovery helpers swallow errors unconditionally. In `_PyPegen_set_syntax_error_metadata` (`Parser/pegen.c:895`):

```c
    if (!the_source) {
        PyErr_Clear();                       /* L917: wipes a MemoryError from PyUnicode_Decode */
        the_source = Py_None; Py_INCREF(the_source);
    }
    PyObject* metadata = Py_BuildValue("(iiN)", ...);
    if (!metadata) {
        PyErr_Clear();                       /* L928: wipes the error and returns with NO exception set */
        return;
    }
```

Under OOM each of these allocations (`PyUnicode_Decode`, `Py_BuildValue`, and the second `_PyPegen_parse` itself) can fail and raise `MemoryError`; the surrounding recovery code then `PyErr_Clear()`s it while trying to upgrade the diagnostic, and if its own follow-up allocation also fails it returns without re-raising anything. `_PyPegen_run_parser` then returns NULL with a clear error state, which propagates all the way out of `_symtable.symtable()`. The defect is an unconditional error-clear in a path that cannot guarantee it will set a replacement exception -- not a use-after-free.

## Suggested fix

The parser's error-recovery pass must preserve a pending non-`SyntaxError` exception (notably `MemoryError`) instead of clearing it and returning NULL with no error. Concretely:

* In `_PyPegen_run_parser`, after the second pass, if no exception is set, re-raise the original error captured before the recovery pass (save it with `PyErr_GetRaisedException()` before `reset_parser_state_for_error_pass`, restore if recovery produced nothing).
* In `_PyPegen_set_syntax_error_metadata`, on the `!metadata` branch, restore the saved `exc` (`PyErr_SetRaisedException(exc)`) rather than `PyErr_Clear(); return;`, so the original exception is not lost.

As a belt-and-suspenders backstop, `_Py_SymtableStringObjectFlags`/`_symtable_symtable_impl` could set `PyErr_NoMemory()` when a build helper returns NULL without an exception, converting the fatal into a normal `MemoryError`.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). The crash is the generic "returned NULL without setting an exception" interpreter invariant, fired here specifically through the symtable/pegen path; the same recovery-pass error-loss could in principle surface via `compile()` / `ast.parse()` too.

Build matrix: this is a `Py_FatalError`, which is gated on `#ifdef Py_DEBUG` inside `_Py_CheckFunctionResult` (`Objects/call.c:40-43`). It therefore **aborts on both debug builds** (`ft_debug_asan` and `jit`, both `Py_DEBUG=1`) at `start=4`, and is **compiled out on the release builds** (`ft_release`, `upstream`, both `Py_DEBUG=0`), where the same NULL-without-exception is instead converted into a silent `SystemError` return -- a latent correctness bug, not a clean `MemoryError`. Per the OOM-catalog convention for debug-gated fatals, the non-debug builds are recorded as `n/a`. (Sweeping `start` 1..200 on the release builds raised only clean `MemoryError`s and never aborted.)

Four fuzzer vehicles (`python-5` once, `python-7` three times) all fatal at the identical `_Py_CheckFunctionResult@Objects/call.c:43` site via `symtable.symtable()` (`Lib/symtable.py:26`) called from `symtable.main()` (`Lib/symtable.py:412`) under the fuzzer's `oom_call` sweep.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build and the JIT debug build at `start=4`. Release/upstream builds: `Py_FatalError` compiled out (`n/a`; survive the sweep with `MemoryError`/latent `SystemError`).
