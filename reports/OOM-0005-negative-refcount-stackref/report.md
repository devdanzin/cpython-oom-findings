# Abort: negative-refcount over-decref in `_PyFrame_ClearLocals` (`frame.c:101`)

*An OOM opcode error path leaves a stale, already-dead `_PyStackRef` on the value stack; during exception unwinding `_PyFrame_ClearLocals` calls `PyStackRef_XCLOSE` on it, driving a `MemoryError` instance's refcount below zero — a latent use-after-free on release builds where the assert is compiled out.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

When an allocation fails (`MemoryError`) in the middle of a bytecode instruction, the eval loop unwinds the frame through its `exit_unwind` label, which clears the frame's operand stack via `_PyFrame_ClearLocals()`. Under OOM, an opcode error path has left a stale / already-dead `_PyStackRef` on the value stack, so closing it (`PyStackRef_XCLOSE` -> `Py_DECREF_MORTAL`) drives the referenced object's refcount below zero. On the debug build this aborts with `_Py_NegativeRefcount: "object has negative ref count"`; on release builds the assert is compiled out, so the underflow would free a still-live object — a latent use-after-free hazard. The over-decref'd object is a `MemoryError` instance.

This is a genuine refcount-underflow / memory-safety bug, not merely a debug assertion. It is confirmed deterministically on the `ft_debug_asan` build by the minimal `xml.dom.minidom` reproducer below (10/10). The OOM sweep also trips several *other* distinct latent bugs, so other vehicles that produce a similar negative-refcount abort are listed only as *possibly related* (not individually confirmed to share this exact site — see Notes).

## rr investigation (2026-06-24) — the two repros have DIFFERENT producers

`frame.c:101` (`_PyFrame_ClearLocals` → `PyStackRef_XCLOSE`) is a **detector** — it closes a stale
stackref that an *upstream* error path left on the value stack. `rr` reverse-execution (record the
crash, watchpoint the victim's refcount, `reverse-continue` through its history) shows this report's
two reproducers are driven by **two different upstream producers**:

- **`repro.py` (`xml.dom.minidom.parse(0)`) → this is actually [OOM-0036](../OOM-0036-list-append-oom-double-free/report.md).**
  The victim's refcount history is: `PyStackRef_DUP` (+1) → **`_PyList_AppendTakeRefListResize`
  (`listobject.c:531`, from `_CALL_LIST_APPEND`, gen 3981)** decrefs it on resize-failure (−1) →
  `exception_unwind` `XCLOSE` frees it (−1) → `_PyFrame_ClearLocals` `XCLOSE` underflows it (negref).
  That is exactly OOM-0036's `list.append`-under-`MemoryError` double-free (`_CALL_LIST_APPEND` steals
  the item then `ERROR_NO_POP` leaves it on the stack). **So this "minimal repro" demonstrates OOM-0036,
  not OOM-0005's distinct defect** — a mislabel to fix (the gist's minimal repro is affected; see Notes).

- **`repro_uaf.py` (`pkgutil.get_importer(str)`) → a genuinely distinct over-decref.** No `list.append`
  is involved. The `str` argument is threaded through many references (the holding dict, several call
  frames' args/locals, the raised `OSError`'s fields, an args tuple); under the OOM unwind a dealloc
  *cascade* — `_PyFrame_ClearLocals`×N, `OSError_clear`/`OSError_dealloc` (`exceptions.c:2312`),
  `tuple_dealloc`, `frame_dealloc` — decrefs it **one time too many**, freeing it while the dict still
  holds it → use-after-free (the later `_Py_dict_lookup_threadsafe` / `PyOS_FSPath` touch freed memory).
  This is OOM-0005's real, distinct bug; the single missing-incref in the cascade was not isolated to
  one line, but it is clearly **not** the `_CALL_LIST_APPEND` path.

The over-decref'd **object type varies by run** (the original discovery capture: a `MemoryError`; both
rr-traced repros above: a `str`) — consistent with "whatever stale value the error path left on the
stack," so the victim type is not itself diagnostic. **Net:** OOM-0005 remains a real distinct bug
(the `repro_uaf.py` cascade), but `repro.py` should be replaced — it is an OOM-0036 reproducer.

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the `xml.dom.minidom` vehicle, then
hand-cleaned). Deterministic — aborts on every run (20/20 with `PYTHON_GIL=1`, 8/8 with
`PYTHON_GIL=0`); requires a debug build. See `repro.py`:

