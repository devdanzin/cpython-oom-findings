# Abort: `assert(!PyErr_Occurred())` in `_PyType_LookupStackRefAndVersion` (`typeobject.c:6343`)

*Under OOM, `frame.f_back`'s lazy parent-frame allocation fails and sets `MemoryError`, but `PyFrame_GetBack` returns `NULL` and `frame_back_get_impl` reports it as `None`, leaving the exception pending; the next `LOAD_ATTR` then trips `assert(!PyErr_Occurred())`.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Reading `frame.f_back` lazily materializes the parent `PyFrameObject`. Under OOM that allocation fails and sets `MemoryError`, but `PyFrame_GetBack()` does not check for it: it returns `NULL`, and `frame_back_get_impl()` interprets `NULL` as "no parent frame" and returns `None` *successfully* -- swallowing the pending exception. The `LOAD_ATTR` opcode therefore completes "successfully" with a `MemoryError` still set, and the **next** attribute lookup enters `_PyType_LookupStackRefAndVersion`, which asserts `!PyErr_Occurred()` and aborts. On release builds (assert compiled out) the dangling exception surfaces later as a spurious `SystemError: ... returned a result with an exception set`.

## Reproducer

```python
import sys, _testcapi, faulthandler
faulthandler.enable()
def walk():
    f = sys._getframe()
    while f is not None:
        f = f.f_back          # under OOM, materializing the parent frame fails:
                              # MemoryError is set but f.f_back returns None
_testcapi.set_nomemory(1, 0)  # fail every allocation from #1
try:
    try:
        walk()                # returns with a pending MemoryError after yielding None
        x = sys.maxsize       # next LOAD_ATTR -> _PyType_LookupStackRefAndVersion
                              # -> assert(!PyErr_Occurred()) fails -> SIGABRT
    finally:
        _testcapi.remove_mem_hooks()
except MemoryError:
    pass
```

Deterministic at `start=1` on the free-threaded debug+ASan build (and on the JIT debug build). The frame-walk just guarantees at least one `f.f_back` access whose lazy `PyFrameObject` allocation fails; the trailing `sys.maxsize` is any subsequent `LOAD_ATTR` that then trips the assert.

## Backtrace

```
#8  _PyType_LookupStackRefAndVersion   Objects/typeobject.c:6343   <- assert !PyErr_Occurred()
#9  _PyObject_GenericGetAttrWithDict    Objects/object.c:1919
#10 _PyObject_GetAttrStackRef           Objects/object.c:1369
#11 _PyEval_EvalFrameDefault            Python/generated_cases.c.h:8786   (LOAD_ATTR)
#12 _PyEval_Vector                      Python/ceval.c:2141
#13 PyEval_EvalCode                     Python/ceval.c:679
```

The faulting object is valid; the invariant violated is "no live exception on entry to a type lookup". `(gdb) p (int)PyErr_Occurred()` at frame 8 is nonzero (a `MemoryError` set during the previous `frame.f_back`).

## Root cause

`Objects/frameobject.c`, `PyFrame_GetBack()` (L2395):

```c
PyFrameObject*
PyFrame_GetBack(PyFrameObject *frame)
{
    PyFrameObject *back = frame->f_back;
    if (back == NULL) {
        _PyInterpreterFrame *prev = frame->f_frame->previous;
        prev = _PyFrame_GetFirstComplete(prev);
        if (prev) {
            back = _PyFrame_GetFrameObject(prev);   /* L2404: may fail + set MemoryError, returns NULL */
        }
    }
    return (PyFrameObject*)Py_XNewRef(back);          /* L2407: returns NULL, error NOT cleared/propagated */
}
```

`_PyFrame_GetFrameObject()` (`Include/internal/pycore_interpframe.h:340`) lazily creates the `PyFrameObject` via `_PyFrame_MakeAndSetFrameObject()`, whose `PyObject_GC_New` fails under OOM and returns `NULL` with `MemoryError` set. `PyFrame_GetBack` does not distinguish "no parent frame" (`back == NULL`, no error) from "allocation failed" (`back == NULL`, error set). The getter `frame_back_get_impl()` (`Objects/frameobject.c:1116`) then does:

```c
    PyObject *res = (PyObject *)PyFrame_GetBack(self);
    if (res == NULL) {
        Py_RETURN_NONE;          /* L1118: treats the OOM failure as "top frame" -> None */
    }
```

So `frame.f_back` evaluates to `None` while a `MemoryError` is left pending. The `LOAD_ATTR` reports success; the next type lookup hits `assert(!PyErr_Occurred())` (typeobject.c:6343). The defect is a swallowed/unpropagated exception, not a bad pointer.

## Suggested fix

Propagate the allocation failure instead of masking it. In `PyFrame_GetBack()`, distinguish the error case:

```c
        if (prev) {
            back = _PyFrame_GetFrameObject(prev);
            if (back == NULL) {
                return NULL;     /* MemoryError already set; let it propagate */
            }
        }
```

and in `frame_back_get_impl()` only convert a *clean* `NULL` to `None`:

```c
    PyObject *res = (PyObject *)PyFrame_GetBack(self);
    if (res == NULL && !PyErr_Occurred()) {
        Py_RETURN_NONE;
    }
    return res;                  /* NULL with error set -> propagate */
```

This turns the OOM into a normal `MemoryError` raised from the `f.f_back` access, which the eval loop handles correctly.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). The C defect is **build-agnostic**, but the *symptom* differs by build:

- **ft_debug_asan**: `abort` at the `assert(!PyErr_Occurred())` (typeobject.c:6343).
- **jit** (debug, assertions on): identical `abort` at the same assertion.
- **ft_release / upstream** (`-DNDEBUG`, assert compiled out): no abort; the swallowed `MemoryError` instead surfaces later as `SystemError: <built-in function ...> returned a result with an exception set` (a dangling-exception symptom). Per the OOM-catalog convention for assert-based aborts, these are recorded as `n/a`.

The 16 fuzzer vehicles all abort at the identical `typeobject.c:6343` assertion but via diverse stdlib stack-walkers that read `frame.f_back`: `gettext._as_int2` (warning stacklevel walk), `logging.findCaller`, `asyncio.format_helpers.extract_stack` / `traceback.walk_stack`, `argparse`, `optparse`, and `concurrent.futures`. Each merely walks frames (for a warning or traceback) while a `MemoryError` is injected, so any subsequent `LOAD_ATTR` trips the assert. The same swallow-on-OOM pattern likely affects other lazy frame getters (`f_globals`/`f_locals` raise cleanly here, but `f_back` does not).

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build and the JIT debug build. Release/upstream builds: assertion compiled out (`n/a`); the bug instead leaks a `MemoryError` into an unrelated `SystemError`.

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking 35 OOM-related crash findings.*
