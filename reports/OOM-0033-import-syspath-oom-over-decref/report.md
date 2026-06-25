# OOM-0033 — RETIRED (folded into [OOM-0036](../OOM-0036-list-append-oom-double-free/report.md))

**This was not a distinct bug.** It is a third reproducer-path for **OOM-0036** — the
`_CALL_LIST_APPEND` `list.append()`-under-`MemoryError` double-free (filed
[python/cpython#151818](https://github.com/python/cpython/issues/151818)).

## Why it was folded

`rr` reverse-execution of the repro (`sys.path[:] = S; __import__("H")` under the `set_nomemory`
sweep) traced the over-decref'd victim — a 1-character `str` from `S`, held alive by `sys.path` —
and found it is **`list.append`-ed by the import machinery** and freed when the grow fails under
OOM:

```
Py_DECREF(newitem == victim)          Objects/listobject.c:531
  <- _PyList_AppendTakeRefListResize
  <- _CALL_LIST_APPEND                 Python/generated_cases.c.h (gen 3981)
```

That is OOM-0036. The leftover stolen stackref is closed again during the unwind
(`_PyFrame_ClearLocals`@`frame.c:101`), freeing the `str` while `sys.path` still references it.

`PyType_IsSubtype` (`typeobject.c:2931`) and `list_ass_slice` (`listobject.c:1030`) are only
**detector** sites:

- **abort face**: the next iteration's `sys.path[:] = S` (`list_ass_slice` cleanup) `Py_XDECREF`s
  the already-freed element → negative refcount.
- **release/segv face**: `__import__` iterates the freed `sys.path` entry and `PyType_IsSubtype`
  reads a freed type object.

The refcount ledger is **step-for-step identical** to OOM-0005's `pkgutil` trace — both drive a
path-derived string through the *same* import-machinery `list.append`. (An earlier writeup called
this a distinct `list_ass_slice` over-decref; `rr` shows `list_ass_slice` is the detector and the
producer is `_CALL_LIST_APPEND`.)

## Value retained

OOM-0033 is **release-crashing** (upstream segv, like #151818). The `sys.path[:] = S;
__import__(...)` snippet (`repro.py`, kept in this directory) is a clean **pure-stdlib release
reproducer of #151818** and could be offered on that issue.

This `OOM-0033` id is **retired and will not be reused**. Its dedup keys were unique (no
collision), so the fold simply drops them; a crash at `PyType_IsSubtype`/`list_ass_slice` now
surfaces as `oomNEW` for `rr`-triage (almost always OOM-0036 — confirm the producer). The gist
(`249032e1…`) should be marked superseded.
