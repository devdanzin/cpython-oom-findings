# Use-after-free of an `os.DirEntry` string under OOM (eval-loop stackref over-close; `DirEntry_dealloc`, `posixmodule.c:16199`)

*Under OOM the eval loop's `exception_unwind` (`generated_cases.c.h:13853`) over-closes a value-stack reference to a live `os.DirEntry`'s `path` string, freeing it while `entry->path` still points to it; the later `DirEntry_dealloc` `Py_XDECREF`s the dangling pointer — a `_Py_NegativeRefcount` abort on debug/JIT builds, and a **SIGSEGV on the release `upstream` build** (the assert is compiled out under `NDEBUG`).*

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

## Root cause

Pinned with ASan on a `--with-pymalloc` build run under `PYTHONMALLOC=malloc` (so frees go
through ASan's allocator, which then reports the use-after-free **with the free stack**):

- **Allocated (the victim):** the freed object is a `DirEntry`'s `path` string, created by
  `PyUnicode_DecodeFSDefault` in `DirEntry_from_posix_info` (`posixmodule.c:16747`) while
  building `list(os.scandir(d))` (`ScandirIterator_iternext:16923` → `list_extend`).
- **Freed (the bug):** when the OOM `MemoryError` is **not** handled in the current frame,
  the eval loop's `exception_unwind` handler pops and `PyStackRef_XCLOSE`s **every**
  value-stack slot:
  ```c
  // Python/generated_cases.c.h:13853 (exception_unwind, handled == 0)
  _PyStackRef *stackbase = _PyFrame_Stackbase(frame);
  while (frame->stackpointer > stackbase) {
      _PyStackRef ref = _PyFrame_StackPop(frame);
      PyStackRef_XCLOSE(ref);          // :13857 — closes a ref to the live DirEntry string
  }
  ```
  One of those slots references the live `DirEntry`'s `path` string, so closing it drops the
  string to refcount 0 and frees it — even though `entry->path` still points to it.
- **Use-after-free:** later, when the `entries` list (and the frame holding it) is torn
  down, `DirEntry_dealloc` runs `Py_XDECREF(entry->path)` on the dangling pointer →
  `_Py_NegativeRefcount` (debug/JIT) or SIGSEGV (release).

This is **not** a `posixmodule` refcount bug: `DirEntry.name`/`.path` are `Py_T_OBJECT_EX`
members and `__fspath__` uses `Py_NewRef`, so `e.path` yields a properly *owned* reference;
`DirEntry_from_posix_info`/`ScandirIterator_iternext`/`DirEntry_fetch_stat` are all clean.
It is an **eval-loop stackref-lifetime bug**: under OOM unwind, a value-stack slot holding a
reference to the `DirEntry` string is over-closed (an effectively unbacked / double-owned
stackref — consistent with the stack spill/reload machinery, cf. GH-150516). `os.DirEntry`
is only the victim that happens to be on the value stack when the `MemoryError` unwinds; a
generic non-`DirEntry` recursion didn't reproduce only because it didn't leave such a slot
exposed at the unwind.

**Relationship to [OOM-0005]:** same class — a `PyStackRef_XCLOSE` over-close of a
value-stack reference under OOM — but a distinct site (`exception_unwind`'s value-stack pop
here vs `_PyFrame_ClearLocals` there) and a distinct, independently-reproducible trigger
(an `os.DirEntry` string vs a `MemoryError`). Possibly the same underlying stackref bug;
catalogued separately pending confirmation.

**Residual:** the exact push/spill that leaves the value-stack slot unbacked is not pinned
to a line — that needs reverse execution. `rr` is installed but was blocked on the triage
host by `kernel.perf_event_paranoid = 4` (lower it with `sudo sysctl
kernel.perf_event_paranoid=3`); with `rr`, a refcount watchpoint reverse-continued from the
crash would identify the missing-incref/duplicate directly.

## Suggested fix

The fix is in the eval loop's stackref accounting, not `os.scandir`: a value-stack reference
to a live object is over-closed during `exception_unwind` under OOM. Audit the stack
spill/reload paths so value-stack slots are never double-owned / borrowed-as-owned across
operations that can raise `MemoryError` (this likely shares a root with [OOM-0005]).
`os.DirEntry` is incidental — any object on the value stack at the wrong moment under OOM is
exposed.

## Notes

Found by the new **OOM Phase-4 stateful sequences** (`--oom-seq`) fleet, vehicle
`zoneinfo._tzpath` (`inst-01 python-6 zoneinfo__tzpath-assertion-sigabrt-oomNEW`). This is a
crash the single-call fail-forever harness could not reach: it always trips the shallow
[OOM-0003] (`code_dealloc`) first, whereas the windowed sequence runs *past* that shallow
crash (the preceding sequence step warms the code objects) to reach this deeper UAF.

Build matrix: `ft_debug_asan` abort (negrefcount), `jit` abort, `ft_release` no-crash (UAF
latent, did not manifest), **`upstream` SIGSEGV** (release UAF).

See *Root cause* for the relationship to [OOM-0005] (same `PyStackRef_XCLOSE`-over-close
class, distinct site/trigger, possibly the same underlying eval-loop stackref bug).

Dedup: the discriminative key is `DirEntry_dealloc@Modules/posixmodule.c:16199` (the
in-loop deduper resolves to it after skipping the generic `refcount.h`/`object.c:275`
detector frames; the `exception_unwind` over-close frame is too generic to key on).

Root cause: producer pinned to the eval-loop `exception_unwind` value-stack over-close (ASan
free-stack); one residual detail (the unbacked-slot origin) needs `rr` — see above.
