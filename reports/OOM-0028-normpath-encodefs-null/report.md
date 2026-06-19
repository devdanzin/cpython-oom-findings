# Segfault: `os._path_normpath(bytes)` dereferences a NULL string under OOM — `os__path_normpath_impl` (`Modules/posixmodule.c:6149`) passes an unchecked `PyUnicode_From*` result to `PyUnicode_EncodeFSDefault`

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`os__path_normpath_impl` builds the normalized path with `PyUnicode_FromOrdinal('.')`
or `PyUnicode_FromWideChar(...)`, either of which can return `NULL` under memory
pressure. When the input path was `bytes`, it then re-encodes with
`Py_SETREF(result, PyUnicode_EncodeFSDefault(result))` **without checking `result` for
NULL**. `PyUnicode_EncodeFSDefault(NULL)` reaches `unicode_encode_utf8(NULL, …)`, whose
`PyUnicode_Check(unicode)` dereferences the NULL `ob_type` → SIGSEGV. Reproduces on all
build configurations (it is a plain NULL dereference, not a debug-only assert).

## Reproducer

Minimal, stdlib-only:

```python
import posix
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(1, 2000):
    set_nomemory(start, 0)
    try:
        try:
            posix._path_normpath(b"foo//bar/../baz")   # bytes path -> EncodeFSDefault branch
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
```

(`posix._path_normpath` is the C accelerator behind `ntpath.normpath`; on POSIX it is
reachable as `posix._path_normpath`. A `bytes` argument is required to take the
`PyBytes_Check` re-encode branch.)

## Backtrace

```
Program received signal SIGSEGV, Segmentation fault.
#0  unicode_encode_utf8 (unicode=0x0, ...)   Objects/unicodeobject.c:5681   # PyUnicode_Check(NULL)->ob_type
#1  os__path_normpath_impl (module, path)    Modules/posixmodule.c:6149     # Py_SETREF(result, EncodeFSDefault(result)), result==NULL
#2  os__path_normpath                        Modules/clinic/posixmodule.c.h:2701
#3  _Py_BuiltinCallFastWithKeywords_StackRef Python/ceval.c:841
#4  _PyEval_EvalFrameDefault                 Python/generated_cases.c.h:2603
```

`unicode == 0x0` confirmed in gdb: the `result` produced just above is NULL and flows
straight into the encoder.

## Root cause

`Modules/posixmodule.c`, `os__path_normpath_impl` (L6134-6152):

```c
    PyObject *result;
    ...
    if (!norm_len) {
        result = PyUnicode_FromOrdinal('.');          /* may return NULL under OOM */
    }
    else {
        result = PyUnicode_FromWideChar(norm_path, norm_len);  /* may return NULL under OOM */
    }
    if (PyBytes_Check(path->object)) {
        Py_SETREF(result, PyUnicode_EncodeFSDefault(result));  /* L6149: result unchecked */
    }
    return result;
```

The two `PyUnicode_From*` constructors allocate and can fail; `result` is never
NULL-checked before the `bytes`-path re-encode. `PyUnicode_EncodeFSDefault(NULL)`
forwards NULL to `unicode_encode_utf8`, which assumes a valid object.

## Suggested fix

Guard the re-encode (and the function already returns `result==NULL` correctly to
propagate the error):

```c
    if (result != NULL && PyBytes_Check(path->object)) {
        Py_SETREF(result, PyUnicode_EncodeFSDefault(result));
    }
    return result;
```

(Equivalently, `if (result == NULL) return NULL;` before the `PyBytes_Check`.)
Hardening `PyUnicode_EncodeFSDefault` / `unicode_encode_utf8` to reject NULL would
convert the crash into a clean error elsewhere, but the missing check belongs here.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`); surfaced by the catalog
ingest as a new site (`unicode_encode_utf8`) distinct from OOM-0009 (`replace`,
unicodeobject.c:10783). Clean NULL dereference — **reproduces on every build**
(ft_debug_asan, ft_release, jit, upstream), unlike the debug-only assert/ASan-only
findings. Original vehicle `python-7/profiling_sampling_cli-segmentation_fault` reached
it via an `os.path` operation on a bytes path; reduced to the 3-line trigger above.

## Versions

- main (3.16.0a0), commit 15d7406. Reproduces (SIGSEGV) on all four local builds
  (free-threaded debug+ASan, free-threaded release, JIT, upstream release).
