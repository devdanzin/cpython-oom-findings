# OOM-0011 — RETIRED (folded into [OOM-0008](../OOM-0008-typeobject-lookup-pyerr/report.md))

**This was not a distinct bug.** `specialize`'s `assert(!PyErr_Occurred())`
(`Python/specialize.c:364`) is a generic **detector** for a stale pending exception — the
defect is whatever left the `MemoryError` pending. `rr` proved that here it is **OOM-0008**:
`PyFrame_GetBack` swallowing a `MemoryError` under OOM.

## Why it was folded

`rr` reverse-execution of the repro (`optparse.ngettext(...)` with the load-bearing
`import asyncio`) watched `tstate->current_exception` and reversed to where the stale
`MemoryError` was set:

```
_PyErr_SetRaisedException        Python/errors.c:27   (tstate->current_exception = MemoryError)
  <- _PyErr_NoMemory             Objects/exceptions.c:4160
  <- _PyObject_GC_NewVar         (allocating a PyFrameObject)
  <- _PyFrame_MakeAndSetFrameObject / PyFrame_GetBack   Objects/frameobject.c:2404
  <- frame_back_get_impl         Objects/frameobject.c:1116   (reading frame.f_back)
```

That is exactly OOM-0008: `PyFrame_GetBack` fails to allocate the parent frame under OOM and
returns NULL without propagating; `frame_back_get_impl` maps NULL→None, **swallowing the
`MemoryError`**, which stays pending until the next `!PyErr_Occurred()` checkpoint aborts.
OOM-0008's repro catches it at the **type-cache** lookup (`typeobject.c:6343`); this repro
catches it at the **LOAD_ATTR specializer** (`specialize.c:364`). Same producer, different
detector — the run-to-run drift OOM-0011 showed between `:364` and `:6343` was always this one
f_back-swallow. (All of OOM-0011's vehicles — `optparse`/`bdb`/`argparse`/`gettext` — are
frame-walkers that read `f_back`, like OOM-0008's 16.)

## Dedup note (important for this bug class)

Stale-pending-exception crashes are **backtrace-undisambiguable**: the producer (`f_back`) has
already returned before the assert fires, so it is **not on the crash stack** — only the
detector assert is. Dedup can therefore only key the detector site. OOM-0008 now owns **both**
detector sites (`typeobject.c:6343` and `specialize.c:364`), so a stale-exception crash at
either resolves to OOM-0008. **Caveat:** these are producer-agnostic detectors — almost always
the f_back-swallow (OOM-0008), but a stale exception from a *different* producer reaching them
would mislabel; `rr`-confirm if a case looks off.

This `OOM-0011` id is **retired and will not be reused.** `repro.py` (the `optparse` frame-walk)
is kept here as another reproducer of OOM-0008. The gist (`892b6161…`) should be marked
superseded.