```python
import xml.dom.minidom
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(100):
    set_nomemory(start, 0)
    try:
        try:
            xml.dom.minidom.parse(0)
        finally:
            remove_mem_hooks()
    except:
        pass
```

`xml.dom.minidom.parse(0)` fails with `MemoryError` partway through under the sweep; the
exception unwinds a frame whose operand stack still holds a now-dead stackref, and
`_PyFrame_ClearLocals` closes it -> refcount underflow on the `MemoryError` instance.

shrinkray reduced the 511-line vehicle but could not delete the fuzzer's `weird_classes`
setup because the final call's argument referenced it; substituting a trivial argument (`0`)
freed that setup for removal. Unlike the older multiprocessing.spawn/runpy reduction — which
tripped a *sibling* `code_dealloc` assert first (hence the previous "partial" status, see
Notes) — the `xml.dom.minidom` path deterministically hits *this* stackref underflow.
Minimization **complete**.

## Backtrace

```
#9  _Py_NegativeRefcount        Objects/object.c:275       (op = a MemoryError, refcount underflowed)
#10 Py_DECREF_MORTAL            Include/refcount.h (BITS_TO_PTR(ref))
#11 PyStackRef_XCLOSE           Include/internal/pycore_stackref.h:726
#12 _PyFrame_ClearLocals        Python/frame.c:101         (while (sp > locals) PyStackRef_XCLOSE(*sp))
#13 _PyFrame_ClearExceptCode    Python/frame.c:126
#14 clear_thread_frame          Python/ceval.c:1954
#15 _PyEval_EvalFrameDefault    Python/generated_cases.c.h:13908   (LABEL exit_unwind -> _PyEval_FrameClearAndPop)
```

Fatal dump: `object type name: MemoryError`. The minimal `xml.dom.minidom` repro hits frames #11-#15 deterministically (10/10) on `ft_debug_asan`. Several other OOM vehicles (multiprocessing_spawn, _pyrepl_main, importlib_resources, zoneinfo__tzpath, …) produce a *similar* negative-refcount abort, but were not individually re-confirmed to share this exact stackref-close site on the current binary — and the originally-headlined `concurrent_futures_process` vehicle actually hits a **different** `list_dealloc` segv (see Notes), so the "single group" framing is not relied on here.

## Root cause

`Python/frame.c`, `_PyFrame_ClearLocals` (L92):

```c
void
_PyFrame_ClearLocals(_PyInterpreterFrame *frame)
{
    assert(frame->stackpointer != NULL);
    _PyStackRef *sp = frame->stackpointer;
    _PyStackRef *locals = frame->localsplus;
    frame->stackpointer = locals;
    while (sp > locals) {
        sp--;
        PyStackRef_XCLOSE(*sp);     /* L101: closes every live operand-stack slot */
    }
    Py_CLEAR(frame->f_locals);
}
```

This is correct *only if* `frame->stackpointer` accurately reflects the set of operand-stack slots the frame still owns. The bug is upstream of here: an opcode that can fail under allocation pressure took an error exit *after* it had already consumed (closed / stolen via `PyStackRef_*Steal`) a stack value but *before* it removed that slot from the stack pointer -- or it pushed a borrowed reference that it doesn't own. The dead/stale `_PyStackRef` is then left on the value stack. When `MemoryError` unwinds the frame (`exit_unwind` -> `_PyEval_FrameClearAndPop` -> `clear_thread_frame` -> `_PyFrame_ClearExceptCode` -> `_PyFrame_ClearLocals`), that slot is closed and the object's refcount underflows:

- debug (`Py_REF_DEBUG`): `Py_DECREF` detects refcount < 0 -> `_Py_NegativeRefcount` (`Objects/object.c:275`) -> `_PyObject_AssertFailed` -> abort.
- release: no check; the object is freed while still referenced elsewhere -> use-after-free segfault later.

The MemoryError itself being the over-decref'd object suggests the offending opcode is one that puts the just-raised exception (or a value derived alongside it) onto the stack and mishandles its ownership on the error path (CALL/`*_VECTORCALL` steal paths, `BINARY_OP`, `BUILD_*`, or the `FOR_ITER`/`SEND`/`CLEANUP_THROW` family), or one of the generated `pop_N_error:` / `error:` exit stubs miscounting the live stack depth.

## Use-after-free face (confirmed 2026-06-22)

