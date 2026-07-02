"""OOM-0043 -- _blake2.blake2s().copy() under allocation failure crashes on a
half-built object whose `impl` discriminant was never initialised.

NOT stdlib-only: the failing allocation is HACL*'s raw malloc() for the copy's
hash state, which _testcapi.set_nomemory (a PyMem hook) cannot reach. The failure
must be injected at the C malloc layer, so this repro needs the LD_PRELOAD shim
(fusil_malloc_shim.c in this directory -- fusil's --oom-foreign injector).

Build + run (deterministic on a debug build -> Fatal Python error, SIGABRT):

    cc -shared -fPIC -O2 -o shim.so fusil_malloc_shim.c -ldl
    LD_PRELOAD=./shim.so <python> repro.py

fusil_malloc_arm(start, stop) is a drop-in for set_nomemory: it fails allocations
numbered [start, stop). We create the object unarmed, then arm(0, 1) so that the
*first* malloc the copy makes -- the HACL state allocation -- returns NULL.

NB: this needs a NON-ASan build. Under ASan the LD_PRELOAD shim is bypassed
(ASan owns malloc), so no failure is injected and the bug is not reached.
"""

import ctypes
import faulthandler

faulthandler.enable()

import _blake2

lib = ctypes.CDLL(None)
lib.fusil_malloc_arm.argtypes = [ctypes.c_long, ctypes.c_long]
lib.fusil_malloc_arm.restype = None

h = _blake2.blake2s(b"warmup")   # succeeds (unarmed)
lib.fusil_malloc_arm(0, 1)       # fail exactly the next malloc: the HACL state copy
h.copy()                         # -> copy error path never sets cpy->impl -> Py_DECREF
                                 #    -> py_blake2_clear reads uninitialised impl -> fatal
