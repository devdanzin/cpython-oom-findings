# Title

Abort: `_Py_NegativeRefcount` at `Include/refcount.h:520` (double-free of `error_line` in `_PyPegen_raise_error_known_location`, `Parser/pegen_errors.c`) when `Py_BuildValue` fails under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

When the parser raises a located `SyntaxError`, `_PyPegen_raise_error_known_location()` passes the freshly built `error_line` string to `Py_BuildValue("(OnnNnn)", ..., error_line, ...)` using the reference-stealing `N` format. `Py_BuildValue` consumes the `N` argument's reference *even when it fails* (by design, to avoid leaks). Under OOM the build fails, the function does `goto error`, and the `error:` cleanup runs `Py_XDECREF(error_line)` on the already-freed object -- a double-free. On debug builds (`Py_REF_DEBUG`) the second decref drives the refcount negative and aborts via `_Py_NegativeRefcount`.

## Reproducer

```python
import ast, _testcapi, faulthandler
faulthandler.enable()
src = "x y z\n"                 # generic invalid syntax -> located SyntaxError
_testcapi.set_nomemory(54, 0)   # fail every allocation from #54 onward
try:
    ast.parse(src)              # error_line built OK, then Py_BuildValue fails
                                # -> N-arg already consumed -> error: decrefs it again
finally:
    _testcapi.remove_mem_hooks()
```

Deterministic at `start=54` on the free-threaded debug+ASan build (and on the `jit` debug build at the same start/site). `ast.parse` is just a convenient way to reach the parser's error path; the OOM budget must be large enough for `error_line` to be built but small enough that the following `Py_BuildValue` allocation fails.

## Backtrace

```
#11 Py_XDECREF                            Include/refcount.h:520   <- decref of already-freed error_line
#12 _PyPegen_raise_error_known_location   Parser/pegen_errors.c:363  <- error: Py_XDECREF(error_line)
#13 RAISE_ERROR_KNOWN_LOCATION            Parser/pegen.h:196
#14 _Pypegen_set_syntax_error             Parser/pegen_errors.c:404
#15 _PyPegen_run_parser                   Parser/pegen.c:960
```

`_Py_NegativeRefcount` reports `<object ... is freed>` with `object type name: MemoryError` -- the freed `str` slab is reused for the interpreter's pre-allocated `MemoryError` instance under OOM. The `jit` ASan trace pins both ends of the double-free: the consuming decref originates at `pegen_errors.c:346` (the `Py_BuildValue` call) and the second decref at `pegen_errors.c:363`.

## Root cause

`Parser/pegen_errors.c`, `_PyPegen_raise_error_known_location()`:

```c
    tmp = Py_BuildValue("(OnnNnn)", p->tok->filename, lineno, col_number,
                        error_line, end_lineno, end_col_number);   /* L346: 'N' steals error_line */
    if (!tmp) {
        goto error;                                                /* L348 */
    }
    ...
error:
    Py_XDECREF(errstr);
    Py_XDECREF(error_line);                                        /* L363: 2nd decref of error_line */
    return NULL;
```

The `N` format consumes the reference to `error_line`. By design `Py_BuildValue` consumes `N` arguments even on failure -- see `do_mktuple()`/`do_ignore()` in `Python/modsupport.c` and the comment at L263: *"we can't bail immediately on error as this will leak refcounts on any 'N' arguments."* When `PyTuple_New(6)` (or an earlier conversion) fails under OOM, `error_line`'s sole reference is dropped inside `Py_BuildValue`, which then returns `NULL`. The function takes `goto error`, but `error_line` was never reset to `NULL`, so `Py_XDECREF(error_line)` at L363 decrefs the freed object again. This is a refcounting bug (double-free), not a missing init.

## Suggested fix

Reset `error_line` to `NULL` immediately after handing it to `Py_BuildValue`, so the error path's `Py_XDECREF` is a no-op:

```c
    tmp = Py_BuildValue("(OnnNnn)", p->tok->filename, lineno, col_number,
                        error_line, end_lineno, end_col_number);
    error_line = NULL;   /* 'N' consumed our reference, even on failure */
    if (!tmp) {
        goto error;
    }
```

Alternatively, pass `error_line` with the non-stealing `O` format and keep a single explicit `Py_DECREF`/`Py_XDECREF` for it on all paths.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). The `_Py_NegativeRefcount` check is gated on `Py_REF_DEBUG`, so the **abort fires on the debug builds** (`ft_debug_asan` and `jit`, both at `start=54`, identical site `pegen_errors.c:363`). Release builds (`ft_release`, `upstream`) compile the check out, so a single trigger survives, but the double-free is still real and memory-unsafe there: a full `start` sweep on the `upstream` release build was observed to crash with a `Segmentation fault`. Per the OOM-catalog convention for refcount-assert aborts, the non-debug builds are recorded as `n/a`.

Three fuzzer vehicles all abort at the identical `Include/refcount.h:520` negative-refcount check with a freed `MemoryError`: two reach the parser via `ast.parse` (`pyclbr._create_tree`), and one via `multiprocessing.forkserver._handle_preload`. Each merely parses/compiles source under OOM and hits the located-`SyntaxError` path.

This is distinct from OOM-0003 (an uninitialized-field assert in `code_dealloc`): same family (OOM during code/parse handling) but a different defect (a genuine double-free via the `N`-format steal-on-failure contract).

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build and on the `jit` debug build (both `Py_REF_DEBUG`). Release/upstream builds: check compiled out (`n/a`); latent double-free (sweep segfault observed on `upstream`).
