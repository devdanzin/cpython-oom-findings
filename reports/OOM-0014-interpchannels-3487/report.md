# Abort/Segfault: unchecked NULL in `channelsmod__channel_id` (`_interpchannelsmodule.c:3487`)

*`_channel_id()` treats `get_module_from_owned_type()` as infallible; under OOM the `PyUnicode_FromString` inside `_get_current_module()` fails and returns NULL, tripping `assert(mod == self)` (abort) or `Py_DECREF(NULL)` (segfault).*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`_interpchannels._channel_id()` (C function `channelsmod__channel_id`) looks up its own module via `get_module_from_owned_type()` -> `_get_current_module()`, then immediately does `assert(mod == self)` and `Py_DECREF(mod)` without checking for `NULL`. Under OOM the first allocation inside `_get_current_module()` (a `PyUnicode_FromString(MODULE_NAME_STR)`) fails, so `mod == NULL`. On debug builds `assert(mod == self)` aborts; on release builds the assert is compiled out and the unchecked `Py_DECREF(NULL)` segfaults. The pre-existing `MemoryError` is also masked.

## Reproducer

```python
import _interpchannels, _testcapi, faulthandler
faulthandler.enable()
_testcapi.set_nomemory(0, 0)   # fail every allocation from #0 onward
try:
    _interpchannels._channel_id(0)   # _get_current_module() -> NULL
                                     # -> assert mod == self (abort) / Py_DECREF(NULL) (segv)
finally:
    _testcapi.remove_mem_hooks()
```

Deterministic at `start=0` on every build: the very first allocation the function performs is inside `_get_current_module()`, so failing allocation `#0` drives `mod == NULL`. The argument to `_channel_id` is irrelevant — the failure happens before it is ever used.

## Backtrace

```
#8  channelsmod__channel_id   Modules/_interpchannelsmodule.c:3487   <- assert mod == self
#9  cfunction_call            Objects/methodobject.c:564
#10 _PyObject_Call            Objects/call.c:361
#11 _PyEval_EvalFrameDefault  Python/generated_cases.c.h:2831
```

`(gdb) frame 8; print mod` -> `(PyObject *) 0x0`; `print self` -> the live `<module '_interpchannels'>`. On the `ft_release` build the same NULL reaches `Py_DECREF(mod)` at `:3488` (`Include/refcount.h` -> SIGSEGV); on `upstream` the NULL-free OOM instead faults earlier inside `PyImport_GetModule` reached from `_get_current_module()` at `:155` (same frame, `:3486`).

## Root cause

`Modules/_interpchannelsmodule.c`, `channelsmod__channel_id()` (L3478):

```c
    module_state *state = get_module_state(self);
    ...
    PyTypeObject *cls = state->ChannelIDType;

    PyObject *mod = get_module_from_owned_type(cls);   /* L3486: can return NULL */
    assert(mod == self);                               /* L3487: NULL != self -> abort */
    Py_DECREF(mod);                                    /* L3488: Py_DECREF(NULL) -> segv */

    return _channelid_new(self, cls, args, kwds);
```

`get_module_from_owned_type()` (L165) is a thin shim over `_get_current_module()` (L149):

```c
    PyObject *name = PyUnicode_FromString(MODULE_NAME_STR);   /* L151: fails under OOM */
    if (name == NULL) {
        return NULL;                                          /* L153 */
    }
    PyObject *mod = PyImport_GetModule(name);                 /* L155 */
    Py_DECREF(name);
    if (mod == NULL) {
        return NULL;                                          /* L158 */
    }
```

So `_get_current_module()` legitimately returns `NULL` (with an exception set) when an allocation fails, but the caller treats the result as infallible. The `assert(mod == self)` encodes an invariant that is only ever true on the success path; under OOM `mod` is `NULL`. The defect is a missing `NULL` check, not a use-after-free.

## Suggested fix

Check the return value before asserting / decref'ing, and propagate the error:

```c
    PyObject *mod = get_module_from_owned_type(cls);
    if (mod == NULL) {
        return NULL;                 /* propagate the MemoryError */
    }
    assert(mod == self);             /* invariant only meaningful once mod != NULL */
    Py_DECREF(mod);
```

(Long term the `XXX` notes at L169 suggest replacing the `_get_current_module()` shim with `PyType_GetModule(cls)`, which is infallible here and would remove the allocation entirely.)

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). Unlike the free-threading-specific asserts in this catalog, this defect is **build-agnostic**: the unchecked `NULL` is a real memory-safety bug on every configuration.

- `ft_debug_asan`: SIGABRT on `assert(mod == self)` at `:3487`.
- `jit` (also a debug build): identical SIGABRT on the same assert.
- `ft_release`: assert compiled out (`-DNDEBUG`); SIGSEGV in `Py_DECREF(mod)` at `:3488` (`Py_DECREF(NULL)`) — confirms the same NULL.
- `upstream`: assert compiled out; SIGSEGV inside `PyImport_GetModule` (`import_get_module` / `PyDict_GetItemRef`) reached from `_get_current_module()` at `:155`, i.e. the `get_module_from_owned_type(cls)` call at `:3486`. Same function/site, an allocation-timing-shifted instance of the same OOM defect.

Six fuzzer vehicles across `python-5` and `python-7` all abort at the identical `_interpchannelsmodule.c:3487` assertion (faulthandler Python stack: `_interpchannels._channel_id(...)` under the OOM sweep). The same NULL-from-`_get_current_module()` hazard exists in the sibling shim `get_module_from_type()` (L176) and at its other unchecked or assert-only callers; this report covers the `_channel_id` entry point that the fuzzer reached.

## Versions

- main (3.16.0a0, commit 15d7406). Reproduces on all four builds: SIGABRT on the debug builds (`ft_debug_asan`, `jit`), SIGSEGV on the release builds (`ft_release`, `upstream`).
