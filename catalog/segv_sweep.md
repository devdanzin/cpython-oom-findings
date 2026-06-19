# SEGV phase: site-centric sweep of the segv crash vehicles

Triage of the **254 segv crash directories** (stdout shows `Segmentation fault` /
`AddressSanitizer: SEGV`) from `~/crashers/python-4..7`. Run 2026-06-18, commit `15d7406`.

## Method (why the obvious approach fails)

The saved `stdout` faulthandler C-stack reflects the **fuzz host's** crash. The host
binary (`/home/ubuntu/projects/upstream_cpython/python`) is itself a free-threaded
debug+ASan build, equivalent to the local `3.16_ft_debug_asan_cpython`. But OOM crash
sites are **nondeterministic across binaries**: which allocation fails first shifts
with ASLR / hash seed / ASan quarantine / freelist state, so the *same* `source.py`
crashes at a *different* site on the host vs locally. Probe result — six vehicles with
the **identical** host stdout chain `_Py_Dealloc <- PyList_New <- …` re-ran locally to
six different outcomes (OOM-0004 abort, OOM-0013 abort, OOM-0001 segv, an obmalloc
segv, a refcount fatal, and one non-repro). **So the stdout signature is not a bug key.**

However, a single vehicle re-run **locally is deterministic** (same site every run,
verified 3×). So the method is:

1. `scripts/segv_sweep.sh` runs every vehicle under the local `ft_debug_asan` build in
   gdb (`scripts/segv_worker.sh`) and records the **true innermost CPython frame** =
   the deterministic local crash site. (The worker skips the faulthandler/fatal/assert
   reporting plumbing — `fatal_error_exit`, `_Py_FatalError*`, `_PyObject_AssertFailed`,
   `_Py_NegativeRefcount`, `_Py_DumpStack` — so the recorded frame is the real site, not
   the abort handler.)
2. `scripts/bin_sites.py` bins by site and cross-references the known catalog
   (`reports/*/meta.json` `sites[]`), so each vehicle is KNOWN-bug or NEW.
3. Only genuinely-new sites get a report; everything else is recorded as a vehicle of an
   existing bug. Raw data: `catalog/segv_sites_raw.tsv`,
   `catalog/segv_fatal_bucket_resolved.tsv`.

## Result: 254 vehicles → 1 new bug, 10 existing bugs, 46 host-only

| Bug | segv vehicles | deterministic local site |
|-----|--------------:|--------------------------|
| **OOM-0024 (NEW)** | 2 | `templateiter_clear` Objects/templateobject.c:53 (t-string iterator, uninit fields) |
| OOM-0001 | 109 | `setup_context`/`do_warn` Python/_warnings.c (via `warnings_warn_impl` ×77, `warn_unicode` ×32) |
| OOM-0002 | 29 | `PyContextVar_Set` Python/context.c:367 (via `method_vectorcall_O` ×26, `_NOARGS` ×3) |
| OOM-0003 | 8 | `code_dealloc` Objects/codeobject.c:2440 |
| OOM-0004 | 5 | `clear_freelist` Objects/object.c:909 |
| OOM-0005 | 10 | `_PyFrame_ClearLocals` Python/frame.c:101 (negative refcount) |
| OOM-0006 | 7 | `dictiter_dealloc` Objects/dictobject.c:5532 |
| OOM-0008 | 1 | `_PyType_LookupStackRefAndVersion` Objects/typeobject.c:6343 |
| OOM-0013 | 16 | `_Py_BuiltinCallFastWithKeywords_StackRef` Python/ceval.c:843/841 |
| OOM-0020 | 19 | `_PyMem_DebugCheckAddress` Objects/obmalloc.c:3344 |
| OOM-0022 | 2 | `_Py_CheckSlotResult` Objects/call.c:80 |
| _NOREPRO_ | 46 | did not crash on local `ft_debug_asan` within budget — host-only / timing |
| **total** | **254** | |

208 vehicles attributed to 10 already-cataloged bugs; 2 to the one new bug (OOM-0024);
46 did not reproduce locally.

### The "fatal_error_exit" sub-bucket (20)

20 vehicles whose host message was `Fatal Python error: Segmentation fault` re-ran
locally as **debug aborts**, with `fatal_error_exit` masking the site. Resolved (with
the plumbing-skip worker) to: OOM-0005 ×10 (`_PyFrame_ClearLocals` negative refcount),
OOM-0006 ×7 (`dictiter_dealloc`), OOM-0022 ×2 (`_Py_CheckSlotResult`), OOM-0003 ×1
(`code_dealloc`). **No new bug.** See `catalog/segv_fatal_bucket_resolved.tsv`.

## NOREPRO (46) — possible low-yield follow-up

These crashed on the host but not on the local `ft_debug_asan` within the 180s/1000-step
budget (most likely nondeterministic OOM timing; a few may be release-only or need a
longer sweep). Listed in `catalog/segv_sites_raw.tsv` (signal column `NOREPRO`). Not
reportable without a local repro+backtrace; revisit only if a cheap re-run with a wider
sweep or a different build surfaces a stable site.
