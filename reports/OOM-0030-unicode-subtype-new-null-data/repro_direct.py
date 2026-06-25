"""OOM-0030 direct minimal reproducer (stdlib only) -- no email.

The most-direct trigger: instantiate a `str` subclass under the set_nomemory sweep.
`unicode_subtype_new` allocates `self` (tp_alloc) then its data buffer; if the data-buffer
alloc fails under OOM it jumps to onError -> Py_DECREF(self) with self->data still NULL ->
unicode_dealloc -> unicode_is_singleton -> _PyUnicode_NONCOMPACT_DATA asserts `data != NULL`
(Include/cpython/unicodeobject.h:272). SIGABRT on debug builds; NULL-deref/UAF on release.

The instance must be NON-EMPTY so a data buffer is actually allocated: `S("\\x00")` and `S("a")`
both reproduce (the character is irrelevant -- the "\\x00" here only mirrors the email vehicle's
trigger), whereas `S("")` returns the interned empty-string singleton and never allocates, so it
does not crash. The `start` sweep is what lands the data-buffer alloc failure inside
`unicode_subtype_new`; an earlier hand reduction that fixed a single start simply missed the
window, which is why the vehicle was originally reduced (via shrinkray) to `email.get_value`.

Deterministic (10/10 on debug-ft-nojit-asan @1b9fe5c). Companion to repro.py (the realistic
`email._header_value_parser.get_value` path, which is the form published in the gist).
"""
import faulthandler
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

class S(str):                              # str subclass -> unicode_subtype_new path
    pass

for start in range(0, 80):
    try:
        set_nomemory(start, 0)
        try:
            S("\x00")                      # data-buffer alloc fails -> NULL-data str subclass freed
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
    finally:
        try:
            remove_mem_hooks()
        except Exception:
            pass
print("done, no crash")
