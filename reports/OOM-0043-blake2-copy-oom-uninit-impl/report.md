# Fatal error / latent UB: `_blake2` `.copy()` under OOM decrefs a half-built object with uninitialized `impl` (`blake2module.c:997`)

*`_blake2.blake2s().copy()` allocates a GC-tracked `Blake2Object` whose `impl` discriminant is left uninitialized, then fails the HACL* state `malloc`; the error path decrefs the object without ever setting `impl`, so `py_blake2_clear` switches on garbage and hits `Py_UNREACHABLE()` (debug abort; a wild `free`/SIGSEGV on release).*

_AI Disclaimer: this report was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`hashlib`'s BLAKE2 objects (`_blake2.blake2b` / `_blake2.blake2s`) carry an `impl`
enum (`Blake2b`, `Blake2s`, `Blake2b_256`, `Blake2s_128`) that discriminates which
HACL* backend state pointer is live. The deallocator switches on it:

```c
py_blake2_clear (Modules/blake2module.c:964)
    switch (self->impl) {
        case Blake2b:  BLAKE2_FREE(Blake2b, self->blake2b_state); break;
        case Blake2s:  BLAKE2_FREE(Blake2s, self->blake2s_state); break;
        ...
        default:       Py_UNREACHABLE();          // blake2module.c:997
    }
```

The object is allocated by `new_Blake2Object`, which `PyObject_GC_New`s it (memory
**not** zeroed) and immediately `PyObject_GC_Track`s it — so at that point `impl` and
the state pointers are garbage:

```c
new_Blake2Object (blake2module.c:387)
    Blake2Object *self = PyObject_GC_New(Blake2Object, type);   // fields uninitialised
    HASHLIB_INIT_MUTEX(self);
    PyObject_GC_Track(self);                                     // tracked, impl still garbage
    return self;
```

The constructor path (`py_blake2_new`) handles this correctly: it sets `self->impl`
and NULL-inits the state pointers **immediately** after `new_Blake2Object`, before any
fallible allocation (`blake2module.c:556-578`). The **`.copy()` path does not**:

```c
_blake2_blake2b_copy_impl (blake2module.c:798)
    cpy = new_Blake2Object(cls);            // impl uninitialised, GC-tracked
    rc = blake2_blake2b_copy_unlocked(self, cpy);
    if (rc < 0) { Py_DECREF(cpy); return NULL; }   // line 812

blake2_blake2b_copy_unlocked (blake2module.c:749)
    switch (self->impl) {
        case Blake2s:
            cpy->blake2s_state = Hacl_Hash_Blake2s_copy(self->blake2s_state);  // raw malloc
            if (cpy->blake2s_state == NULL) goto error;                        // <-- fails under OOM
        ...
    }
    cpy->impl = self->impl;                 // line 781 -- NEVER REACHED on the error path
    return 0;
error:
    (void)PyErr_NoMemory();
    return -1;
```

When the HACL copy `malloc` fails, `copy_unlocked` jumps to `error` and returns `-1`
**without ever assigning `cpy->impl`**. Back in `_blake2_blake2b_copy_impl`,
`Py_DECREF(cpy)` deallocates the half-built object → `py_blake2_dealloc` →
`py_blake2_clear`, which switches on the uninitialized `impl` and — for any of the
(overwhelmingly likely) garbage values outside the enum — hits `default: Py_UNREACHABLE()`:

```
Fatal Python error: py_blake2_clear: We've reached an unreachable state. ...
```

This is a genuine memory-safety bug, not a harmless assert: if the garbage `impl`
*happens* to match a valid enum case, `py_blake2_clear` instead calls
`Hacl_Hash_*_free()` on the correspondingly **uninitialized state pointer** — a free of
a wild pointer. On a release build `Py_UNREACHABLE()` is `__builtin_unreachable()`, so a
garbage `impl` is undefined behaviour (observed as a SIGSEGV on `release-ft-nojit`).

## Reproducer

Small and **deterministic** on a debug build, but **not stdlib-only**: the failing
allocation is HACL*'s raw `malloc()` for the copy's hash state, which
`_testcapi.set_nomemory` (a PyMem allocator hook) cannot intercept. The failure is
injected at the C `malloc` layer via an `LD_PRELOAD` shim (`fusil_malloc_shim.c` in
this directory — fusil's `--oom-foreign` injector; `fusil_malloc_arm(start, stop)` is a
drop-in for `set_nomemory`, failing allocations `[start, stop)`).

```console
$ cc -shared -fPIC -O2 -o shim.so fusil_malloc_shim.c -ldl
$ LD_PRELOAD=./shim.so <debug-python> repro.py
Fatal Python error: py_blake2_clear: We've reached an unreachable state. ...
Aborted (core dumped)
```

```python
import ctypes, faulthandler
faulthandler.enable()
import _blake2

lib = ctypes.CDLL(None)
lib.fusil_malloc_arm.argtypes = [ctypes.c_long, ctypes.c_long]

h = _blake2.blake2s(b"warmup")   # succeeds (unarmed)
lib.fusil_malloc_arm(0, 1)       # fail exactly the next malloc = the HACL state copy
h.copy()                         # boom
```

