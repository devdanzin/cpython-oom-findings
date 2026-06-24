# SEGV: `_extensions_cache_set` hashes a NULL key under OOM (`hashtable_hash_str`, `import.c:1312`)

*Importing a not-yet-cached C extension under a bounded OOM window: the extensions-cache key allocation fails (NULL), but `_extensions_cache_find_unlocked` returns without signalling that, so `_extensions_cache_set` passes the NULL key to `_Py_hashtable_set`, and `hashtable_hash_str` dereferences it (`strlen(NULL)`) → SEGV. Crashes release builds, not just debug.*

_AI Disclaimer: this report was drafted by Claude Code, which also reproduced the crash and root-caused it._

## Crash report

When a C extension module is imported for the first time, `import_run_extension` records it in the per-interpreter extensions cache (`EXTENSIONS.hashtable`) via `update_global_state_for_extension → _extensions_cache_set`. The cache key is a heap string built by `hashtable_key_from_2_strings(path, name)` (a `PyMem_RawMalloc`). Under memory pressure that allocation can fail and return `NULL`.

`_extensions_cache_set` builds the key indirectly through `_extensions_cache_find_unlocked(path, name, &key)`. On key-alloc failure that helper returns `NULL` (meaning "no entry") **before** writing `*p_key`, so the caller's `key` stays `NULL`. `_extensions_cache_set` then sees `entry == NULL`, builds the new cache value, and calls `_Py_hashtable_set(EXTENSIONS.hashtable, key /* == NULL */, newvalue)`. The hashtable's key-hash callback `hashtable_hash_str` does `Py_HashBuffer(key, strlen((const char *)key))` → `strlen(NULL)` → **SEGV**.

This is a plain NULL-pointer dereference, **not** a `Py_DEBUG`-only assertion: it crashes release builds too (confirmed SEGV on free-threaded debug+ASan, free-threaded release, and GIL release). It requires a *bounded* OOM window (the key alloc fails, then a **later** allocation — `alloc_extensions_cache_value` for `newvalue` — succeeds), which is why fusil's `--oom-seq` windowed mode surfaces it where the single-call fail-forever sweep does not (under fail-forever the `newvalue` alloc also fails and the function bails at `goto finally` before the bad `_Py_hashtable_set`).

## Reproducer

Vehicle-confirmed; **minimization partial** (see Notes). The preserved fuzzer vehicle `vehicle_source.py` (target module `pdb`, whose OOM sweep triggers a first-time C-extension import) reproduces the SEGV deterministically. The mechanism in isolation:

```python
# Reaches the NULL-key path, but a generic "import C extensions under OOM" sweep also trips
# OTHER first-import OOM bugs (GC validate_gc_objects negrefcount; co->_co_unique_id assert)
# that can fire first -- so this is a mechanism demo, not a clean isolated trigger.
# vehicle_source.py is the reliable reproducer. The defect itself is unconditional given a
# NULL key (Root cause).
import faulthandler; faulthandler.enable()
import sys, importlib, gc
gc.disable()                       # suppress one competing import-OOM bug
from _testcapi import set_nomemory
DISABLE = 2_000_000_000
set_nomemory(DISABLE, 0)
CANDS = ["array", "_csv", "_lsprof", "mmap", "_random", "cmath", "unicodedata",
         "_struct", "select", "_socket", "binascii", "_pickle", "_zoneinfo", "_bz2", "_lzma"]
for start in range(6000):
    name = CANDS[start % len(CANDS)]
    sys.modules.pop(name, None)    # force re-import of an uncached extension
    set_nomemory(start, start + 6) # bounded window: key alloc fails, later allocs resume
    try:
        try:
            importlib.import_module(name)
        finally:
            set_nomemory(DISABLE, 0)
    except BaseException:
        pass
print("survived (no crash)")
```

## Backtrace

```
Fatal Python error: Segmentation fault   (READ at a near-NULL address)

# C path (ASan, free-threaded debug+ASan; identical on release):
#7  hashtable_hash_str            Python/import.c:1312   strlen((const char *)key), key == NULL
#8  _Py_hashtable_get_entry_generic Python/hashtable.c:142
#9  _Py_hashtable_set             Python/hashtable.c:225
#10 _extensions_cache_set         Python/import.c:1497   _Py_hashtable_set(EXTENSIONS.hashtable, key, newvalue)
#11 update_global_state_for_extension Python/import.c:1870
#12 import_run_extension          Python/import.c:2236
#13 _imp_create_dynamic_impl      Python/import.c:5529
#14 _imp_create_dynamic           Python/clinic/import.c.h:489
```

