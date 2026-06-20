# Abort / malformed str: invalid `maxchar` in `_PyUnicode_FromUCS4` (`unicodeobject.c:2228`)

*Growing an `io.StringIO` buffer under OOM leaves uninitialized `Py_UCS4` within `[0, string_size)`; `getvalue()` -> `_PyUnicode_FromUCS4` scans the garbage, builds a `str` with `maxchar > 0x10FFFF`, and trips `_PyUnicode_CheckConsistency` (`unicodeobject.c:673`).*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Writing to an `io.StringIO` grows its internal `Py_UCS4` buffer
(`resize_buffer` → `PyMem_Realloc`). When a grow happens under memory pressure, the
buffer ends up with **uninitialized `Py_UCS4` values inside `[0, string_size)`**.
`getvalue()` then materializes the result string:

```
_io_StringIO_getvalue_impl (Modules/_io/stringio.c:294)
  -> PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, self->buf, self->string_size)
     -> _PyUnicode_FromUCS4(buf, size)            (Objects/unicodeobject.c:2228)
          max_char = ucs4lib_find_max_char(u, u + size);   # scans the garbage
          res = PyUnicode_New(size, max_char);             # max_char > 0x10ffff
        -> assert(_PyUnicode_CheckConsistency(res, 1))      # maxchar <= MAX_UNICODE -> FAIL
```

`ucs4lib_find_max_char` reads an uninitialized code point above `0x10FFFF`, so the new
`str` is built with an invalid `maxchar` and fails its consistency check. On a debug
build this aborts; on a release build the malformed `str` survives (and segfaults on the
JIT build).

## Reproducer

Minimal, stdlib-only, **deterministic** (4/4 on the debug build). Two phases mirror the
fuzzer's per-method OOM sweeps — accumulate, then read back:

```python
import faulthandler, io
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

s = io.StringIO()
chunk = "stringio-oom-chunk" * 2          # any small ASCII text, repeated to grow the buffer
for start in range(0, 1000):              # phase 1: accumulate under intermittent OOM
    try:
        set_nomemory(start, 0)
        try: s.writelines(chunk)
        finally: remove_mem_hooks()
    except BaseException: pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
for start in range(0, 1000):              # phase 2: read it back -> consistency check
    try:
        set_nomemory(start, 0)
        try: s.getvalue()
        finally: remove_mem_hooks()
    except BaseException: pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
```

The buffer must be grown large over many writes-under-OOM (the vehicle reached ~32830
chars); a single small write does not expose it. The content can be plain ASCII — the
out-of-range `maxchar` comes from uninitialized buffer memory, not from the written text.

## Backtrace

```
Objects/unicodeobject.c:673: _PyUnicode_CheckConsistency: Assertion failed: maxchar <= 0x10ffff
#9  _PyUnicode_CheckConsistency     Objects/unicodeobject.c:673
#10 _PyUnicode_FromUCS4 (size=32830) Objects/unicodeobject.c:2228   # reads the buffer
#11 _io_StringIO_getvalue_impl      Modules/_io/stringio.c:294
#12 _io_StringIO___getstate___impl  Modules/_io/stringio.c:866
```

## Root cause

`io.StringIO`'s buffer (`self->buf`, a `Py_UCS4` array sized `self->buf_size`, with
`self->string_size` valid characters) is grown by `resize_buffer` via `PyMem_Realloc`,
whose newly-added region is **not zeroed**. Normal writes keep `string_size` ≤ the
validly-written prefix, and `resize_buffer` memsets seek-gaps (`stringio.c:253`), so the
uninitialized tail is normally never read. Under repeated allocation failure while the
buffer grows, the buffer ends up with `string_size` covering uninitialized `Py_UCS4`
slots, and `getvalue()` → `_PyUnicode_FromUCS4` scans them. The exact write/resize step
that leaves the gap is **not pinned** (root-cause partial); the consistency check at
`unicodeobject.c:673` is the detector, and the real site is `_PyUnicode_FromUCS4`
(`unicodeobject.c:2228`).

## Suggested fix

Two defensible angles:
- Ensure `io.StringIO` never leaves uninitialized `Py_UCS4` within `[0, string_size)` —
  e.g. zero the grown region in `resize_buffer`, or guarantee `string_size` only ever
  covers written data even on the allocation-failure paths of `write`/`writelines`.
- Defensively, `_PyUnicode_FromUCS4` could reject code points `> MAX_UNICODE` with an
  error rather than building an inconsistent `str` (turning a debug-only abort / release
  corruption into a clean failure).

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`) by the local systemd fleet —
by the **new Phase 2 OOM method fuzzing**: an `oc1m4` sweep of
`email.iterators.StringIO.__getstate__` (`email.iterators.StringIO` is `io.StringIO`),
after a preceding `writelines` sweep had grown the buffer to ~32830 chars. **Second bug
attributable to OOM Phase 2** (after OOM-0034), again in a method path the
module-function-only sweep could not reach. Distinct from OOM-0030 (str-subclass
`unicode_subtype_new` → `_PyUnicode_NONCOMPACT_DATA` `data != NULL` — a different
consistency check). Reproduces deterministically on the debug build (consistency abort)
and the JIT build (segv); release/upstream silently build the malformed `str`.

## Versions

- main (3.16.0a0), commit `15d7406`. Repro matrix: `ft_debug_asan` abort, `jit` segv,
  `ft_release` no-crash, `upstream` no-crash.

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking 35 OOM-related crash findings.*
