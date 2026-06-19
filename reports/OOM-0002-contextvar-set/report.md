# Segfault: `Py_DECREF(NULL)` in `PyContextVar_Set` (`Python/context.c`) when `token_new()` fails under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`PyContextVar_Set` does not NULL-check the result of `token_new()`. Under memory pressure `token_new()` returns NULL; if the following `contextvar_set()` also fails, the error path runs `Py_DECREF(tok)` on the NULL token and segfaults.

## Reproducer

```python
import contextvars
from _testcapi import set_nomemory, remove_mem_hooks
cv = contextvars.ContextVar("x")
for start in range(16):            # crashes at start=2
    set_nomemory(start, 0)
    try:
        try:
            cv.set(object())
        finally:
            remove_mem_hooks()
    except MemoryError:
        pass
```

A single `set_nomemory(0, 0); cv.set(object())` does *not* crash — `PyContextVar_Set`'s own early `context_get()` fails first and returns cleanly. The crash needs a budget where the early allocations succeed but `token_new()` and `contextvar_set()` then fail, hence the short sweep.

## Backtrace

```
#0 _Py_atomic_load_uint32_relaxed
#1 Py_DECREF              Include/refcount.h:345    (op == 0x0)
#2 PyContextVar_Set       Python/context.c:367      (Py_DECREF(tok), tok == NULL)
```

## Root cause

`Python/context.c`, `PyContextVar_Set` (L346):

```c
    PyContextToken *tok = token_new(ctx, var, old_val);  /* L363: may return NULL, UNCHECKED */
    Py_XDECREF(old_val);
    if (contextvar_set(var, val)) {                      /* L366: fails under OOM (_PyHamt_Assoc -> NULL) */
        Py_DECREF(tok);                                  /* L367: tok == NULL -> SIGSEGV */
        return NULL;
    }
    return (PyObject *)tok;
```

`token_new()` allocates (`PyObject_GC_New`) and can return NULL on failure, but `tok` is not checked before the `Py_DECREF(tok)` on the `contextvar_set()` failure path. (On the success path the function also returns `tok` unchecked — harmless NULL-with-exception, but the modification still happened.)

## Suggested fix

```c
    PyContextToken *tok = token_new(ctx, var, old_val);
    Py_XDECREF(old_val);
    if (tok == NULL) {
        return NULL;
    }
```

(or `Py_XDECREF(tok)` on the error path).

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). Same pattern as gh-146080 (`Py_DECREF(NULL)` in an `_ssl.c` error label). **Not** free-threading-specific: reproduces on free-threaded and default (GIL) builds, debug and release. (A `_py_warnings`/`ContextVar` vehicle reaches this only when `context_aware_warnings` is enabled — the default on free-threaded builds — but the C bug is build-agnostic.)

## Versions

- main (3.16.0a0); reproduced on free-threaded debug+ASan, free-threaded release, and GIL release builds.
