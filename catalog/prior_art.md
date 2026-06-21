# Prior art — CPython issue-tracker check (2026-06-19)

Checked all 35 findings against `python/cpython` issues (open + closed) via
`gh search issues`, keyed on each crash-site C function plus a distinctive term
(assertion expression / mechanism / `MemoryError`). Verdicts below.

**Caveat:** a "no match" is *no matching issue found by these searches*, not proof of
novelty — a duplicate filed with very different wording could be missed.

## Already filed upstream

| Finding | Issue | State | By | Note |
|---------|-------|-------|----|------|
| **OOM-0001** | [#151673](https://github.com/python/cpython/issues/151673) | open | devdanzin | Exact match — our own report (`Py_DECREF(NULL)` in `setup_context`/`do_warn` under MemoryError). |

That is the **only** one of the 35 currently in the tracker.

## No matching issue found → appear novel (34)

OOM-0002 … OOM-0035 returned no issue describing the same function + mechanism under
allocation failure. A few have *related but distinct* prior issues worth citing when filing:

- **OOM-0012** — instrumentation/monitoring has had crashes (e.g. #106012, `monitoring_version`
  mismatch, markshannon, closed/fixed 2023) but that is a different assert from OOM-0012's
  `_co_monitoring`-NULL-under-OOM `debug_check_sanity`.
- **OOM-0019** — `_PyPegen_raise_error_known_location` has prior parser-fuzzer issues
  (#95876 format bug; #89657/#96268/#100050 parser asserts) — none is the OOM double-free.
- **OOM-0022 / OOM-0023** — the "C function returned/deallocated with an exception set" theme
  has prior issues (#109613 `os.stat` `_Py_CheckSlotResult`; #89373 docs: tp_dealloc may run
  with the error indicator set) — different triggers; cite for context, not as duplicates.

## OOM-crash reporting landscape (for context)

The allocation-failure crash vein is already active in the tracker:
- #151673 (devdanzin) — OOM-0001 (above).
- #146093 (devdanzin) — `_set_str` missing NULL check after `PyUnicode_DecodeASCII` in `_csv.c`
  — an earlier fusil-OOM finding, **not** in this catalog.
- #151112 (stestagg) — double free in `assemble_init` under allocation failure — someone else's
  OOM finding, not in this catalog.
- #74880 / #93649 — the `_testcapi.set_nomemory` infrastructure itself (not crash reports).

No single OOM "umbrella" tracking issue was found; the campaign's umbrella-issue plan still applies.

## Addendum 2026-06-21 — OOM-0038 (dup-check + filing policy)

**OOM-0038** (`_PyIndexPool_AllocIndex` calls `PyErr_NoMemory()` with no active thread state while
reserving a TLBC index during free-threaded sub-interpreter creation, `index_pool.c:167`) —
**appears novel.** `gh search issues python/cpython` on the crash-site symbols
(`_PyIndexPool_AllocIndex`, `_Py_ReserveTLBCIndex`, `index_pool.c`) and distinctive terms
(`_PyInterpreterState_GET without an active thread state`, `new_threadstate MemoryError`,
`PyErr_NoMemory sub-interpreter create`, `Py_NewInterpreterFromConfig MemoryError`) returned no
matching report. Nearest prior art: **#126644** (devdanzin) "`_interpreters` is not thread safe on
the free-threaded build" — a **data race** in the *same* `index_pool.c` but on the `heap_pop`
freelist branch (`index_pool.c:92` ← `_PyIndexPool_AllocIndex:173`), from concurrent create/destroy,
**not** allocation failure; closed NOT_PLANNED (2025-01-11), fix PR #126696 closed unmerged.
Distinct defect/branch/mechanism/fix — cite for context, not a duplicate.

**Filing policy — free-threaded sub-interpreter fuzzing crashes are on hold.** colesbury (FT lead)
on **#143232** (devdanzin, "Assertion failures at interpreter finalization from using `_interpreters`
with free-threading"): "I don't think it's worth fuzzing [subinterpreters] for now until the known
issues are addressed" (cf. the FT subinterpreter data-race umbrella **#129824**). So **OOM-0038** and
**OOM-0020** — both FT-only subinterpreter-create OOM crashes — are **not** to be filed upstream for
now (see `filing_hold` in their `meta.json`); they stay cataloged and become file-ready once the FT
subinterpreter area stabilizes. **OOM-0037** is **kept fileable** — it also crashes GIL builds and is
not a race, so it falls outside that scope.
