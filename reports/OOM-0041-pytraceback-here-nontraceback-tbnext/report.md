# OOM-0041 — RETIRED (folded into [OOM-0036](../OOM-0036-list-append-oom-double-free/report.md))

**This was not an independent bug.** The `Python/traceback.c:313` assertion
`tb_next == NULL || PyTraceBack_Check(tb_next)` (in `_PyTraceBack_FromFrame`, reached from
`PyTraceBack_Here` as an exception unwinds a frame) is a **downstream detector face** of
**OOM-0036** — the `_CALL_LIST_APPEND` `list.append(x)` double-free under `MemoryError`
(filed [python/cpython#151818](https://github.com/python/cpython/issues/151818)).

## Why it was folded

`rr` reverse-execution on this vehicle (target `inspect`) walked from the crash back to the
freeing decref and pinned the producer unambiguously:

- the over-decref'd object was an `inspect.Parameter`;
- it was freed by `_PyList_AppendTakeRefListResize` (`Objects/listobject.c:531`) ← `Py_DECREF`
  ← `_CALL_LIST_APPEND` (`Python/generated_cases.c.h:3981`);
- the `list.append` *steals + frees* the item when the resize fails under OOM, **but the
  operand stack still holds a `_PyStackRef` to it**, so as the frame unwinds,
  `exception_unwind`'s `PyStackRef_XCLOSE` (`generated_cases.c.h:13857`) closes that stale
  reference → the second free.

That is exactly OOM-0036. The same double-freed item, once its storage is reused, is read by
whichever invariant gets there first: the `pycore_stackref.h:726` negative-refcount (the
reproducible face on the FT+ASan build), a `tuple_alloc` freelist SEGV (GIL build), or — when
the reused storage is/aliases the in-flight exception's `traceback` — this `traceback.c:313`
assert (the capture-time face). One producer, many victim/detector sites.

## Where things went

- **Dedup key**: `traceback.c:313` / `_PyTraceBack_FromFrame` now lives in
  `OOM-0036`'s `meta.json` (`sites[]`), so crashes at this site dedup to OOM-0036.
- **Full diagnostic**: see the "Downstream faces confirmed (rr)" note in
  [OOM-0036's report](../OOM-0036-list-append-oom-double-free/report.md).
- **Artifacts**: `vehicle_source.py`, `backtrace.txt`, and `repro.py` are retained in this
  directory for provenance.

This `OOM-0041` id is **retired and will not be reused**. The catalog's generator scripts skip
`status: "folded"` entries, so this is not counted as a distinct bug and emits no dedup keys of
its own.
