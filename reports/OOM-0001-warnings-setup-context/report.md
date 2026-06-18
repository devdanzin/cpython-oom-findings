# Title

Segfault: `Py_DECREF(NULL)` in `setup_context`/`do_warn` (`_warnings.c`) when emitting a warning under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._
## Crash report

Emitting a warning while allocations are failing segfaults on a `Py_DECREF` of a NULL `filename`. `setup_context()` does not NULL-check `PyUnicode_FromString("<sys>")`, and the resulting NULL is later decref'd either by `do_warn()` (success path) or by `setup_context()`'s own `handle_error:` label (which uses `Py_DECREF`, not `Py_XDECREF`).

## Reproducer

```python
import _testcapi, warnings, faulthandler
faulthandler.enable()
warnings.simplefilter("always")
_testcapi.set_nomemory(0, 0)   # fail every allocation from here on
warnings.warn("boom")          # -> Py_DECREF(NULL) -> SIGSEGV
```

Deterministic (`start=0`). Reproduced on `main`.

## Backtrace

```
#0 _Py_atomic_load_uint32_relaxed   Include/cpython/pyatomic_gcc.h
#1 Py_DECREF                        Include/refcount.h
#2 do_warn                          Python/_warnings.c:1139   <- Py_DECREF(filename), filename == NULL
#3 warnings_warn_impl               Python/_warnings.c:1184
#4 warnings_warn                    Python/clinic/_warnings.c.h:161
```

`(gdb) frame 2; print filename` → `$1 = (PyObject *) 0x0`.

## Root cause

In `setup_context()` (`_warnings.c`), the `f == NULL` branch (~L1036):

```c
if (f == NULL) {
    globals = interp->sysdict;
    *filename = PyUnicode_FromString("<sys>");   /* return value unchecked */
    *lineno = 0;
}
```

Under memory pressure two allocations fail in sequence:
1. `PyThreadState_GetFrame()` returns NULL (its frame-object allocation fails), so the `f == NULL` branch is taken; then
2. `PyUnicode_FromString("<sys>")` itself returns NULL, leaving `*filename == NULL`.

The NULL `*filename` then reaches a `Py_DECREF`:
- if `setup_context()` returns success (registry and `__name__` already present in `globals`, so no further allocation is needed), `do_warn()` runs its cleanup `Py_DECREF(filename)` at L1139 — NULL deref; **or**
- if `setup_context()` instead hits `handle_error:` (L1084), that path runs `Py_DECREF(*filename)` (L1087, **not** `Py_XDECREF`) — NULL deref.

## Suggested fix

```c
    *filename = PyUnicode_FromString("<sys>");
    if (*filename == NULL) {
        goto handle_error;
    }
```

and at `handle_error:` use `Py_XDECREF(*filename)` (since `*filename` may legitimately be NULL there).

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). Same pattern as gh-146080 (`Py_DECREF(NULL)` in an `_ssl.c` error label). Code is long-standing, so 3.13–3.15 are likely affected as well (unverified).
