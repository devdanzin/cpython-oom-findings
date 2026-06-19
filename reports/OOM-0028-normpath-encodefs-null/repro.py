"""OOM-0028: os._path_normpath(bytes) NULL-derefs under OOM.

os__path_normpath_impl (Modules/posixmodule.c:6149) builds `result` with
PyUnicode_FromOrdinal/PyUnicode_FromWideChar (either can return NULL under OOM), then
-- for a bytes input -- re-encodes via Py_SETREF(result, PyUnicode_EncodeFSDefault(result))
WITHOUT checking result for NULL. PyUnicode_EncodeFSDefault(NULL) -> unicode_encode_utf8(NULL)
-> PyUnicode_Check(NULL)->ob_type -> SIGSEGV.

Reproduces on every build (plain NULL deref, not a debug/ASan-only artifact).
posix._path_normpath is the C accelerator; a bytes arg is required for the crash branch.
"""
import posix
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(1, 2000):
    set_nomemory(start, 0)
    try:
        try:
            posix._path_normpath(b"foo//bar/../baz")
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
