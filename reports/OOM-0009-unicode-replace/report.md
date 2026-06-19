# Abort: `assert(release1 == (buf1 != PyUnicode_DATA(str1)))` in `replace` (`Objects/unicodeobject.c`) when a kind-widening allocation fails under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`str.replace()` (the C `replace()` helper) tracks three "owned scratch buffer" flags -- `srelease` / `release1` / `release2` -- that must stay consistent with their pointers `sbuf` / `buf1` / `buf2`. When a substring or replacement string of a narrower `PyUnicode` kind has to be widened, the code overwrites the pointer with the result of `unicode_askind()` (a `PyMem_New` allocation) and only sets the matching `release` flag on the *next* line. Under OOM, `unicode_askind()` returns `NULL`; the pointer becomes `NULL` while the flag is still `0`, and the `goto error` cleanup path then asserts `release1 == (buf1 != PyUnicode_DATA(str1))` -- which is `0 == 1` -- aborting the interpreter.

## Reproducer

```python
import sys, _testcapi, faulthandler
faulthandler.enable()
s = "轘" * 4                 # UCS-2 (2-byte kind) string
_testcapi.set_nomemory(0, 0)  # fail every allocation from #0 onward
try:
    s.replace("&", "&amp;")   # ASCII "&" must widen to UCS-2 via unicode_askind ->
                              # PyMem_New fails -> buf1=NULL, release1=0 -> error -> assert
finally:
    _testcapi.remove_mem_hooks()
```

Deterministic at `start=0` on builds with assertions enabled (FT debug+ASan, JIT debug). The input must be a wider kind than the ASCII substring so that `replace()` is forced down the `unicode_askind` widening path; the very first allocation it makes is the one that must fail. This is exactly what `html.escape()` does to a non-Latin-1 string (`s.replace("&", "&amp;")`), which is how the fuzzer found it.

## Backtrace

```
#8  replace              Objects/unicodeobject.c:10783   <- assert release1 == (buf1 != PyUnicode_DATA(str1))
#9  unicode_replace_impl Objects/unicodeobject.c:12586   (str.replace)
#10 unicode_replace      Objects/clinic/unicodeobject.c.h:1002
#11 _PyCallMethodDescriptorFastWithKeywords_StackRef  Python/ceval.c:883
#12 _PyEval_EvalFrameDefault  Python/generated_cases.c.h:4205
```

Faulting state: `buf1 == NULL` (the `unicode_askind`/`PyMem_New` for the widened substring failed under OOM) while `release1` is still `0`, so `(buf1 != PyUnicode_DATA(str1))` is `1` and the `0 == 1` assert fails. faulthandler's Python stack points at `Lib/html/__init__.py:19` (`s.replace("&", "&amp;")`).

## Root cause

`Objects/unicodeobject.c`, `replace()`. There are several copies of this pattern (L10583, L10592, L10605, L10608, L10646, L10655, L10662, L10671); the one the reproducer hits is L10644:

```c
    if (kind1 < rkind) {
        /* widen substring */
        buf1 = unicode_askind(kind1, buf1, len1, rkind);   /* L10646: PyMem_New, may fail */
        if (!buf1) goto error;          /* L10647: buf1 == NULL, release1 still 0 */
        release1 = 1;                   /* L10648: only reached on success */
    }
```

`unicode_askind()` (L2406) allocates with `PyMem_New` and returns `NULL` (via `PyErr_NoMemory()`) under OOM. On that failure `buf1` is set to `NULL` but `release1` is never set to `1`, so the flag/pointer invariant is broken. Every cleanup label -- `done` (L10756-10758), `nothing` (L10770-10772) and `error` (L10782-10784) -- then asserts:

```c
    assert(srelease == (sbuf != PyUnicode_DATA(self)));
    assert(release1 == (buf1 != PyUnicode_DATA(str1)));   /* L10783: 0 == 1 -> abort */
    assert(release2 == (buf2 != PyUnicode_DATA(str2)));
```

With `buf1 == NULL`, `(buf1 != PyUnicode_DATA(str1))` is `1` while `release1 == 0`, so the assertion fails. This is purely a stale-flag/assert bug: the subsequent `if (release1) PyMem_Free(buf1)` correctly does *not* free the NULL pointer, and the function would otherwise return `NULL` (a clean `MemoryError`) -- which is exactly what release builds do.

## Suggested fix

Make the assertions tolerant of the OOM failure path, or (cleaner) keep the flag in sync by treating a `NULL` widened buffer as "not owned". The simplest robust fix is to guard each assert against the error pointer being `NULL`, e.g.:

```c
    assert(release1 == (buf1 != NULL && buf1 != PyUnicode_DATA(str1)));
```

applied to all three flags at the `done` / `nothing` / `error` labels. (On the success paths `buf1` is always non-NULL, so this does not weaken the invariant there.) Equivalently, set `buf1 = PyUnicode_DATA(str1)` immediately before `goto error` when `unicode_askind` returns NULL, so the flag/pointer pair stays consistent.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). This is a **build-agnostic C bug** that surfaces only where the `assert()` is compiled in: it aborts on the free-threaded debug+ASan build **and** on the JIT debug build (both define assertions). On the FT release and upstream builds `-DNDEBUG` compiles the assert out, the desync is harmless (`if (release1) PyMem_Free` skips the NULL), and `str.replace` correctly raises `MemoryError`; those builds are therefore recorded as `n/a` (they do not crash, not even a segfault). Per the OOM-catalog convention for assert-based aborts, only assertion-enabled builds reproduce.

Fourteen fuzzer vehicles across many stdlib modules (`html`, `tomllib`, `sqlite3.dump`, `_pylong`, `shlex`, `wsgiref.headers`, `xml.etree.ElementInclude`, `compression.gzip`) all abort at the identical `unicodeobject.c:10783` assertion -- each reaches `str.replace` on a wider-than-ASCII string under OOM, confirming the defect is in `replace()` itself rather than any one caller.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build and the JIT debug build. FT release / upstream builds: assertion compiled out, `str.replace` raises `MemoryError` cleanly (`n/a`).
