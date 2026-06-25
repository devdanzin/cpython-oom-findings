# Abort: `assert(!PyErr_Occurred())` in `specialize` (`specialize.c:364`)

*An earlier OOM allocation leaves a stale `MemoryError` pending; `_Py_Specialize_LoadAttr` never checks `PyErr_Occurred()` and walks into `specialize(instr, LOAD_ATTR_MODULE)`, whose opening `assert(!PyErr_Occurred())` aborts.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

The adaptive `LOAD_ATTR` specializer runs at the *start* of the opcode (`_SPECIALIZE_LOAD_ATTR`), before the attribute is actually loaded, and assumes no exception is pending. Under OOM injection an earlier allocation in the same expression leaves a `MemoryError` set. `_Py_Specialize_LoadAttr` never checks `PyErr_Occurred()` and proceeds into `specialize(instr, LOAD_ATTR_MODULE)`, whose opening `assert(!PyErr_Occurred())` (`Python/specialize.c:364`) then aborts the interpreter.

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the vehicle, then cleaned; deterministic,
re-verified). LOAD_ATTR specialization under OOM leaves a pending exception.

```python
import faulthandler, asyncio, optparse   # the asyncio import is load-bearing (shrinkray kept it)
faulthandler.enable()
from _testcapi import set_nomemory
for start in range(120):
    set_nomemory(start)
    try:
        optparse.ngettext(0.0, 0, "")
    except BaseException:
        pass
print("done, no crash")
```

The full fuzzer vehicle is preserved as `vehicle_source.py`.

## Backtrace

```
#8  specialize                          Python/specialize.c:364   <- assert !PyErr_Occurred() (opcode 190 = LOAD_ATTR_MODULE)
#9  specialize_module_load_attr_lock_held Python/specialize.c:443   <- specialize(instr, LOAD_ATTR_MODULE)
#10 specialize_module_load_attr          Python/specialize.c:460
#11 _Py_Specialize_LoadAttr              Python/specialize.c:1010
#12 _PyEval_EvalFrameDefault             Python/generated_cases.c.h:8761  (_SPECIALIZE_LOAD_ATTR for LOAD_ATTR)
```

`(gdb)` break at `specialize.c:364 if PyErr_Occurred() != 0` -> `specialized_opcode == 190` and the pending exception's `object type name: MemoryError`. The error is *stale* (set by a prior allocation), not raised inside the specializer.

## Root cause

The specializer is best-effort and is documented to require a clean error state. `specialize()` (`Python/specialize.c:362`) opens with:

```c
static inline void
specialize(_Py_CODEUNIT *instr, uint8_t specialized_opcode)
{
    assert(!PyErr_Occurred());          /* L364 */
    ...
}
```

and the type-cache lookup it depends on makes the same assumption (`Objects/typeobject.c:6342`: `/* We may end up clearing live exceptions below, so make sure it's ours. */ assert(!PyErr_Occurred());`).

`_SPECIALIZE_LOAD_ATTR` invokes `_Py_Specialize_LoadAttr` at the top of the opcode (`Python/bytecodes.c`, `generated_cases.c.h:8761`) without first checking for a pending exception. `_Py_Specialize_LoadAttr` (`specialize.c:994`) and `specialize_module_load_attr_lock_held` (`specialize.c:411`) likewise never test `PyErr_Occurred()`; they walk straight to `specialize(instr, LOAD_ATTR_MODULE)` (`specialize.c:443`). Under `set_nomemory`, an allocation earlier in the same Python expression fails and leaves a `MemoryError` set; the specializer then observes it and the debug assert fires. This is a missing pending-error guard, not a use-after-free or NULL deref.

## Suggested fix

Make specialization a no-op when an exception is already pending. Simplest at the entry of `_Py_Specialize_LoadAttr` (and symmetrically for the other `_Py_Specialize_*` entry points / the `_SPECIALIZE_*` micro-ops):

```c
Py_NO_INLINE void
_Py_Specialize_LoadAttr(_PyStackRef owner_st, _Py_CODEUNIT *instr, PyObject *name)
{
    PyObject *owner = PyStackRef_AsPyObjectBorrow(owner_st);
    assert(ENABLE_SPECIALIZATION);
    if (PyErr_Occurred()) {            /* stale error (e.g. OOM): don't specialize */
        unspecialize(instr);
        return;
    }
    ...
}
```

Alternatively, gate the `_SPECIALIZE_*` micro-ops in the eval loop so the specializer is never called while `tstate` holds a pending exception.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). assert-based abort: fires on builds that compile assertions in. Reproduces on the **free-threaded debug+ASan build** and on the **JIT build** (both ship the `assert`); the **FT release** and **upstream** builds define `-DNDEBUG`, so the assert is compiled out and the reproducer runs cleanly (recorded as `n/a` per the OOM-catalog convention for assert-based aborts). On non-debug builds the specializer simply writes the specialized opcode while a `MemoryError` is pending, which the eval loop then propagates normally -- latent but not crashing here.

Ten fuzzer vehicles across `python-4/5/7` abort at the identical `specialize.c:364` assertion; the Python-level faulthandler stack points at `gettext._as_int2` (`n.__class__.__name__`) reached via `ngettext`/`npgettext`/`dngettext` with a non-int `n`, but the C-level crash is build-agnostic and not gettext-specific -- any `LOAD_ATTR` specialized while an error is pending triggers it. Minimization is **partial**: the crash needs a failing allocation to coincide with a not-yet-specialized hot `LOAD_ATTR`, so the reproducer drives the real `gettext` path under a `set_nomemory` sweep rather than a single deterministic `start`.

**Build note (`1b9fe5c`, 2026-06-24).** On the current workhorse build the committed repro is
**flaky between two sibling sites of the same `!PyErr_Occurred()` family**: a 10× run aborted
5× at this bug's own `specialize.c:364` and 5× at `_PyType_LookupStackRefAndVersion`
(`typeobject.c:6343`, the type-cache assert = OOM-0008's site). Both are the same defect class
— a stale `MemoryError` left pending when a `!PyErr_Occurred()` assert is checked — and the
allocation window has drifted across commits (`15d7406` → `1b9fe5c`) so the swept failure now
lands on either assert roughly half the time. This is **window-drift flakiness, not a new bug
or a deterministic mislabel** (the root-cause section already notes that `specialize()` and the
type cache share the assumption). The repro still exercises this bug's site on ~half the runs;
to pin it deterministically to `specialize.c:364` again, tighten the sweep/window so the
failure precedes the type-cache lookup (verify the crashing opcode is `LOAD_ATTR_MODULE`).

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build and the JIT build. FT release / upstream builds: assertion compiled out (`n/a`, clean exit).

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking 35 OOM-related crash findings.*
