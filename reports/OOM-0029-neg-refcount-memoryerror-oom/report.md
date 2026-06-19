# Title

Abort: negative refcount on a `MemoryError` under OOM — an OOM error path over-decrefs a `MemoryError`, tripping `_Py_NegativeRefcount` later during a dealloc cascade

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Under memory pressure a `MemoryError` instance is decref'd one time too many (its
refcount goes negative). The corruption is detected later — when an unrelated object
graph is torn down (`list_dealloc` → `subtype_dealloc` → `tuple_dealloc`) and that
already-broken `MemoryError` is `Py_DECREF`'d again — by `_Py_NegativeRefcount`
(`object.c:275`), which aborts (`_PyObject_AssertFailed`, debug builds). The
deallocation cascade is **incidental**: it is only where the bad refcount is next
touched, not where the unbalanced decref happened.

## Reproducer

Vehicle: fuzzing `_pyrepl.utils` (`gen_colors_from_token_stream`, `iter_display_chars`,
`_ascii_control_repr`, …) under the `set_nomemory` sweep
(`~/crashers/_pyrepl_utils-sigabrt-assertion-oomNEW/source.py`). Reproduces
deterministically on the debug builds (same `_Py_NegativeRefcount` ← `tuple_dealloc`
chain across runs). **No minimal stdlib trigger isolated** — the defect is an unbalanced
`MemoryError` decref on an OOM error path, and pinning the exact site needs the precise
allocation-failure timing; minimization is therefore vehicle-only.

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
release builds (where the negative refcount is a silent use-after-free risk). Root cause:
PARTIAL (symptom; over-decref site unisolated).

## Versions

- main (3.16.0a0), commit 15d7406. Aborts on free-threaded debug+ASan and JIT debug+ASan;
  detector compiled out on the release builds.