`arm(0, 1)` fails a single allocation, and the first `malloc` `copy()` makes *is* the
HACL state allocation, so the trigger is a 1-allocation window with no tuning.
`_blake2.blake2b` shares `_blake2_blake2b_copy_impl` and fails identically. **Needs a
non-ASan build** — under ASan the `LD_PRELOAD` shim is bypassed (ASan owns `malloc`), so
no failure is injected.

## Backtrace

```
Fatal Python error: py_blake2_clear: We've reached an unreachable state. ...

#8  py_blake2_clear (op=...)   Modules/blake2module.c:997   # default: Py_UNREACHABLE() -- reads uninitialised self->impl
#9  py_blake2_dealloc          Modules/blake2module.c:1008  # (void)py_blake2_clear(self)
#10 _Py_Dealloc               Objects/object.c:3319         # generic dealloc dispatch (detector)
#11 Py_DECREF (lineno=812)    Include/refcount.h:359        # inlined macro (detector)
#12 _blake2_blake2b_copy_impl Modules/blake2module.c:812    # Py_DECREF(cpy) after copy_unlocked failed  <-- SITE
#13 _blake2_blake2b_copy      Modules/clinic/blake2module.c.h:449
```

## Root cause

`new_Blake2Object` GC-tracks the object before its `impl`/state fields are initialized,
delegating initialization to each caller. `py_blake2_new` discharges that obligation
immediately (sets `impl`, NULL-inits states) *before* any fallible allocation, so its
error paths deallocate a well-formed-enough object. `blake2_blake2b_copy_unlocked` does
the fallible HACL allocation **first** and only sets `cpy->impl` on success
(`blake2module.c:781`), so its `error` path leaves `impl` uninitialized. The subsequent
`Py_DECREF(cpy)` (`blake2module.c:812`) reaches `py_blake2_clear`, whose `switch
(self->impl)` reads that uninitialized value → `Py_UNREACHABLE()` (debug) or UB /
wild-`free` (release).

The comment at `blake2module.c:967-970` already anticipates the "free only allocated
states" hazard and is why the *new* path NULL-inits states — but the copy path was not
given the same treatment, and the `impl` discriminant itself is never defended.

## Suggested fix

Initialize the copy's discriminant (and state pointers) **before** the fallible HACL
allocation, mirroring `py_blake2_new`. Minimal fix — in `_blake2_blake2b_copy_impl`
right after `new_Blake2Object`, or at the top of `blake2_blake2b_copy_unlocked`:

```c
cpy->impl = self->impl;
/* NULL-init the state pointer(s) for cpy->impl so py_blake2_clear is a no-op on error */
```

Then the error path deallocates an object with a valid `impl` and a NULL state →
`py_blake2_clear` frees nothing and returns cleanly. (Defensively, `new_Blake2Object`
could itself `impl`/NULL-init the whole struct, removing the per-caller obligation.)

## Notes

Found by **fusil** OOM-injection fuzzing — specifically the new **`--oom-foreign`** mode
(technique F), which injects `malloc`-layer failures via an `LD_PRELOAD` shim to reach
**foreign C-library allocations** that `_testcapi.set_nomemory` structurally cannot. This
is the **first catalog entry attributable to `--oom-foreign`**: HACL*'s BLAKE2 state is
allocated with raw `malloc`, so `set_nomemory` never fails it and the bug is unreachable
by the PyMem-hook harness. The vehicle was an `--oom-seq` sequence
`oc2:_blake2.blake2s[copy>...]` (fleet `fusil-fleet3` inst-01 session-134); the reduced
trigger is a single `.copy()` under a 1-allocation failure window.

Root cause is **fully pinned** (gdb-confirmed C chain on the debug build; the release
SIGSEGV is the same defect's latent-UB face). Distinct from the other uninitialized-read
entry OOM-0035 (StringIO `Py_UCS4` tail) — that is a missing buffer zero-fill read back by
`_PyUnicode_FromUCS4`; this is a missing discriminant init read back by a `tp_clear`
switch. No `_testcapi`-only repro exists; the shim (or any raw-`malloc` fault injector) is
required.

## Versions

- main (3.16.0a0), commit `1b9fe5c`. Repro matrix (non-ASan; ASan bypasses the shim):
  `debug-ft-nojit` / `debug-gil-nojit` / `debug-gil-jit` = **fatal** (deterministic
  `Py_UNREACHABLE` abort); `release-ft-nojit` = **latent UB** (one SIGSEGV observed,
  otherwise clean `MemoryError` — nondeterministic); `release-gil-nojit`/`jit` = latent
  UB (clean `MemoryError` this run). The clean, reliable signal is the debug abort.

---

*Filed upstream as [python/cpython#152851](https://github.com/python/cpython/issues/152851).*
