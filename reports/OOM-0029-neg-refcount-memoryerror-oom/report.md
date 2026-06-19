# Abort: negative refcount on a `MemoryError` (`tuple_dealloc`, `tupleobject.c:277`)

*A `_pyrepl.utils.disp_str` OOM path over-decrefs a `MemoryError`; `_Py_NegativeRefcount` fires later when that item is freed in a `list`->`subtype`->`tuple` dealloc cascade.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Under memory pressure a `MemoryError` instance is decref'd one time too many (its
refcount goes negative). The corruption is detected later — when an unrelated object
graph is torn down (`list_dealloc` → `subtype_dealloc` → `tuple_dealloc`) and that
already-broken `MemoryError` is `Py_DECREF`'d again — by `_Py_NegativeRefcount`
(`object.c:275`), which aborts (`_PyObject_AssertFailed`, debug builds). The
deallocation cascade is **incidental**: it is only where the bad refcount is next
touched, not where the unbalanced decref happened.

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the `_pyrepl.utils` vehicle). **Deterministic**
— aborts on every run (30/30); requires a debug build (`PYTHON_GIL=1`):

```python
import _pyrepl.utils
from _testcapi import set_nomemory

for start in range(150):
    set_nomemory(start, 0)
    try:
        _pyrepl.utils.disp_str("\x004\x8A\xD5\x03")
    except MemoryError:
        pass
```

`disp_str` computes display widths; the argument is **load-bearing** — it mixes NUL/control
bytes and high bytes (`\x00 4 \x8a \xd5 \x03`), exercising the control-char / wide-char path.
Every simpler argument tested fails (`"\x00"`, `"\x8a"`, `"\x00\x8a"`, `"\x004\x03"` without a
high byte, and even `"4\x8a\xd5\x03"` without the leading NUL — all 0/20), so the specific
mix is required. This narrows the over-decref to `disp_str`'s OOM handling of this string,
though the exact unbalanced-decref **line** is still not pinned (root cause PARTIAL).

The crash-time backtrace is obtained without gdb via `ASAN_OPTIONS=...:handle_abort=1`, which
makes ASan print a symbolized C backtrace on the abort; the `tuple_dealloc -> subtype_dealloc
-> list_dealloc` cascade is byte-identical on every run.

## Backtrace

```
refcount.h:520: _Py_NegativeRefcount: Assertion failed: object has negative ref count
Fatal Python error: _PyObject_AssertFailed     (object type name: MemoryError)
#9  _Py_NegativeRefcount   Objects/object.c:275
#12 tuple_dealloc          Objects/tupleobject.c:277   # Py_DECREF(item) -> the over-decref'd MemoryError
#13 subtype_dealloc        Objects/typeobject.c:2876
#14 _Py_Dealloc            Objects/object.c:3319
#17 list_dealloc           Objects/listobject.c:567
```

The faulting object is a `MemoryError` (from the fatal's `object type name`).

## Root cause

`_Py_NegativeRefcount`/`_PyObject_AssertFailed` are the *detector*, not the defect.
The defect is an **unbalanced `Py_DECREF` of a `MemoryError`** on an allocation-failure
path: under OOM, `MemoryError` objects are created/propagated heavily (CPython also keeps
a pre-allocated `MemoryError` to avoid allocating while out of memory), and an error
path drops one reference too many. The negative refcount then surfaces at the next
unrelated decref of that object (here a `tuple` item freed during a `subtype`/`list`
teardown). The exact over-decref site is **not isolated** from this single vehicle —
this is a consumer-side symptom; an allocation-failure-injection run that records the
decref balance for the shared/`MemoryError` objects would localize it.

## Suggested fix

Audit `Py_DECREF`/`Py_XDECREF` of `MemoryError` (and the cached/pre-allocated
`MemoryError`) on OOM error paths reachable from the `_pyrepl.utils` call chain — a
double-decref or a decref-without-incref on the failure branch. The standard remedies
are `Py_XDECREF` + NULL-after-free, or moving the decref out of a branch that didn't own
the reference.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`); flagged `oomNEW` by fusil's
in-loop dedup (it did not match the catalog). **Negative-refcount-under-OOM family**, but
distinct from OOM-0005 (`PyStackRef_XCLOSE`/`_PyFrame_ClearLocals`, frame locals) and
OOM-0019 (`Py_XDECREF` in `_PyPegen_raise_error_known_location`, the parser) — different
subsystem and a different (incidental) detection chain. The shared theme is an unbalanced
decref under OOM; these may or may not share a root. Debug-only: the `_Py_NegativeRefcount`
check is `Py_DEBUG`-gated, so it aborts on `ft_debug_asan`/`jit` and is compiled out on the
release builds (where the negative refcount is a silent use-after-free risk). Minimization
DONE (2026-06-19): deterministic 8-line stdlib repro (`disp_str("\x004\x8A\xD5\x03")` under
the sweep, 30/30) — shrinkray-reduced, oracle pinned to the `tuple_dealloc@tupleobject.c:277`
cascade via the ASan `handle_abort=1` symbolized backtrace (no gdb). Root cause still PARTIAL
(the trigger is minimal, but the exact unbalanced-decref line inside disp_str's OOM path is
not pinned — that needs a refcount watchpoint on the `MemoryError`).

## Versions

- main (3.16.0a0), commit 15d7406. Aborts on free-threaded debug+ASan and JIT debug+ASan;
  detector compiled out on the release builds.
