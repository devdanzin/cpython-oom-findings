# Title

Abort: a warning emitted under memory pressure enters `warn_explicit` message-normalization with a pending exception — debug assert `!_PyErr_Occurred(tstate)` in `type_call` (`Objects/typeobject.c:2441`) / `PyObject_Str` (`Objects/object.c:818`)

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

When a warning is emitted while an allocation failure is active, CPython's warnings C path
(`do_warn` → `warn_explicit`) reaches message normalization with a `MemoryError` already
pending. `warn_explicit` then normalizes the message *without first checking for a pending
exception*:

- a plain-string message takes the category-constructor branch
  `message = PyObject_CallOneArg(category, message)` (`_warnings.c:806`) → `type_call`, which
  asserts `!_PyErr_Occurred(tstate)` at its entry (`typeobject.c:2441`);
- a `Warning`-instance message takes `text = PyObject_Str(message)` (`_warnings.c:799`) →
  `PyObject_Str`, which asserts the same invariant (`object.c:818`).

Both abort the interpreter on a debug build. The assert is `#ifdef Py_DEBUG`, so on release
builds it is compiled out and the pending exception is silently lost — a latent invariant
violation (`type_call`/`PyObject_Str` may clear the caller's exception, per the assert's own
comment).

## Reproducer

Minimal, stdlib-only — emit a warning under the `set_nomemory` sweep. Deterministic (3/3)
on the free-threaded debug+ASan build; trips the `PyObject_Str` sibling site:

```python
import warnings, faulthandler
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks
warnings.simplefilter("always")
for start in range(0, 600):
    try:
        set_nomemory(start, 0)
        warnings.warn(UserWarning("oom-%d" % start))   # Warning instance -> PyObject_Str branch
    except MemoryError:
        pass
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
print("done, no assert")
```

The fleet vehicle (`vehicle_source.py`, fuzzing `zoneinfo._tzpath`) instead hits the
`type_call` branch (plain-string message). A plain-string minimal sweep segfaults elsewhere
in the warnings path before reaching the exact `type_call:2441` window, so that specific site
is **vehicle-confirmed**; the root cause is the same and is reproduced deterministically by
the `PyObject_Str` variant above.

## Backtrace

Fleet vehicle (debug, SIGABRT) — `type_call` branch:

```
python: Objects/typeobject.c:2441: type_call: Assertion `!_PyErr_Occurred(tstate)' failed.
#8  type_call            Objects/typeobject.c:2441     # assert: an exception is already pending
#9  _PyObject_MakeTpCall  Objects/call.c:242
#10 PyObject_CallOneArg   Objects/call.c:395
#11 warn_explicit        Python/_warnings.c:806        # PyObject_CallOneArg(category, message)
#12 do_warn              Python/_warnings.c:1136
```

Minimal repro (debug, SIGABRT) — `PyObject_Str` branch:

```
python: Objects/object.c:818: PyObject_Str: Assertion `!_PyErr_Occurred(tstate)' failed.
#8  PyObject_Str         Objects/object.c:818
#9  warn_explicit        Python/_warnings.c:799        # text = PyObject_Str(message)
```

## Root cause

`Python/_warnings.c`, `warn_explicit` (L796–809):

```c
/* Normalize message. */
Py_INCREF(message);  /* DECREF'ed in cleanup. */
if (PyObject_TypeCheck(message, (PyTypeObject *)PyExc_Warning)) {
    text = PyObject_Str(message);            /* L799: asserts !_PyErr_Occurred */
    if (text == NULL)
        goto cleanup;
    category = (PyObject*)Py_TYPE(message);
}
else {
    text = message;
    message = PyObject_CallOneArg(category, message);  /* L806 -> type_call asserts !_PyErr_Occurred */
    if (message == NULL)
        goto cleanup;
}
```

At the crashing invocation a `MemoryError` is already set on entry to `warn_explicit` (nothing
between the function entry and these calls sets one), so the defect is a **missing
pending-exception check on the OOM path** before message normalization — either `do_warn` /
`warn_explicit` should bail (or assert) when entered with an exception set, or an earlier
caller is emitting a warning without clearing a failed allocation's `MemoryError`. Both
`type_call` and `PyObject_Str` explicitly document that they must not be called with an
exception set because they can clear it, losing the caller's exception.

## Suggested fix

Guard the warnings emission path against a pre-existing exception under allocation failure:
check `_PyErr_Occurred(tstate)` at the top of `warn_explicit` (or `do_warn`) and short-circuit
/ propagate rather than normalizing the message, and audit the callers that invoke the warnings
machinery so they do not do so with a pending `MemoryError`. This removes both the
`type_call:2441` and `PyObject_Str:818` aborts (same fix) and the corresponding release-build
exception loss.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`) by the local systemd fleet; flagged
`oomNEW` and surfaced by the native-backtrace ingest sweep over the 31-bug catalog. Member of
the "stale/missing exception under OOM" assert family (cf. OOM-0008/0010/0011/0015), distinct
site. **Not** OOM-0001 (`do_warn:1139` `Py_DECREF`-of-freed segv) — though the *same* fleet
vehicle is build-dependent: it aborts here (OOM-0032) on both debug builds (`ft_debug_asan`
*and* `jit`, which is also `Py_DEBUG`) and segfaults in `do_warn` (OOM-0001) on the release
builds (`ft_release`/`upstream`), a textbook one-vehicle-multiple-bugs case.
Verified distinct: OOM-0001's *own* reducer SIGSEGVs at `do_warn:1139` (`Py_DECREF(filename)`,
the `setup_context` over-decref) on the **debug** build too — same site on debug and release,
never tripping this `warn_explicit` assert. Different function, different defect.

## Versions

- main (3.16.0a0), commit `15d7406`. SIGABRT on both `Py_DEBUG` builds (`ft_debug_asan`
  and `jit`); the assert is compiled out on the release builds `ft_release` / `upstream`
  (latent — that vehicle segfaults via OOM-0001 there).
