# OOM-0042 — RETIRED (folded into [OOM-0040](../OOM-0040-extensions-cache-set-null-key/report.md))

**This was not a distinct bug.** The `assert(!PyErr_Occurred())` at `import_run_extension`
(`Python/import.c:2301`) is a generic **detector** for a stale pending exception; the defect is
whatever left the `MemoryError` pending. `rr` proved that here it is **OOM-0040**: the
extensions-cache key allocation failing under OOM and being mishandled by
`_extensions_cache_find_unlocked`.

## Why it was folded

The original OOM-0042 write-up hypothesized that an allocation *inside* `readline`'s
single-phase `PyInit_*` failed and was left pending. `rr` refuted that. Recording an OOM-0042
vehicle and watching `tstate->current_exception`, then `reverse-continue`-ing to where the
stale `MemoryError` was set:

```
_PyErr_NoMemory                        Objects/exceptions.c
  <- hashtable_key_from_2_strings      Python/import.c:1297   (PyMem_RawMalloc of the cache key fails)
  <- _extensions_cache_find_unlocked   Python/import.c:1389   (returns NULL = "not found", MemoryError set)
  <- import_find_extension             (cache lookup before running the init)
```

That is the **same producer as OOM-0040**. The cache key-builder allocation fails;
`_extensions_cache_find_unlocked` returns `NULL` *without distinguishing* "key-alloc failed
(OOM)" from "entry not found". Two faces follow, depending on which caller mishandles the NULL:

- **SET path** (OOM-0040): `_extensions_cache_set` passes the still-`NULL` key to
  `_Py_hashtable_set` → `hashtable_hash_str` does `strlen(NULL)` → **SEGV** (`import.c:1312`,
  release-crashing).
- **GET path** (this one): the lookup returns "not found" with the `MemoryError` pending, the
  import proceeds to run the init, and the post-init `assert(!PyErr_Occurred())` at
  `import_run_extension:2301` **aborts** (debug-only).

One fix — give `_extensions_cache_find_unlocked` an error signal distinct from "not found" —
covers both faces, which is why they are one bug.

## Dedup note

OOM-0042's only dedup key was `import_run_extension:2301` (the detector assert). It has been
**moved to OOM-0040's `sites[]`**, so a GET-path stale-`MemoryError` abort at that line now
dedups to OOM-0040. (Collision-checked: that key was unused elsewhere; OOM-0022 keys
`reload_singlephase_extension`/`import_find_extension`, a different import-path detector.)

This `OOM-0042` id is **retired and will not be reused.** `repro.py` and `vehicle_source.py`
are kept here as additional reproducers of OOM-0040's GET-path (abort) face. There was no gist
to supersede (OOM-0042 was never published).
