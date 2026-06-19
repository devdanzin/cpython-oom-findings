"""OOM-0018 minimal reproducer (stdlib only) — reduced from the wsgiref.util fuzz vehicle with shrinkray.

A free-threaded build's managed-dict teardown has an unsafe OOM-recovery branch:
`PyObject_ClearManagedDict` (Objects/dictobject.c:7896), when `detach_dict_from_object` fails
under memory pressure, calls `set_keys(dict, Py_EMPTY_KEYS)` — but `set_keys` asserts
`_Py_IsOwnedByCurrentThread(mp) || IS_DICT_SHARED(mp)` (dictobject.c:205), a precondition the
recovery path does not re-establish. Under OOM this aborts on debug builds; on release it
clears the dict without the ownership/shared invariant.

This hits that branch deterministically via the cyclic GC: a MagicMock (which has a managed
`__dict__`) is abandoned into a traceback reference cycle, so it survives to interpreter
shutdown; with allocation failure still armed, the shutdown GC's clear path
(`delete_garbage -> subtype_clear -> PyObject_ClearManagedDict`) takes the OOM-recovery branch
and trips the assert. This is the SAME path the full vehicle takes on a normal run (8/8 under
gdb); the cross-thread dealloc path (`_Py_brc_queue_object`) the report also shows is a rare
alternate route to the identical assert/branch.

Requires a free-threaded debug build (PYTHON_GIL=0). Deterministic (30/30). The
`set_nomemory(N)` argument must land the failing allocation inside the shutdown GC: the
working window is roughly N in [113, 900] on this build (N=200 is comfortably central); too
small fails during setup, too large (e.g. 999) overshoots shutdown. NOT tied to the small-int
cache — tested N=254..258 across the 256 boundary, no effect. Full vehicle: vehicle_source.py.
"""
from unittest.mock import MagicMock
from _testcapi import set_nomemory

set_nomemory(200)              # fail allocations from the 200th onward (lands in shutdown GC)
(MagicMock(), undefined_name)  # build a MagicMock, then NameError abandons it into a traceback
                               # cycle -> survives to shutdown GC, cleared there under active OOM