The "latent use-after-free" predicted above is now **directly demonstrated**, not just inferred.
When the over-decref'd local is *also* referenced elsewhere, the underflow frees it while it is
still live, and a later access touches freed memory. `repro_uaf.py` (shrinkray-reduced from a
`pkgutil` fuzzing vehicle) threads a heap `str` through
`pkgutil.get_importer(s) -> os.fsdecode(s) -> os.fspath(s)` while keeping a second reference to
it in a dict:

- **debug-gil-nojit-asan**: ASan reports a clean `heap-use-after-free`. Its *freed-by* stack is
  this exact over-decref — `PyStackRef_XCLOSE` (`stackref.h:726`) <- `_PyFrame_ClearLocals`
  (`frame.c:101`), `exit_unwind` — the *read* is a later `Py_INCREF` via a dict lookup, and the
  *allocated-by* is the victim `str(0)`. So the bug is **not** free-threading-specific and **not**
  assert-only.
- **debug-ft-nojit-asan**: the same freed local is instead used by `PyOS_FSPath`
  (`posixmodule.c:17168`) -> `PyType_HasFeature` reads `Py_TYPE(path)->tp_flags` on the freed
  object (`ob_type == 0xdd`, the debug freed-fill) -> SIGSEGV.

See `repro_uaf.py` and `backtrace_uaf.txt`. This pins the memory-safety hazard to *this* site (a
genuine UAF reachable through ordinary stdlib such as `pkgutil.get_importer`), upgrading the
release behaviour from "latent / not pinned" to a demonstrated use-after-free. Which downstream
*use* faults (dict-lookup `Py_INCREF` vs `os.fspath` type read) depends on build/timing — the
defect is the single `_PyFrame_ClearLocals` over-decref, not any particular use site.

## Suggested fix

Audit the bytecode-handler error/cleanup paths (and the generated `pop_N_error:` / `error:` stubs in `Python/bytecodes.c` / `generated_cases.c.h`) so that on any allocation-failure exit, `frame->stackpointer` exactly matches the set of still-owned stackrefs: every consumed/stolen value must be popped, every leftover value must remain owned. The fix is in the opcode that leaks the stale ref, not in `_PyFrame_ClearLocals` (which must trust the stack pointer). As a debugging aid, the stack-effect invariants could be asserted on the error path before `_PyEval_FrameClearAndPop`.

## Notes

- Found by OOM-injection fuzzing (`_testcapi.set_nomemory`). Largest group in `python-4`.
- **Build matrix (minimal repro):** `ft_debug_asan` -> **abort** (negative-refcount assert; 10/10). On the release builds (`ft_release`, `upstream`) the assert is compiled out (`NDEBUG`), so the underflow is a latent use-after-free hazard — but the minimal repro does **not** deterministically segv at this site there (it exits cleanly), so the exact release fault is **not pinned** to this site; recorded `n/a`. `jit` (also a debug build) does not hit this stackref path with the minimal repro either (a different OOM allocation fails first) -> `n/a`. Only the `ft_debug_asan` abort is solidly confirmed as *this* bug.
- **The OOM sweep trips several distinct latent bugs across builds** — so other vehicles are *possibly related*, not individually confirmed. Concretely, the `concurrent_futures_process` vehicle (a "segfault" vehicle) on `ft_debug_asan` deterministically (8/8) hits a **different** `list_dealloc` heap-corruption segv (via `unicode.split` -> `PyList_New`), **not** this negative-refcount assert; an earlier draft incorrectly claimed it as confirmed in this group. The release/upstream segvs of the minimal repro likewise resolve (under gdb) to unrelated OOM sites (`weakref___new__`/`PyArg_UnpackTuple`, `PyType_HasFeature`/`tuple_alloc`), not the `_PyFrame_ClearLocals` stackref path.
- **Sibling bug spotted during minimization:** under the same OOM sweep, `runpy.run_path()` / `spawn._fixup_main_from_path()` can instead abort at `Objects/codeobject.c:2440` (`_co_unique_id == _Py_INVALID_UNIQUE_ID` in `code_dealloc`) -- a *different* over-free during code-object teardown under OOM, likely worth a separate id.

## Versions

- main (3.16.0a0), commit 15d7406. Confirmed on free-threaded debug+ASan (abort, 10/10 via the minimal repro). On the release builds (`ft_release`, `upstream`) the assert is compiled out — a latent use-after-free, but the minimal repro does not pin a segv at this site there. The `jit` build does not reach this stackref path with the minimal repro.

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking 35 OOM-related crash findings.*
