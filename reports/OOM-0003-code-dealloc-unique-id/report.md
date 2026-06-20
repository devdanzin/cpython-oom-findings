# Abort: uninitialized `_co_unique_id` assert in `code_dealloc` (`codeobject.c:2440`)

*`_PyCode_New` sets `_co_unique_id` only after `init_code()` succeeds; when `init_code`'s tlbc allocation fails under OOM, the resulting `Py_DECREF(co)` reaches `code_dealloc`, which asserts on the never-initialized (garbage) field on free-threaded debug builds.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

On free-threaded builds, `_PyCode_New()` assigns `co->_co_unique_id` only *after* `init_code()` succeeds. The field is not zero-initialized by the `PyObject_GC_NewVar` allocation. Under OOM, an allocation inside `init_code()` (the thread-local bytecode array, `_PyCodeArray_New`) fails, `_PyCode_New()` runs `Py_DECREF(co)`, and `code_dealloc()` asserts on the never-initialized `_co_unique_id` (garbage, not 0), aborting the interpreter.

## Reproducer

```python
import marshal, _testcapi, faulthandler
faulthandler.enable()
blob = marshal.dumps(compile("def f(x):\n    return x + 1\n", "<gen>", "exec"))
_testcapi.set_nomemory(9, 0)   # fail every allocation from #9 onward
try:
    marshal.loads(blob)        # _PyCode_New -> init_code fails -> Py_DECREF(co) -> assert
finally:
    _testcapi.remove_mem_hooks()
```

Deterministic at `start=9` on the free-threaded debug+ASan build. `marshal.loads` is just a convenient way to drive `_PyCode_New`; the OOM budget must be large enough for the code-object allocation to succeed but small enough that a later allocation inside `init_code` fails.

## Backtrace

```
#8  code_dealloc      Objects/codeobject.c:2440   <- assert co->_co_unique_id == _Py_INVALID_UNIQUE_ID
#9  _Py_Dealloc       Objects/object.c:3319
#10 Py_DECREF         Include/refcount.h:359
#11 _PyCode_New       Objects/codeobject.c:747    <- Py_DECREF(co) after init_code(co, con) < 0
#12 r_object          Python/marshal.c:1676       (marshal.loads)
```

`(gdb) frame 8; print co->_co_unique_id` -> a nonzero garbage value (never set to `_Py_INVALID_UNIQUE_ID`, which is `0`).

## Root cause

`Objects/codeobject.c`, `_PyCode_New()` (L716):

```c
    co = PyObject_GC_NewVar(PyCodeObject, &PyCode_Type, size);   /* L736: does NOT zero _co_unique_id */
    ...
    if (init_code(co, con) < 0) {
        Py_DECREF(co);                 /* L747: -> code_dealloc on a half-built code object */
        return NULL;
    }
#ifdef Py_GIL_DISABLED
    co->_co_unique_id = _PyObject_AssignUniqueId((PyObject *)co);   /* L752: only set AFTER init_code succeeds */
    _PyObject_GC_TRACK(co);
#endif
```

`init_code()` (L511) sets many fields but never initializes `co->_co_unique_id`. Its free-threaded branch allocates the tlbc array (L570):

```c
    co->co_tlbc = _PyCodeArray_New(INITIAL_SPECIALIZED_CODE_SIZE);   /* PyMem_Calloc, fails under OOM */
    if (co->co_tlbc == NULL) {
        return -1;                     /* -> _PyCode_New runs Py_DECREF(co) */
    }
```

When that `PyMem_Calloc` fails, `init_code` returns -1 before line 752 ever runs, so `_co_unique_id` still holds uninitialized heap garbage from `PyObject_GC_NewVar`. `code_dealloc()` (L2440) then asserts `co->_co_unique_id == _Py_INVALID_UNIQUE_ID` and aborts. The defect is a missing initialization, not a use-after-free.

## Suggested fix

Initialize the field before any path that can reach `code_dealloc`. Either in `init_code()` near the other field inits:

```c
#ifdef Py_GIL_DISABLED
    co->_co_unique_id = _Py_INVALID_UNIQUE_ID;
#endif
```

or in `_PyCode_New()` immediately after the `PyObject_GC_NewVar` NULL-check, before `init_code(co, con)`. (The later real assignment at L752 then overwrites it on the success path.)

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). Free-threading-specific: both `_co_unique_id` and the `code_dealloc` assert are gated on `#ifdef Py_GIL_DISABLED`. Reproduces as an **abort only on the free-threaded debug build** -- release builds define `-DNDEBUG`, so the `assert` is compiled out. On the FT release build the same uninitialized `_co_unique_id` instead feeds the deferred-refcount machinery and can segfault at a different site (latent memory-safety hazard); GIL builds (`jit`, `upstream`) lack the field entirely and run the reproducer cleanly. Per the OOM-catalog convention for assert-based aborts, the non-debug builds are recorded as `n/a`.

Four fuzzer vehicles (`random`, `_osx_support`, `tabnanny`, `xmlrpc_client`) all abort at the identical `codeobject.c:2440` assertion; each merely imports a stdlib module under OOM, which unmarshals its `.pyc` via `importlib._bootstrap_external._compile_bytecode` and reaches `_PyCode_New`.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build. Release/JIT/upstream builds: assertion compiled out (`n/a`).

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking 35 OOM-related crash findings.*
