"""OOM-0034 minimal reproducer (stdlib only).

Tokenizing a line containing a non-ASCII character under allocation failure
NULL-derefs in the C tokenizer's column-offset helper:

  _get_col_offsets (Python/Python-tokenize.c) calls
  _PyPegen_byte_offset_to_character_offset_line(line, ...), which does
      data = PyUnicode_AsUTF8(line);   # Parser/pegen.c:29
  and then indexes
      data[col_offset]                 # Parser/pegen.c:33
  WITHOUT checking data for NULL. Under OOM, PyUnicode_AsUTF8 fails to build/cache
  the UTF-8 form and returns NULL -> NULL dereference -> SIGSEGV on all builds.

The non-ASCII char is required: _get_col_offsets only runs when a token's byte
offset differs from its character offset.
"""
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
        try:
            remove_mem_hooks()
        except Exception:
            pass
print("done, no crash")