See `backtrace.txt` for the full capture. `key` is NULL at frame #7 because the key-builder allocation failed under OOM (frame absent — it already returned NULL).

## Root cause

`Python/import.c`. The key builder returns NULL on OOM:

```c
static void *
hashtable_key_from_2_strings(PyObject *str1, PyObject *str2, const char sep)
{
    ...
    char *key = PyMem_RawMalloc(size);
    if (key == NULL) {
        PyErr_NoMemory();
        return NULL;                 /* <- under OOM */
    }
    ...
}
```

`_extensions_cache_find_unlocked` propagates that as a plain "not found" and **leaves `*p_key` unwritten**:

```c
static _Py_hashtable_entry_t *
_extensions_cache_find_unlocked(PyObject *path, PyObject *name, void **p_key)
{
    if (EXTENSIONS.hashtable == NULL) {
        return NULL;
    }
    void *key = hashtable_key_from_2_strings(path, name, HTSEP);
    if (key == NULL) {
        return NULL;                 /* <- returns BEFORE writing *p_key */
    }
    _Py_hashtable_entry_t *entry = _Py_hashtable_get_entry(EXTENSIONS.hashtable, key);
    if (p_key != NULL) {
        *p_key = key;                /* only reached on success */
    }
    ...
}
```

So in `_extensions_cache_set` the local `void *key = NULL;` is never updated, `entry == NULL`, and it proceeds to the new-entry path:

```c
    void *key = NULL;
    ...
    _Py_hashtable_entry_t *entry = _extensions_cache_find_unlocked(path, name, &key);
    /* key is still NULL here on OOM, but entry == NULL is read as "not cached" */
    ...
    if (entry == NULL) {
        if (_Py_hashtable_set(EXTENSIONS.hashtable, key /* NULL */, newvalue) < 0) {  /* SEGV in hashtable_hash_str */
            PyErr_NoMemory();
            goto finally;
        }
        ...
    }
```

`_extensions_cache_set` cannot distinguish "key allocation failed (OOM)" from "entry not found, key valid" — both come back as a NULL entry — and dereferences the NULL key.

## Suggested fix

Bail out of `_extensions_cache_set` when the key wasn't produced. Since `hashtable_key_from_2_strings` already set `MemoryError`, a check after `find_unlocked` suffices:

```c
    _Py_hashtable_entry_t *entry = _extensions_cache_find_unlocked(path, name, &key);
    if (key == NULL) {
        /* the key allocation failed (OOM); MemoryError is already set */
        goto finally;
    }
```

(Alternatively, give `_extensions_cache_find_unlocked` an explicit error signal distinct from "not found" so every caller can tell the cases apart — the other call sites pass `p_key == NULL` and already destroy the key, so they are unaffected.)

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`), fusil `--oom-seq` windowed mode. **Recurring across all three fleet machines** (local FT debug+ASan, the `oca` and `magalu` boxes) and several target modules (`pdb`, `cmd`, `code`, `site`) — all just vehicles that trigger a first-time C-extension import during their OOM sweep.

**Release-crashing (high value).** A genuine NULL deref, not a debug assertion: SEGV confirmed on `ft_debug_asan`, `ft_release`, and the GIL release build. On the `jit` build this *vehicle*'s allocation timing lands on OOM-0022 (`_Py_CheckSlotResult`) first, but the `import.c` code is identical, so the defect is build-agnostic.

**Distinct from OOM-0022.** Both go through `_imp_create_dynamic_impl` (the generic first-import-of-an-extension caller), but OOM-0022 is a `_Py_CheckSlotResult` *fatal* at a different point; this is a NULL-key *SEGV* in the extensions-cache set. The signature is keyed on `hashtable_hash_str`/`_extensions_cache_set` (not the shared `_imp_create_dynamic_impl` frame) so the two do not conflate.

**Minimization: partial.** A generic "import C extensions under a windowed OOM" reproducer reaches this path but competes with other first-import OOM bugs (GC `validate_gc_objects` negative-refcount; the `co->_co_unique_id` assert) that can fire first; no clean isolated stdlib trigger was pinned. `vehicle_source.py` is the reliable reproducer.

## Versions

- main (3.16.0a0), commit `1b9fe5c` (free-threaded debug+ASan, Clang 21). SEGV reproduced from the vehicle on `ft_debug_asan` and `ft_release` (free-threaded) and on the GIL release build — a real production crash, not debug-only.

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking OOM-related crash findings.*
