# Double-free / use-after-free: `list.append(x)` under OOM double-frees the item (`_CALL_LIST_APPEND` steals `arg`, then `ERROR_NO_POP`)

*When `list.append`'s grow (`list_resize`) fails under OOM, `_PyList_AppendTakeRef` has already consumed the item's reference (it decrefs it on failure), but the specialized `_CALL_LIST_APPEND` bytecode takes `ERROR_NO_POP()`, leaving the stolen `arg` stackref on the value stack; the eval loop's `exception_unwind` then `PyStackRef_XCLOSE`s it — decreffing the item a second time. If the item is referenced elsewhere this is a use-after-free: `_Py_NegativeRefcount` abort on debug/JIT, **SIGSEGV on the release `upstream` build**.*

_AI Disclaimer: this report was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Appending a still-referenced object to a `list` while allocations are failing double-frees
the object. The original fleet vehicle was `os.scandir` recursion (`stack.append(e.path)`,
with the `DirEntry` holding `entry->path`), but the bug is generic and reproduces in pure
Python with any object that holds a second reference to the appended item.

## Reproducer

Minimal, stdlib-only, **deterministic** on the debug build (GIL on and off); pure Python,
no filesystem:

```python
from _testcapi import set_nomemory, remove_mem_hooks

class E:
    __slots__ = ("a",)
    def __init__(self, a): self.a = a

def f():
    items = [E(str(i) + "_value") for i in range(200)]   # E.a holds the only other ref to the str
    out = []
    for e in items:
        out.append(e.a)             # CALL_LIST_APPEND; under OOM the grow fails -> double-free of e.a

f()                                  # warm-up: specialize CALL_LIST_APPEND (+ build code objects)
for start in range(1500):
    set_nomemory(start, start + 1)   # fail one allocation at #start, then resume
    try:
        try: f()
        finally: remove_mem_hooks()
    except BaseException: pass
```

The warm-up `f()` is load-bearing: it specializes `out.append(e.a)` to `CALL_LIST_APPEND`
(the bug is in that specialized form) and builds the code objects so the much more common
`code_dealloc` crash ([OOM-0003]) doesn't fire first and mask this one.

## Natural trigger (no `_testcapi`)

`_CALL_LIST_APPEND`'s only error path is `list_resize` failing, which happens **only** on a
genuine allocation failure — `set_nomemory` just makes it deterministic. So the bug is
reachable under real memory pressure: a program that does `list.append(obj)` (with `obj`
referenced elsewhere) while the list's grow allocation returns NULL gets a double-free / UAF
**instead of a recoverable `MemoryError`**.

Demonstrated with a real `RLIMIT_AS` address-space cap and no test API (`repro_natural.py`,
run on a non-ASan release build):

```
$ PYTHON_GIL=1 ./python repro_natural.py
Segmentation fault            # 3/3; faulthandler pins it to the `out.append(x)` line
```

Control: under the **same** cap, when the failing allocation is *not* a list-append grow
(e.g. appending large `bytes`), Python raises a clean, catchable `MemoryError` and does not
crash. So the segfault is specific to the buggy append path, not an `RLIMIT_AS` artifact.

## Root cause

In the specialized append bytecode `_CALL_LIST_APPEND` (`Python/bytecodes.c`):

```c
op(_CALL_LIST_APPEND, (callable, self, arg -- none, c, s)) {
    ...
    int err = _PyList_AppendTakeRef((PyListObject *)self_o, PyStackRef_AsPyObjectSteal(arg));
    UNLOCK_OBJECT(self_o);
    if (err) {
        ERROR_NO_POP();          // <-- bug: arg already consumed, but left on the value stack
    }
    ...
}
```

1. `PyStackRef_AsPyObjectSteal(arg)` **steals** the item's reference out of the `arg`
   stackref and hands it to `_PyList_AppendTakeRef`.
2. `_PyList_AppendTakeRef` **consumes the reference on every path**: on the grow path,
   `_PyList_AppendTakeRefListResize` does `if (list_resize(...) < 0) { Py_DECREF(newitem);
   return -1; }` (`Objects/listobject.c:531`). Under OOM the resize fails, so the item is
   decreffed here.
3. The uop then takes `ERROR_NO_POP()` — which jumps to error handling **without removing
   `arg` from the value stack**. But `arg`'s reference was already consumed in step 2.
4. The eval loop's `exception_unwind` pops the frame's value stack and `PyStackRef_XCLOSE`s
   every slot (`Python/generated_cases.c.h:13853-13857`), including the stale `arg` slot —
   decreffing the item a **second** time.

