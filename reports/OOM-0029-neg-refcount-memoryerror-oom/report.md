# OOM-0029 — RETIRED (folded into [OOM-0036](../OOM-0036-list-append-oom-double-free/report.md))

**This was not a distinct bug.** It is a fourth reproducer-path for **OOM-0036** — the
`_CALL_LIST_APPEND` `list.append()`-under-`MemoryError` double-free (filed
[python/cpython#151818](https://github.com/python/cpython/issues/151818)).

## Why it was folded

`rr` reverse-execution of the repro (`_pyrepl.utils.disp_str("\x004\x8A\xD5\x03")` under the
`set_nomemory` sweep) traced the over-decref'd victim. Two corrections to the original report:

1. **The victim is a `str` (a display segment), not a `MemoryError`.**
2. `disp_str` builds a list of display segments via `list.append`. The victim `str` is appended
   (the list already had 4 elements), the grow fails under OOM, and it's freed:

```
Py_DECREF(newitem == victim)          Objects/listobject.c:531
  <- _PyList_AppendTakeRefListResize
  <- _CALL_LIST_APPEND                 Python/generated_cases.c.h (gen 3981)
```

The leftover stolen stackref is then closed again by `exception_unwind` → the `str` is freed
while still referenced by the segment structure. The **negative refcount is only detected later**,
when a `list_dealloc:567 → subtype_dealloc:2876 → tuple_dealloc:277` cascade (the segment tuples)
`Py_XDECREF`s the already-freed `str`. Those dealloc frames are **detectors**, not the bug.

The "load-bearing mixed control/high-byte argument" simply produces enough `list.append` display
segments to land a resize-failure inside the sweep window — a single character makes too few
segments. The refcount ledger matches OOM-0005/0033's import-path traces (same `_CALL_LIST_APPEND`).

This `OOM-0029` id is **retired and will not be reused**. Its unique keys (`tuple_dealloc:277`,
`listobject.c:567`) are dropped; the generic dealloc-cascade frames it shared
(`subtype_dealloc`/`list_dealloc`) remain under their real owners. A `tuple_dealloc` negref now
resolves as ambiguous-known / `oomNEW` → `rr`-triage (almost always OOM-0036). The `disp_str`
snippet (`repro.py`) is kept here as a `_pyrepl`-path reproducer of #151818. The gist
(`10e0fdaf…`) should be marked superseded.
