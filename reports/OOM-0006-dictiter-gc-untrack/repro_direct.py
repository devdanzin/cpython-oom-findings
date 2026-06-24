"""OOM-0006 direct minimal reproducer (stdlib only, no _strptime).

The most-direct trigger: iter(d.items()) under the set_nomemory sweep, after draining the
size-2 tuple freelist. dictiter_new() builds the item-iterator's di_result placeholder via
_PyTuple_FromPairSteal(None, None) -- a 2-tuple normally served from the freelist, which
bypasses the set_nomemory hook (that's why a bare iter(d.items()) sweep never failed).
Holding a list of live 2-tuples empties that freelist, so di_result's allocation actually
reaches the failing allocator; dictiter_new then Py_DECREF's the still-untracked iterator
and dictiter_dealloc untracks a never-tracked object -> abort (debug) / GC-list corruption
-> later SEGV (release).

Deterministic (verified 8/8 on debug-ft-nojit-asan @1b9fe5c; crashes ~start=2 there). Use
the iter() builtin (not the GET_ITER bytecode) to keep the di==NULL rung clean and avoid
the neighbouring PyStackRef_XCLOSE negrefcount bug. The range(16) sweep absorbs the
per-build allocation offset.

Companion to repro.py (the realistic _strptime path, which is what the gist publishes).
"""
import faulthandler
faulthandler.enable()
from _testcapi import set_nomemory

d = {}
keep = [(x, x) for x in range(500)]   # drain the size-2 tuple freelist -- MUST stay referenced
for start in range(16):               # if `keep` is freed, its 2-tuples flood the freelist again
    set_nomemory(start)
    try:
        iter(d.items())
    except BaseException:
        pass
print("done, no crash")
