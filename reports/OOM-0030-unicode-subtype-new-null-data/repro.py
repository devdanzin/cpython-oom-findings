"""OOM-0030: str-subclass instantiation under OOM frees a unicode with NULL data.

unicode_subtype_new (Objects/unicodeobject.c) allocates the subclass instance `self`
first, then allocates its data buffer; if a later allocation fails under OOM it jumps to
`onError: Py_DECREF(self)` while self->data is still NULL -> unicode_dealloc ->
unicode_is_singleton -> _PyUnicode_NONCOMPACT_DATA asserts `data != NULL` -> abort
(debug builds; NULL deref on release).

Minimization PARTIAL/vehicle-confirmed: this reduction exercises unicode_subtype_new but
did not hit the exact allocation-failure window in budget. Reliable reproducer is
`vehicle_source.py` (fusil fuzzing email._header_value_parser, which builds str
subclasses, under the set_nomemory sweep) -- deterministic abort on ft_debug_asan / jit.
"""
from _testcapi import set_nomemory, remove_mem_hooks


class S(str):
    pass


for start in range(1, 3000):
    set_nomemory(start, 0)
    try:
        try:
            S("abcdefghij")          # str.__new__ for a subclass -> unicode_subtype_new
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
