# Title

Segfault: unchecked `PyUnicode_AsUTF8` in the tokenizer's column-offset helper — NULL dereference in `_PyPegen_byte_offset_to_character_offset_line` (`Parser/pegen.c:33`) under OOM

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

When the C tokenizer emits a token on a line that contains a non-ASCII character, it
converts byte offsets to character offsets via
`_get_col_offsets` (`Python/Python-tokenize.c`) →
`_PyPegen_byte_offset_to_character_offset_line(line, ...)`. That helper does:

```c
const unsigned char *data = (const unsigned char*)PyUnicode_AsUTF8(line);   // pegen.c:29 — result UNCHECKED
...
Py_UCS4 ch = data[col_offset];                                              // pegen.c:33 — derefs data
```

Under memory pressure `PyUnicode_AsUTF8(line)` cannot build/cache the line's UTF-8 form and
returns `NULL`; `data` is never checked, so `data[col_offset]` dereferences NULL and the
interpreter segfaults. `line` itself is a perfectly valid `str` (gdb-confirmed) — only the
UTF-8 conversion failed. Reproduces on all four build configurations (a plain NULL
dereference, not a debug-only assert).

## Reproducer

Minimal, stdlib-only, **deterministic** (4/4 across builds): tokenize a line with one
non-ASCII character under the `set_nomemory` sweep.

```python
import faulthandler, io, tokenize
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

src = "ü\n"        # any line with a multibyte character triggers _get_col_offsets
for start in range(0, 400):
    try:
        set_nomemory(start, 0)
        try:
            list(tokenize.generate_tokens(io.StringIO(src).readline))
        finally:
            remove_mem_hooks()
    except MemoryError:
        pass
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
```

The non-ASCII character is required — with an all-ASCII line, byte offset == character
offset and `_get_col_offsets` never calls the helper.

## Backtrace

```
Program received signal SIGSEGV, Segmentation fault.
#0  _PyPegen_byte_offset_to_character_offset_line  Parser/pegen.c:33     # data[col_offset], data == NULL
#1  _get_col_offsets                               Python/Python-tokenize.c:229
#2  tokenizeriter_next                             Python/Python-tokenize.c:304
#3  _PyForIter_VirtualIteratorNext                 Python/ceval.c:3744    # FOR_ITER over the tokenizer
```

## Root cause

`Parser/pegen.c`, `_PyPegen_byte_offset_to_character_offset_line`:

```c
Py_ssize_t
_PyPegen_byte_offset_to_character_offset_line(PyObject *line, Py_ssize_t col_offset,
                                              Py_ssize_t end_col_offset)
{
    const unsigned char *data = (const unsigned char*)PyUnicode_AsUTF8(line);  /* may be NULL */
    Py_ssize_t len = 0;
    while (col_offset < end_col_offset) {
        Py_UCS4 ch = data[col_offset];   /* NULL deref when PyUnicode_AsUTF8 failed */
        ...
```

`PyUnicode_AsUTF8` can fail (and set `MemoryError`) whenever it must allocate the cached
UTF-8 representation. The return value is used without a NULL check.

## Suggested fix

Check the `PyUnicode_AsUTF8` result and propagate the error:

```c
const char *utf8 = PyUnicode_AsUTF8(line);
if (utf8 == NULL) {
    return -1;   /* or an agreed sentinel; _get_col_offsets must handle it */
}
const unsigned char *data = (const unsigned char *)utf8;
```

`_get_col_offsets` / `tokenizeriter_next` should handle the failure path (propagate the
exception) rather than computing column offsets.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`) by the local systemd fleet —
specifically by the **new Phase 2 OOM class fuzzing**: an `oc5` *constructor* sweep of
`_pyrepl._module_completer.ImportParser`, which tokenizes import text and so drives the C
tokenizer's column-offset path. This is the **first bug attributable to OOM Phase 2**
(constructor/method coverage), in a path the module-function-only sweep could not reach.
Distinct from the other parser OOM bugs: OOM-0019 (`pegen_errors.c`
`raise_error_known_location`) and OOM-0021 (`pegen.c` `_PyPegen_run_parser` /
`set_syntax_error_metadata`) — different function, and a clean segv rather than an
abort/fatal.

## Versions

- main (3.16.0a0), commit `15d7406`. SIGSEGV on all four local builds (ft_debug_asan,
  ft_release, jit, upstream).
