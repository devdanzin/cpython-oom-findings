# Use-after-free of an `os.DirEntry` `name` string under OOM (`DirEntry_dealloc`, `posixmodule.c:16199`)

*Walking a directory tree with `os.scandir` while allocations intermittently fail leaves an `os.DirEntry` whose `name` string has already been freed; the later `DirEntry_dealloc` `Py_XDECREF`s the dangling pointer — a `_Py_NegativeRefcount` abort on debug/JIT builds, and a **SIGSEGV on the release `upstream` build** (a latent use-after-free; the assert is compiled out under `NDEBUG`).*

_AI Disclaimer: this report was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Recursively scanning a directory tree with `os.scandir` under memory pressure ends with an
`os.DirEntry` whose `name` string has been freed prematurely. When that `DirEntry` is later
deallocated, `DirEntry_dealloc` runs `Py_XDECREF(entry->name)` on the dangling pointer:

```
_Py_NegativeRefcount        Objects/object.c:275            (generic negative-refcount detector)
  <- Py_XDECREF(entry->name)  in DirEntry_dealloc  (Modules/posixmodule.c:16199/16200)
     <- _Py_Dealloc of the DirEntry, while the `entries = list(os.scandir(d))` list /
        its holding (generator) frame is torn down
```

On the debug and JIT builds this trips the negative-refcount assert and aborts. On the
release `upstream` build the assert is compiled out, the `Py_XDECREF` of freed memory is
undefined behaviour, and the process **segfaults**. So this is a genuine memory-safety
use-after-free, not merely a debug-only assertion.

## Reproducer

Minimal, stdlib-only, **deterministic** on the ft_debug_asan build (GIL on and off, window 1
or fail-forever). `os.walk` was the original vehicle, but it reduces to a bare recursive
`os.scandir` — no `is_dir()`/`stat()` and no generator needed:

```python
import os
from _testcapi import set_nomemory, remove_mem_hooks

TREE = "/usr/share/zoneinfo"   # any directory tree with enough entries

def walk(top):
    stack = [top]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in entries:
            stack.append(e.path)   # recurse; os.scandir on a file just raises (caught)

walk(TREE)                              # warm-up (see Notes: avoids masking by OOM-0003)
for start in range(600):
    set_nomemory(start, start + 1)      # fail the allocation at #start, then resume
    try:
        try: walk(TREE)
        finally: remove_mem_hooks()
    except BaseException:
        pass
```

The **warm-up** `walk()` is load-bearing: without it, the far more common
`code_dealloc`/`_co_unique_id` crash ([OOM-0003]) fires first under OOM and masks this one.

## Backtrace

See `backtrace.txt`. The innermost meaningful frame is
`DirEntry_dealloc@Modules/posixmodule.c:16199` doing `Py_XDECREF(entry->name)`; under gdb
the negative-refcount object is freed memory (debug deadbyte `0xdd…`), confirming a UAF on
the `name` string.

## Root cause (PARTIAL)

**What is established:**

- The victim is a `DirEntry`'s `name` string (the first `Py_XDECREF` in `DirEntry_dealloc`),
  freed while the `DirEntry` still references it. Confirmed UAF: the object is in freed
  memory at the second decref.
- It is **`os.scandir`/`DirEntry`-specific**: a generic generator/recursion holding ordinary
  (non-`DirEntry`) objects under the same OOM sweep does **not** reproduce.
- It needs enough scandir churn (deep recursion) so the OOM sweep lands on the vulnerable
  allocation; it does **not** require `is_dir()`/`stat()` (the minimal repro touches only
  `.path` to recurse) nor a generator (a non-generator recursion reproduces too).

**What was ruled out** (by source inspection): `DirEntry_from_posix_info` (clean: NULL-inits
all fields, single `Py_XDECREF(entry)` on the error path), `ScandirIterator_iternext`
(returns the owned entry, no over-decref), and `DirEntry_fetch_stat`/`path_object_error`
(do not touch `self->name`/`self->path` refs — and aren't even called in the minimal repro).

**What is open:** the exact producer — where `entry->name` loses a reference under
allocation failure. Notably, a conditional breakpoint on `unicode_dealloc` for the specific
freed string never fired, and a hardware refcount watchpoint on it never tripped (it is
invalidated by the OOM allocator's arena churn on this `--without-pymalloc` ASan build),
which hints the string's memory is reclaimed via an arena/aliasing path rather than a plain
`Py_DECREF`. Pinning it cleanly needs ASan's free-stack (a `--with-pymalloc` + ASan build, so
`PYTHONMALLOC=malloc` routes frees through ASan) or `rr` reverse execution — neither was
available on the triage host.

## Suggested fix

Audit the `os.scandir`/`DirEntry` `name`/`path` reference handling on allocation-failure
paths: a reference to the `name` string is dropped one too many times (or its storage is
reclaimed) while the owning `DirEntry` is still live and reachable from the `entries` list.
A NULL-out-before-free / save-and-restore discipline on the `DirEntry` string fields under
OOM should close it. (Exact site to be confirmed once the producer is pinned.)

## Notes

Found by the new **OOM Phase-4 stateful sequences** (`--oom-seq`) fleet, vehicle
`zoneinfo._tzpath` (`inst-01 python-6 zoneinfo__tzpath-assertion-sigabrt-oomNEW`). This is a
crash the single-call fail-forever harness could not reach: it always trips the shallow
[OOM-0003] (`code_dealloc`) first, whereas the windowed sequence runs *past* that shallow
crash (the preceding sequence step warms the code objects) to reach this deeper UAF.

Build matrix: `ft_debug_asan` abort (negrefcount), `jit` abort, `ft_release` no-crash (UAF
latent, did not manifest), **`upstream` SIGSEGV** (release UAF).

Distinct from [OOM-0005] (a generic frame-stack `PyStackRef_XCLOSE` over-close of a
`MemoryError` on a *thread* frame): a generic non-`DirEntry` recursion does not reproduce
this, so it is not the same frame-clear root — it is specific to `os.DirEntry` string
lifetime under OOM. They share only the generic `_Py_NegativeRefcount` detector frame.

Dedup: the discriminative key is `DirEntry_dealloc@Modules/posixmodule.c:16199` (the
in-loop deduper resolves to it after skipping the generic `refcount.h`/`object.c:275`
detector frames); the negative-refcount detector frames are intentionally not keyed.

Root cause PARTIAL — see above.
