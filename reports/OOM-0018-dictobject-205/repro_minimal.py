"""OOM-0018 minimal reproducer (stdlib only) -- no unittest.mock.

PyObject_ClearManagedDict's OOM-recovery branch calls set_keys(dict, Py_EMPTY_KEYS)
(dictobject.c:7896) when detach_dict_from_object fails under memory pressure, without
re-establishing the ownership/shared invariant set_keys asserts (dictobject.c:205,
_Py_IsOwnedByCurrentThread || IS_DICT_SHARED). The shutdown cyclic GC clears a managed-dict
object under active OOM and trips the assert.

The buggy branch only runs for a MATERIALIZED managed dict (via o.__dict__) whose ma_values
still point at the inline values -- a bare instance has _PyObject_GetManagedDict()==NULL and
takes the harmless early return (verified: removing the `o.__dict__` line -> no crash, 0/8).
Free-threading + debug only (the assert is Py_GIL_DISABLED + Py_DEBUG).

Because the crash is in the SHUTDOWN cyclic GC it cannot be swept; a fixed set_nomemory(1) is
used (the failing detach_dict_from_object allocation is ~the second allocation during shutdown
for this minimal object -- far earlier than the MagicMock vehicle's N~200 window, which did
much more setup). Deterministic (10/10 on debug-ft-nojit-asan @1b9fe5c, PYTHON_GIL=0).

Companion to repro.py (the unittest.mock.MagicMock path published in the gist).
"""
from _testcapi import set_nomemory

class C:
    pass

o = C()
o.self = o          # inline value + self-cycle: survives to the shutdown cyclic GC
o.__dict__          # MATERIALIZE the managed dict (ma_values -> inline values)
set_nomemory(1)     # armed at shutdown: detach_dict_from_object fails -> set_keys recovery -> assert
