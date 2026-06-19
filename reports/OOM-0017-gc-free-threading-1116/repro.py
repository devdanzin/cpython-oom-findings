"""OOM-0017 minimal reproducer (stdlib only) — reduced from the socket fuzz vehicle with shrinkray.

`socket.recv_fds` internally builds an `array.array("i")` for the received FD list. Under a
dense allocation-failure sweep that construction repeatedly fails partway: newarrayobject
(Modules/arraymodule.c:770) takes a *deferred* reference to the `array.array` TYPE via
tp_alloc, then PyMem_NEW fails (L782) and array_dealloc unconditionally drops a *real*
reference to the type (Py_DECREF(tp), L848). The deferred-vs-strong mismatch leaves the
`array.array` type object's refcount a few counts too small. The corruption is silent until
interpreter shutdown, when the free-threaded cyclic GC's update_refs/visit_decref tally
drives the type's gc_refs below zero and the debug assertion
`gc_get_refs(op) >= 0` in validate_gc_objects (Python/gc_free_threading.c:1116) aborts.

Requires a free-threaded debug build (PYTHON_GIL=0). Reliable (~75%/run; aborts within a
couple of runs). The jit (GIL) debug build aborts on the same imbalance at Python/gc.c:96
(gc_decref); ft_release / upstream compile the assert out (NDEBUG) — the imbalance is latent.

NOTE: the abort happens during *interpreter shutdown GC*, after the module body finishes —
so the "body done" line below prints and the process then aborts on its way out.

shrinkray disproved the earlier belief that the fuzzer boilerplate's "allocation baseline"
was load-bearing: the bare `socket.recv_fds(0, 0, 0)` sweep reproduces on its own. The full
fuzzer vehicle is preserved as `vehicle_source.py`.
"""
import socket
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(259):
    set_nomemory(start)
    try:
        try:
            socket.recv_fds(0, 0, 0)
        finally:
            remove_mem_hooks()
    except:
        pass

print("body done — process now aborts during shutdown GC")
