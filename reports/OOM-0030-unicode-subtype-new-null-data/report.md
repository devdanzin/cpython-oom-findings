# Abort: `Py_DECREF` of NULL-data unicode in `unicode_subtype_new` (`unicodeobject.c:13986`)

*A failing data-buffer allocation in `unicode_subtype_new` sends it to `onError: Py_DECREF(self)` while `self`'s data pointer is still NULL; `unicode_dealloc` -> `unicode_is_singleton` then asserts `data != NULL`. Triggered by parsing a header value containing a NUL byte, which instantiates a `str` subclass.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Creating a `str` subclass instance allocates the object (`self`) and then allocates its
character buffer. If that buffer allocation (or another step) fails under memory
pressure, `unicode_subtype_new` jumps to `onError: Py_DECREF(self)` while
`_PyUnicode_DATA_ANY(self)` is still NULL. The decref runs `unicode_dealloc` →
`unicode_is_singleton`, which calls `_PyUnicode_NONCOMPACT_DATA(self)` and asserts
`data != NULL` → abort (debug builds).

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the vehicle; deterministic, re-verified 40×):

```python
import faulthandler, email._header_value_parser as hvp
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks
for start in range(0, 40):
    try:
        set_nomemory(start, 0)
        try:
            hvp.get_value("\x00")          # builds str-subclass tokens
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
```

Parsing a header value with a NUL byte instantiates a `str` subclass; under allocation
failure it is freed with `self->data == NULL`. (An earlier hand reduction
`class S(str): S("…")` exercised `unicode_subtype_new` but didn't hit the window; shrinkray
found the `email.get_value` trigger.) The full fuzzer vehicle is preserved as `vehicle_source.py`.

## Backtrace

```
unicodeobject.h:272: _PyUnicode_NONCOMPACT_DATA: Assertion `data != NULL' failed.
#11 unicode_is_singleton   Objects/unicodeobject.c:1723   # _PyUnicode_NONCOMPACT_DATA(self), data == NULL
#12 unicode_dealloc        Objects/unicodeobject.c:1629
#13 subtype_dealloc        Objects/typeobject.c:2876
#16 unicode_subtype_new    Objects/unicodeobject.c:13986   # onError: Py_DECREF(self)
#17 unicode_new_impl       Objects/unicodeobject.c:13849   # str.__new__ for a subclass
```

## Root cause

`Objects/unicodeobject.c`, `unicode_subtype_new`: `self` (the subclass instance) is
allocated first; its data buffer and fields are filled afterward:

```c
    self = type->tp_alloc(type, 0);          /* self->data is NULL here */
    ...
    data = PyObject_Malloc(...);             /* can fail under OOM */
    if (data == NULL) { ... goto onError; }
    _PyUnicode_DATA_ANY(self) = data;
    ...
onError:
    Py_DECREF(self);                         /* self->data still NULL -> unicode_dealloc chokes */
    return NULL;
```

On the failure path `self` is a fully-typed `str` subclass whose
`_PyUnicode_DATA_ANY` is NULL. `unicode_dealloc` calls `unicode_is_singleton`, which
unconditionally dereferences `_PyUnicode_NONCOMPACT_DATA(self)` (asserts `data != NULL`).
The object is freed before it is in a dealloc-safe state.

## Suggested fix

Make a half-constructed unicode safe to deallocate. Either initialize the subtype's
data/state so `unicode_dealloc` tolerates it, or guard the dealloc path:
`unicode_is_singleton` (and `unicode_dealloc`) should treat a NULL data pointer as
"not a singleton / nothing to inspect" rather than asserting. The robust fix is to set
`self`'s length/data to an empty-but-valid state immediately after `tp_alloc`, before any
fallible allocation.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`); flagged `oomNEW` by fusil's
in-loop dedup against the current catalog (found by 2 fleet instances on
`3.16_ft_debug_asan` / `jit`). Same "partially-constructed object freed on the OOM error
path" class as OOM-0024 (`template_iter`), different object (str subclass). Distinct from
OOM-0009 (`replace`, unicodeobject.c:10783). Debug-only abort (the `data != NULL` assert
is `Py_DEBUG`-gated; on release the NULL data is dereferenced -> segfault/UAF risk).

## Versions

- main (3.16.0a0), commit 15d7406. Aborts on free-threaded debug+ASan and JIT debug+ASan;
  assert compiled out on the release builds.

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking 35 OOM-related crash findings.*
