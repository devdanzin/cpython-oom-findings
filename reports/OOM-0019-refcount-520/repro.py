"""
Minimal reproducer: abort on _Py_NegativeRefcount (Include/refcount.h:520,
"object has negative ref count") caused by a double-free of `error_line` in
_PyPegen_raise_error_known_location() when Py_BuildValue() fails under OOM.

Affected:   CPython 3.16.0a0 (main), commit 15d7406.
            The _Py_NegativeRefcount check is gated on Py_REF_DEBUG, so the
            abort fires on debug builds (ft_debug_asan, jit). Release builds
            (ft_release, upstream) compile it out; the underlying double-free
            is still present there (latent memory-safety bug -- a cumulative
            sweep was observed to segfault upstream).
Crash:      SIGABRT, ./Include/refcount.h:520 (Py_XDECREF -> Py_DECREF ->
            _Py_NegativeRefcount). "<object ... is freed>",
            "object type name: MemoryError".
Requires:   a free-threaded debug build exposing _testcapi.set_nomemory.

Run:
    python repro.py
    # aborts (rc 134) on the FT debug+ASan build at start=54.

Backtrace (gdb):
    #11 Py_XDECREF                            ./Include/refcount.h:520
    #12 _PyPegen_raise_error_known_location   Parser/pegen_errors.c:363  (Py_XDECREF(error_line))
    #13 RAISE_ERROR_KNOWN_LOCATION            Parser/pegen.h:196
    #14 _Pypegen_set_syntax_error             Parser/pegen_errors.c:404
    #15 _PyPegen_run_parser                   Parser/pegen.c:960

Root cause (Parser/pegen_errors.c, _PyPegen_raise_error_known_location):

    tmp = Py_BuildValue("(OnnNnn)", p->tok->filename, lineno, col_number,
                        error_line, end_lineno, end_col_number);   // L346
    if (!tmp) {
        goto error;                                                // L348
    }
    ...
  error:
    Py_XDECREF(errstr);
    Py_XDECREF(error_line);                                        // L363

    The 'N' format steals/consumes the reference to `error_line`. Crucially,
    Py_BuildValue consumes the 'N' argument even when it FAILS: on a mid-build
    error do_mktuple()/do_ignore() in Python/modsupport.c still run do_mkvalue()
    for the 'N' slot, which decrefs the argument (see the comment at
    modsupport.c:263 "we can't bail immediately on error as this will leak
    refcounts on any 'N' arguments"). Under OOM the PyTuple_New(6) (or an earlier
    conversion) fails, so error_line's only reference is dropped inside
    Py_BuildValue. Py_BuildValue returns NULL, the code does `goto error`, and
    `Py_XDECREF(error_line)` at L363 decrefs the *already-freed* object a second
    time -> negative refcount -> abort. (`error_line` is never reset to NULL
    after L346.)

    The freed str's memory is then reused for the interpreter's pre-allocated
    MemoryError instance under OOM, which is why the reported "object type name"
    is MemoryError and the object is flagged "is freed".

The OOM sweep is needed so that error_line is built successfully (start large
enough) while the subsequent Py_BuildValue allocation fails (start small enough).
Observed crash at start=54 on the FT debug+ASan build; jit reproduces at the
same start and same site.

Likely fix: set `error_line = NULL;` immediately after the Py_BuildValue() call
(before the `if (!tmp)` check) so the error: path's Py_XDECREF(error_line) is a
no-op, or pass error_line with the 'O' format and keep an explicit decref.
"""
import ast
import _testcapi
import faulthandler

faulthandler.enable()

# Generic "invalid syntax" drives _Pypegen_set_syntax_error ->
# RAISE_SYNTAX_ERROR_KNOWN_LOCATION -> _PyPegen_raise_error_known_location.
src = "x y z\n"

_testcapi.set_nomemory(54, 0)   # fail every allocation from #54 onward
try:
    ast.parse(src)              # Py_BuildValue consumes error_line's ref on
                                # failure; error: path decrefs it again -> abort
finally:
    _testcapi.remove_mem_hooks()
