"""
Minimal reproducer: Fatal Python error
    _Py_CheckFunctionResult: a function returned NULL without setting an exception
for _symtable.symtable() when the pegen parser's error-recovery pass loses a
MemoryError under OOM.

Affected:   CPython 3.16.0a0 (main).
Crash:      SIGABRT via Py_FatalError, Objects/call.c:43
            (gated on #ifdef Py_DEBUG inside _Py_CheckFunctionResult).
            Aborts on the Py_DEBUG builds (ft_debug_asan, jit). On release
            builds the fatal is compiled out and the same bug surfaces as a
            silent SystemError instead of a clean MemoryError (see Notes).
Requires:   a debug build exposing _testcapi.set_nomemory.

Run:
    python repro.py
    # aborts (rc 134) on the FT debug+ASan build and the JIT debug build.

Backtrace (gdb, debug build):
    #8  _Py_CheckFunctionResult      Objects/call.c:43   (Py_FatalError: NULL w/o exception)
    #9  _Py_VectorCall_StackRefSteal Python/ceval.c:726
    #10 _PyEval_EvalFrameDefault     Python/generated_cases.c.h:3686  (calls _symtable.symtable)

faulthandler Python stack (the real culprit C call):
    File ".../Lib/symtable.py", line 26 in symtable
        top = _symtable.symtable(code, filename, compile_type, module=module)

Root cause (Parser/pegen.c):

    _symtable.symtable() -> _Py_SymtableStringObjectFlags
        -> _PyParser_ASTFromString -> _PyPegen_run_parser (Parser/pegen.c:939).

    When the first parse fails, pegen runs a second "error-recovery" pass to
    build a nicer SyntaxError:

        reset_parser_state_for_error_pass(p);
        _PyPegen_parse(p);                       // heavy second pass
        _Pypegen_set_syntax_error(p, last_token);
        if (PyErr_ExceptionMatches(PyExc_SyntaxError))
            _PyPegen_set_syntax_error_metadata(p);
        return NULL;                             // Parser/pegen.c:966

    The recovery helpers clear errors unconditionally. In
    _PyPegen_set_syntax_error_metadata (Parser/pegen.c:895):

        if (!the_source) {
            PyErr_Clear();                       // L917: wipes MemoryError
            ...
        }
        PyObject* metadata = Py_BuildValue("(iiN)", ...);
        if (!metadata) {
            PyErr_Clear();                       // L928: wipes error, returns
            return;                              //       with NO exception set
        }

    Under OOM these allocations (PyUnicode_Decode, Py_BuildValue, and the
    second _PyPegen_parse) fail and raise MemoryError; the recovery path
    PyErr_Clear()s it and then fails its own allocation, so _PyPegen_run_parser
    returns NULL with a clean error state. That NULL bubbles out of
    _symtable.symtable(); the eval loop's _Py_CheckFunctionResult sees
    result == NULL && !PyErr_Occurred() and (on Py_DEBUG builds) aborts.

    The faulthandler dump shows a MemoryError instance, refcount 1, with an
    EMPTY repr -- a MemoryError whose normalization/repr could not allocate:
    exactly the exception the recovery pass cleared.

A single set_nomemory(4, 0) is enough on these builds: a few earlier
allocations succeed, and the failing allocation lands inside the parser's
error-recovery pass. Observed crash at start=4 on both debug builds.

Likely fix: the parser error-recovery pass must not clear a pending
non-SyntaxError exception (e.g. MemoryError). Save it with
PyErr_GetRaisedException() before reset_parser_state_for_error_pass and
restore it if recovery produced no exception; in
_PyPegen_set_syntax_error_metadata, restore the saved exc on the !metadata
branch instead of PyErr_Clear(); return;.
"""
import symtable
import _testcapi
import faulthandler

faulthandler.enable()

# Fail every allocation from #4 onward. The parse of this trivial source makes a
# few allocations succeed, then a later allocation inside pegen's error-recovery
# pass fails -- and that path clears the MemoryError and returns NULL with no
# exception set, tripping _Py_CheckFunctionResult.
_testcapi.set_nomemory(4, 0)
try:
    symtable.symtable("def f(x):\n    return x + 1\n", "<min>", "exec")
finally:
    _testcapi.remove_mem_hooks()
