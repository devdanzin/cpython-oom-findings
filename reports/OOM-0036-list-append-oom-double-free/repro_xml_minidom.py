"""OOM-0036 alternate reproducer (stdlib only) -- xml.dom.minidom.parse(0) under a set_nomemory sweep.

A simple stdlib trigger for the _CALL_LIST_APPEND list.append-under-OOM double-free: parsing
under the allocation-failure sweep runs a `list.append` whose grow fails, and the specialized
_CALL_LIST_APPEND uop steals the item then ERROR_NO_POP leaves the dead stackref on the value
stack, which a later XCLOSE (exception_unwind / frame teardown) closes a second time -> the item
is over-decref'd / double-freed. Aborts with `_Py_NegativeRefcount` on debug builds; latent
UAF / SIGSEGV on release.

PROVENANCE: this was previously filed under OOM-0005 as its minimal repro. `rr` reverse-execution
(2026-06-24) showed its crash is driven by `_PyList_AppendTakeRefListResize` (Objects/listobject.c:531)
from `_CALL_LIST_APPEND` (generated_cases.c.h:3981) -- i.e. THIS bug (OOM-0036), not OOM-0005's
distinct frame-locals over-decref -- so it was moved here. Deterministic (20/20 PYTHON_GIL=1,
8/8 PYTHON_GIL=0 on ft_debug_asan). See the pure-Python repro.py for the minimal __slots__ form.
"""
import xml.dom.minidom
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(100):
    set_nomemory(start, 0)
    try:
        try:
            xml.dom.minidom.parse(0)
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
