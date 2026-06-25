# OOM-0005 — RETIRED (folded into [OOM-0036](../OOM-0036-list-append-oom-double-free/report.md))

**This was not a distinct bug.** `_PyFrame_ClearLocals` → `PyStackRef_XCLOSE` (`Python/frame.c:101`
/ `pycore_stackref.h:726`) is a **generic eval-loop over-decref detector** — the same frames are
shared by OOM-0007 and OOM-0023 (as fatals). Both of OOM-0005's reproducers are, in fact,
**OOM-0036** — the `_CALL_LIST_APPEND` `list.append()`-under-`MemoryError` double-free (filed
[python/cpython#151818](https://github.com/python/cpython/issues/151818)).

## Why it was folded

`rr` reverse-execution from the crash back through the victim's full refcount history shows, for
**both** repros, that the over-decref'd object is a value that is **`list.append`-ed** and freed
when the list's grow fails under OOM:

```
Py_DECREF(newitem = <the victim>)     Objects/listobject.c:531
  <- _PyList_AppendTakeRefListResize
  <- _CALL_LIST_APPEND                  Python/generated_cases.c.h (gen 3981)
```

`_CALL_LIST_APPEND` steals the item and decrefs it on the failed resize, but `ERROR_NO_POP`
leaves the now-dead stackref on the value stack; it is closed a second time during the unwind
(`exit_unwind` / `_PyFrame_ClearLocals`), and because the item has a second live reference, the
second close frees a still-referenced object → the negative-refcount abort (or, on the
free-threaded build, the `PyOS_FSPath` SIGSEGV) this report originally described. Those sites are
**downstream detectors** of #151818, not a separate defect.

- `repro.py` here = the `pkgutil.get_importer(str)` UAF reproducer (rr-confirmed OOM-0036).
- the earlier `xml.dom.minidom.parse(0)` reproducer (also rr-confirmed OOM-0036) lives in the
  OOM-0036 report as `repro_xml_minidom.py`.

## Correction note

A prior reverse trace stopped **7 steps in — one step before the `list.append`** — and wrongly
concluded the `pkgutil` face was a distinct bug (no `list.append`). The full ledger shows the
append; the distinctness claim was an error, now retracted.

## Caveat — a possible distinct producer we can't reproduce

OOM-0005's **original discovery capture** reported a **`MemoryError`** victim, which is not a
list-append victim. So a genuinely-distinct over-decref producer at this detector cannot be
*fully* ruled out — but it is not reproducible or pinned; everything we can reproduce is
OOM-0036. **If a `frame.c:101` over-decref abort recurs whose producer (confirm via `rr`) is not
`_CALL_LIST_APPEND`, re-open as a distinct bug.**

## Where things went

- **Dedup keys**: `frame.c:101` / `pycore_stackref.h:726` (and the frame-unwind frames) are now
  **skip-listed** as generic over-decref detectors in `gen_known_sites` — never dedup keys for any
  bug. A bare over-decref *abort* there surfaces as `oomNEW` for `rr`-triage (almost always
  OOM-0036; confirm the producer is `_CALL_LIST_APPEND`).
- **Artifacts**: `repro.py` (pkgutil UAF), `backtrace.txt`, and `vehicle_source.py` are retained
  in this directory for provenance.
- **Upstream**: the issue filed from this finding is a duplicate of #151818 (closed with a dup
  comment); the gist was corrected/superseded.

This `OOM-0005` id is **retired and will not be reused**. The generator scripts skip
`status: "folded"` entries, so it is not counted as a distinct bug and emits no dedup keys of its
own.
