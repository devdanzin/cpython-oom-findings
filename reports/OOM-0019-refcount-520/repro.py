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
Requires:   a debug build exposing _testcapi.set_nomemory (Py_REF_DEBUG).

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

Self-sweeping: `python repro.py` runs the trigger under set_nomemory(N, 0) for N in a
sweep, each in a FRESH subprocess (a fresh process avoids cache warm-up shifting the OOM
window), and stops at the first N that crashes. Needs a debug build (the check is compiled
out under NDEBUG). Bare trigger (fixed N=54):
    import ast, _testcapi
    _testcapi.set_nomemory(54, 0)
    ast.parse("x y z\n")
"""
import os
import sys
import subprocess

TRIGGER = r"""
import ast
import _testcapi
import faulthandler
faulthandler.enable()
# Generic "invalid syntax" drives _Pypegen_set_syntax_error ->
# RAISE_SYNTAX_ERROR_KNOWN_LOCATION -> _PyPegen_raise_error_known_location.
_testcapi.set_nomemory({n}, 0)
try:
    ast.parse("x y z\n")   # Py_BuildValue consumes error_line's ref on failure;
                           # error: path decrefs it again -> abort
finally:
    _testcapi.remove_mem_hooks()
"""

SIGNATURE = "Include/refcount.h:520: _Py_NegativeRefcount"

def main():
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=0"}
    # env["PYTHON_GIL"] = "0"   # ONLY if this bug is free-threading-only (it is not)
    for n in range(120):
        out = subprocess.run([sys.executable, "-c", TRIGGER.format(n=n)],
                             capture_output=True, text=True, env=env)
        if SIGNATURE in out.stdout + out.stderr:
            print("reproduced at set_nomemory(%d, 0):" % n)
            sys.stdout.write(out.stderr or out.stdout)
            return 1
    print("no crash in range(120); widen it for your build")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
