"""OOM-0023 minimal reproducer (stdlib only) -- no http.server.

subtype_dealloc (Objects/typeobject.c) tears down a pure-Python instance's slots/__dict__
without saving/restoring tstate->current_exception (the preserving wrapper exists only in the
__del__ path, slot_tp_finalize). A trivial heap-type instance with a MATERIALIZED managed dict,
held as a live local, is freed while a MemoryError unwinds the frame; the managed-dict teardown
takes the same detach-fail -> PyErr_FormatUnraisable OOM-recovery path as OOM-0018, which clears
the in-flight MemoryError, tripping the gh-89373 debug invariant
`_Py_Dealloc: Deallocator of type 'C' cleared the current exception` (Objects/object.c:3338).

The instance needs the MATERIALIZED managed dict (o.__dict__): without it the teardown does not
take the exception-clearing path (verified: dropping the o.__dict__ line -> 0/8 no crash). The
start sweep is required (the exact failing allocation index depends on swept state).

Fatal on Py_DEBUG builds (ft_debug_asan, jit); NDEBUG compiles the invariant out.
Deterministic (10/10 on debug-ft-nojit-asan @1b9fe5c). Companion to repro.py (the http.server /
argparse _StoreAction path published in the gist).
"""
import faulthandler
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

class C:
    pass

def f():
    o = C(); o.x = 1
    o.__dict__                       # materialize the managed dict
    dict(zip(range(99), range(99)))  # alloc fails under OOM -> MemoryError while o is a live local

for start in range(500):
    set_nomemory(start, 0)
    try:
        f()                          # frame unwind clears o -> subtype_dealloc clears the MemoryError
    except BaseException:
        pass
    remove_mem_hooks()
print("done, no crash")