Net: the appended item is decreffed twice for one reference → **double-free**. When the item
has another live owner (the `E.a` slot above; `entry->path` in the scandir vehicle), that
owner is left dangling and the next decref of it is a use-after-free, detected as
`_Py_NegativeRefcount` (debug/JIT) or a SIGSEGV (release).

Confirmed from four independent angles: the ASan free-stack (a `--with-pymalloc` build under
`PYTHONMALLOC=malloc`) shows the item freed by `PyStackRef_XCLOSE` ← `exception_unwind`; the
`listobject.c` source shows the decref-on-resize-failure; the disassembly shows
`out.append(e.a)` specializes to `CALL_LIST_APPEND`; and a control (load `e.a` but don't
append) does **not** crash.

## Suggested fix

`_CALL_LIST_APPEND` must account for the consumed `arg` on the error path — once
`_PyList_AppendTakeRef` has taken the reference, `arg`'s stackref is dead and must not be left
on the value stack for `exception_unwind` to close. The sibling ops show the two correct
idioms: the comprehension adds (`LIST_APPEND`/`SET_ADD`/`MAP_ADD`) use `ERROR_IF(...)` so the
codegen drops the consumed input; the consuming call ops (`_DO_CALL_FUNCTION_EX`,
`_PY_FRAME_EX`) call `INPUTS_DEAD(); SYNC_SP();` before `ERROR_NO_POP()`.

## Audit (is this the only one?)

Scanned all 440 ops in `Python/bytecodes.c` for the same shape — steal a stack input **and**
take a bare `ERROR_NO_POP()`. `_CALL_LIST_APPEND` is the **only** affected op:

- `_DO_CALL_FUNCTION_EX`, `_PY_FRAME_EX` — steal callargs/kwargs but call
  `INPUTS_DEAD(); SYNC_SP();` before `ERROR_NO_POP()` → the unwind skips the consumed slots. Safe.
- `DELETE_DEREF` — false positive: its `PyCell_SwapTakeRef` is on a cell's contents, not a
  value-stack input (stack effect `(--)`). Safe.
- the comprehension adds (`LIST_APPEND`/`SET_ADD`/`MAP_ADD`) and `STORE_SUBSCR_DICT` steal
  inputs but use the codegen-accounted `ERROR_IF`/`goto pop_N_error`. Safe — confirmed
  empirically: `[e.a for e in items]` (`LIST_APPEND`, the *same* `_PyList_AppendTakeRef`
  helper) does **not** crash under the OOM sweep, whereas `out.append(e.a)`
  (`_CALL_LIST_APPEND`) does.

So the defect is specifically the bare `ERROR_NO_POP()` after a steal, with neither the
codegen accounting nor `INPUTS_DEAD()/SYNC_SP()`. Related to [OOM-0005] — a sibling
eval-loop stackref over-close under OOM, same `PyStackRef_XCLOSE` closer family but a
different inconsistency source/site (the value-stack over-close fires whenever the stack is
left inconsistent at unwind; here the source is the consumed-but-unpopped `arg`).

## Backtrace

See `backtrace.txt` for the ASan use-after-free report (allocated-by / freed-by / use
stacks) and the bytecode evidence. The crash *site* depends on which holder is left dangling
(`DirEntry_dealloc` in the scandir vehicle; `clear_slots`/`subtype_dealloc` in the
`__slots__` repro), but the producer is always `exception_unwind`'s value-stack
`PyStackRef_XCLOSE` after the `_CALL_LIST_APPEND` double-consume.

## Notes

Found by the OOM Phase-4 stateful sequences (`--oom-seq`) fleet, vehicle `zoneinfo._tzpath`
(`stack.append(e.path)` inside `available_timezones`'s `os.walk`). A crash the single-call
fail-forever harness could not reach: it trips the shallow [OOM-0003] first; the windowed
sequence runs past it. Originally filed as an `os.scandir`/`DirEntry` UAF (root-partial),
then root-caused to this generic `list.append`-under-OOM double-free and reduced to the
pure-Python repro above.

Build matrix (identical for the scandir and pure-Python repros): `ft_debug_asan` abort,
`jit` abort, `ft_release` no-crash, **`upstream` SIGSEGV** (real memory-safety bug).

Dedup: the fleet vehicle keys on `DirEntry_dealloc@Modules/posixmodule.c:16199`; note this is
generic, so other victims (other holders of the appended item) will surface at different
dealloc sites and won't auto-dedupe to this entry.

Strong, self-contained upstream candidate (tiny pure-Python repro, release-crashing,
one-spot fix in `_CALL_LIST_APPEND`).
