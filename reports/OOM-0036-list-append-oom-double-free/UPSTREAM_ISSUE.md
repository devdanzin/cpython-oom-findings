<!-- DRAFT CPython issue for OOM-0036. Title goes in the GitHub title field; body below. -->

# Title

Double free / use-after-free in `list.append()` when the list grows under `MemoryError` (`_CALL_LIST_APPEND`)

# Body

## Bug report

When `list.append(x)` has to grow the list's backing array and that allocation fails (i.e.
under `MemoryError`), the appended item `x` is decref'd **twice**. If `x` is referenced
elsewhere this is a use-after-free: the interpreter aborts with `_Py_NegativeRefcount` on a
debug build, or **segfaults** on a release build, instead of raising a recoverable
`MemoryError`.

This is reachable under genuine memory pressure (a real `RLIMIT_AS` reproducer with no test
API is included below), so a program that correctly catches `MemoryError` can still be left
with a corrupted interpreter.

### Reproducer

Deterministic, pure Python, using `_testcapi.set_nomemory` to fail the grow allocation at a
controlled point:

```python
import _testcapi

class C:
    __slots__ = ("ref",)
    def __init__(self, ref):
        self.ref = ref

def fill():
    items = [C(str(i) + "_unique") for i in range(200)]
    out = []
    for it in items:
        out.append(it.ref)          # CALL_LIST_APPEND; it.ref is also held by the C instance

fill()                              # warm up: specialize out.append(...) to CALL_LIST_APPEND
for start in range(1500):
    _testcapi.set_nomemory(start, start + 1)   # fail one allocation, then resume
    try:
        try:
            fill()
        finally:
            _testcapi.remove_mem_hooks()
    except BaseException:
        pass
```

On a `--with-pydebug` build this aborts:

```
./Include/refcount.h:520: _Py_NegativeRefcount: Assertion failed: object has negative ref count
Fatal Python error: _PyObject_AssertFailed
```

On a release build it segfaults.

### Without any test API (real `MemoryError`)

The same double-free fires under a genuine allocation failure. With an `RLIMIT_AS` cap so the
list's grow allocation returns NULL naturally (run on a non-ASan build):

```python
import resource

pool = [object() for _ in range(8_000_000)]      # uniquely-referenced items, built before the cap
warm = []
for i in range(3000):
    warm.append(pool[i])                          # specialize CALL_LIST_APPEND
del warm

cur = int(open("/proc/self/statm").read().split()[0]) * 4096   # current virtual size
resource.setrlimit(resource.RLIMIT_AS, (cur + 24 * 1024 * 1024,) * 2)

out = []
for x in pool:
    out.append(x)                                 # real list_resize failure -> double-free -> SIGSEGV
```

```
$ ./python natural.py
Segmentation fault            # faulthandler pins the crash to the `out.append(x)` line
```

Under the same cap, when the failing allocation is *not* a list-append grow (e.g. appending
large `bytes`), Python raises a clean, catchable `MemoryError` and does not crash — so the
segfault is specific to the buggy append path.

## Root cause

In the specialized append bytecode `_CALL_LIST_APPEND` (`Python/bytecodes.c`):

```c
op(_CALL_LIST_APPEND, (callable, self, arg -- none, c, s)) {
    ...
    int err = _PyList_AppendTakeRef((PyListObject *)self_o, PyStackRef_AsPyObjectSteal(arg));
    UNLOCK_OBJECT(self_o);
    if (err) {
        ERROR_NO_POP();
    }
    ...
}
```

`arg` is **stolen** via `PyStackRef_AsPyObjectSteal` and handed to `_PyList_AppendTakeRef`,
which consumes the reference on every path — including decref'ing the item when the grow
fails (`_PyList_AppendTakeRefListResize` → `if (list_resize(...) < 0) { Py_DECREF(newitem);
return -1; }`, `Objects/listobject.c`).

But on that failure the uop takes `ERROR_NO_POP()`, which jumps to exception handling
**without removing `arg` from the value stack**. Since `arg`'s reference was already
consumed, the stale `arg` stackref is now dangling. The eval loop's `exception_unwind` then
pops the frame's value stack and `PyStackRef_XCLOSE`s every slot, closing the stale `arg`
slot — a **second** decref of the item.

(Confirmed with ASan on a `--with-pymalloc` build: the item is freed by `PyStackRef_XCLOSE`
← `_PyEval_EvalFrameDefault` (the `exception_unwind` handler); both the item's allocation and
the second, use-after-free decref are visible in the report.)

## Suggested fix

`_CALL_LIST_APPEND` must account for the consumed `arg` on the error path — once
`_PyList_AppendTakeRef` has taken the reference, the `arg` stackref is dead and must not be
left on the value stack for `exception_unwind` to close. The sibling ops already show the two
correct idioms:

- the comprehension element-adds (`LIST_APPEND`, `SET_ADD`, `MAP_ADD`) call the same kind of
  steal/`*TakeRef` helper but use `ERROR_IF(...)`, so the codegen drops the consumed input on
  the error path. Concretely, `[x for x in ...]` (`LIST_APPEND`, the *same*
  `_PyList_AppendTakeRef` helper) does **not** crash where `lst.append(x)`
  (`_CALL_LIST_APPEND`) does;
- the consuming call ops (`_DO_CALL_FUNCTION_EX`, `_PY_FRAME_EX`) call `INPUTS_DEAD();
  SYNC_SP();` before `ERROR_NO_POP()`.

I audited the other specialized ops: `_CALL_LIST_APPEND` is the only one that steals a
stack input and then takes a bare `ERROR_NO_POP()` without either form of accounting, which
is why it is the lone op affected.

## Your environment

- CPython `main` (3.16.0a0); reproduced on `--with-pydebug` builds (abort) and release builds
  (segfault), both free-threaded and default GIL.
- Linux, x86-64.

---

*This report and the reduced reproducers were drafted with the assistance of Claude Code; I
have reviewed and reproduced them.*
