# Abort: `PyTraceBack_Here` appends to a non-traceback `__traceback__` under OOM (`traceback.c:313`)

*Under OOM, the in-flight exception's `__traceback__` field holds an object that is not a traceback. When the eval loop appends the current frame via `PyTraceBack_Here → _PyTraceBack_FromFrame`, the `assert(tb_next == NULL || PyTraceBack_Check(tb_next))` fails. The corrupt `tb_next` points at a live-but-wrong-type object, i.e. the traceback was freed and its storage reused — an over-decref / use-after-free of the exception traceback under memory pressure.*

_AI Disclaimer: this report was drafted by Claude Code, which also reproduced the crash and characterized it._

## Crash report

As an exception propagates out of a frame, the eval loop calls `PyTraceBack_Here(frame)` to prepend that frame to the exception's traceback chain:

```c
int
PyTraceBack_Here(PyFrameObject *frame)
{
    PyObject *exc = PyErr_GetRaisedException();
    assert(PyExceptionInstance_Check(exc));
    PyObject *tb = PyException_GetTraceback(exc);       /* exc->traceback */
    PyObject *newtb = _PyTraceBack_FromFrame(tb, frame);
    ...
}

PyObject*
_PyTraceBack_FromFrame(PyObject *tb_next, PyFrameObject *frame)
{
    assert(tb_next == NULL || PyTraceBack_Check(tb_next));   /* <- fails */
    ...
}
```

`exc` is a valid exception instance (the earlier assert passes), but `exc->traceback` (`tb_next`) is **neither NULL nor a `traceback` object** — so `PyTraceBack_Check(tb_next)` (`Py_IS_TYPE(tb_next, &PyTraceBack_Type)`) fails and CPython aborts. `__traceback__` cannot be set to a non-traceback from Python (the descriptor type-checks), so this is C-level corruption: under OOM the traceback object was decref'd to zero while `exc` still referenced it, freed, and its memory reused for an object of another type. `PyTraceBack_Here` then reads the dangling pointer as `tb_next`.

This is the same over-decref / stale-reference class as the eval-loop OOM bugs (cf. OOM-0005), surfacing here at the traceback chain. The assertion is `Py_DEBUG`-gated (abort on debug/JIT builds); on a release build the check is compiled out and the dangling `tb_next` is instead linked into a `PyTracebackObject` and later traversed/dealloc'd as if it were a traceback — latent UB / use-after-free.

## Reproducer

Vehicle-confirmed; **minimization open** (see Notes). The preserved fuzzer vehicle `vehicle_source.py` (target module `inspect`) aborts deterministically with this assertion. A plain "raise through several frames under an OOM sweep" does **not** reproduce — the corruption requires the specific over-decref of the traceback object, which is not yet isolated:

```python
# Does NOT reproduce on its own (survives): plain exception propagation under OOM does not
# corrupt exc.__traceback__. The over-decref trigger is not yet isolated; vehicle_source.py
# (target: inspect) is the reliable reproducer. Kept here to document what was ruled out.
import faulthandler; faulthandler.enable()
from _testcapi import set_nomemory
DISABLE = 2_000_000_000
set_nomemory(DISABLE, 0)
def f3(): raise ValueError("boom")
def f2(): f3()
def f1(): f2()
for start in range(3000):
    set_nomemory(start, start + 5)
    try:
        try:
            f1()
        finally:
            set_nomemory(DISABLE, 0)
    except BaseException:
        pass
print("survived (no crash)")
```

## Backtrace

```
python: Python/traceback.c:313: PyObject *_PyTraceBack_FromFrame(PyObject *, PyFrameObject *):
        Assertion `tb_next == NULL || PyTraceBack_Check(tb_next)' failed.
Fatal Python error: Aborted

# C path (ASan, free-threaded debug+ASan):
#13 _PyTraceBack_FromFrame   Python/traceback.c:313     tb_next (== exc->traceback) is not NULL and not a traceback
#14 PyTraceBack_Here         Python/traceback.c:326
#15 _PyEval_EvalFrameDefault Python/generated_cases.c.h:13833   (exception propagating out of a frame)
... PyEval_EvalCode -> run_eval_code_obj   (raised during module exec under the OOM sweep)
```

See `backtrace.txt`. Confirming the UAF (the type/identity of the object `tb_next` now points at) requires a gdb hardware watchpoint on `exc->traceback` to catch the freeing decref — see Notes.

## Root cause

`Python/traceback.c`, `_PyTraceBack_FromFrame` (L313) / `PyTraceBack_Here` (L317-340). The invariant being asserted — that an exception's `__traceback__` is always NULL or a real traceback — is violated because the traceback object is freed out from under `exc` under OOM (an over-decref leaves `exc->traceback` dangling; the freed block is reused for an object of a different type). The defect is **not** in `traceback.c` itself (which correctly asserts the invariant); it is the over-decref of the traceback elsewhere in the OOM unwinding path. The assertion is the detector, in the spirit of the gh-89373 / negative-refcount invariants.

## Suggested fix

Find and fix the over-decref of `exc->traceback` on the OOM error path (the producer), not the assertion (the detector). Pinning it needs a debug build with a watchpoint on the exception's `traceback` slot (`watch -l exc->traceback`) while running the vehicle, to catch the decref that drops it to zero while still referenced. Until the producing decref is located this is a *characterized* finding, not a one-line fix.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`), fusil `--oom-seq` mode. **Recurring across machines** (local FT debug+ASan + the `magalu` box) and several traceback-touching target modules: `inspect`, `_pyrepl_render`, `xmlrpc_server` — all paths that build or format tracebacks while an exception is in flight.

**Distinct** from the PEP-657-caret traceback OOM finding (which is `ast.parse` invoked from `traceback.py` while formatting carets); this is the C-level `PyTraceBack_Here` invariant on a corrupt `exc->traceback`.

**Debug-only signature; latent UB on release.** The assertion is `Py_DEBUG`-gated (abort on `ft_debug_asan` + `jit`); on release builds (`ft_release`, `upstream`) it is compiled out and the dangling `tb_next` is linked into the new traceback and later traversed/freed — a latent use-after-free, recorded `n/a` for the release builds.

**Minimization: open.** Vehicle-confirmed; a plain raise-under-OOM sweep does not reproduce (the over-decref trigger is unisolated). Recommended next step: gdb watchpoint on `exc->traceback` against the vehicle to pin the freeing decref, then catalog the producer (it may turn out to be a face of an existing eval-loop over-decref bug such as OOM-0005).

## Versions

- main (3.16.0a0), commit `1b9fe5c` (free-threaded debug+ASan, Clang 21). Aborts deterministically from the vehicle on the `Py_DEBUG` builds; release builds compile the assertion out (latent UB).

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking OOM-related crash findings.*
