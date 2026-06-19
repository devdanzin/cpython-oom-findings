"""OOM-0032 minimal reproducer (stdlib only).

A warning emitted while an allocation failure (set_nomemory) is active drives the
warnings C path (do_warn -> warn_explicit) into message-normalization with a
MemoryError already pending. warn_explicit then normalizes the message with an
exception set, tripping the debug-only invariant assert `!_PyErr_Occurred(tstate)`:
  - Warning-instance message -> PyObject_Str  (Objects/object.c:818)      [this repro]
  - plain-string message      -> type_call    (Objects/typeobject.c:2441) [fleet vehicle]
Both are the same bug. Debug builds abort; on release the lost exception is a latent
invariant violation (the same vehicle then segfaults in do_warn, = OOM-0001).
"""
import warnings, faulthandler
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks
warnings.simplefilter("always")
for start in range(0, 600):
    try:
        set_nomemory(start, 0)
        warnings.warn(UserWarning("oom-%d" % start))   # Warning instance -> PyObject_Str branch
    except MemoryError:
        pass
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
print("done, no assert")
