"""
Minimal-ish reproducer: abort on
    assert(_Py_IsOwnedByCurrentThread((PyObject *)mp) || IS_DICT_SHARED(mp))
in set_keys() (Objects/dictobject.c:205), reached from the OOM-recovery branch of
PyObject_ClearManagedDict() (Objects/dictobject.c:7896).

Affected:   CPython 3.16.0a0 (main), free-threaded (Py_GIL_DISABLED) builds only.
            The assertion is compiled in on free-threaded DEBUG builds; release
            builds define NDEBUG so assert() is a no-op (see Notes). GIL builds do
            not have the assert or the ownership concept at all.
Crash:      SIGABRT, Objects/dictobject.c:205
            Assertion `_Py_IsOwnedByCurrentThread((PyObject *)mp) || IS_DICT_SHARED(mp)' failed.
Requires:   a free-threaded debug build exposing _testcapi.set_nomemory.

Run:
    python repro.py
    # aborts (rc 134) on the FT debug+ASan build, usually within a few seconds.

Backtrace (gdb, asserting thread):
    #8  set_keys                  Objects/dictobject.c:205   (assert owned-or-shared)
    #9  PyObject_ClearManagedDict Objects/dictobject.c:7896  (set_keys(dict, Py_EMPTY_KEYS) in OOM recovery)
    #10 subtype_dealloc           Objects/typeobject.c:2847
    #11 _Py_Dealloc              Objects/object.c:3319
    #12 _Py_brc_queue_object      Python/brc.c:91            (object owned by another thread)
    #13 Py_DECREF                ./Include/refcount.h:363    (cross-thread last decref)

Root cause (Objects/dictobject.c):

    PyObject_ClearManagedDict() (L7865) clears an object whose materialized dict
    still points at the object's inline values. It calls detach_dict_from_object()
    (L7885) which must copy_values() the inline values into a standalone block.
    Under OOM that copy_values() fails (L7850) and detach returns -1, so the
    function enters its recovery branch (L7888):

        Py_BEGIN_CRITICAL_SECTION(dict);
        PyDictKeysObject *oldkeys = dict->ma_keys;
        set_keys(dict, Py_EMPTY_KEYS);                     // L7896
        dict->ma_values = NULL;
        dictkeys_decref(oldkeys, IS_DICT_SHARED(dict));    // L7898
        ...
        Py_END_CRITICAL_SECTION();

    set_keys() asserts that the dict is either owned by the current thread or has
    been marked DICT_SHARED. Every other code path that rewrites ma_keys (dictresize,
    insertdict, clear) first calls ensure_shared_on_resize(mp), which marks a
    non-owned dict shared. This recovery branch does NOT. When the managed-dict
    object is owned by thread A but its last reference is dropped on thread B
    (biased reference counting routes the free through _Py_brc_queue_object /
    _Py_HandlePending), the dealloc -- and this set_keys -- runs on a thread that
    does not own the dict and the dict was never shared, so the assert fires.

    (On a release FT build the assert is compiled out, but the same branch then
    rewrites ma_keys and decrefs the old keys with the wrong IS_DICT_SHARED()
    value, skipping the QSBR delay that protects concurrent lock-free readers --
    a latent free-threading memory-safety hazard, not just a debug assert.)

Why threads + a sweep: the object must be (a) created/owned by one thread, then
(b) freed on another thread, while (c) copy_values() inside detach fails under
OOM. The reproducer below makes a producer thread mint managed-dict objects whose
real dict points at inline values, then frees them on the main thread while an OOM
sweep is active. The crash is inherently racy (other OOM-driven aborts can win the
race in a given run); minimization is therefore "partial" / vehicle-style.

Likely fix: mark the dict shared before rewriting ma_keys in the recovery branch,
i.e. call ensure_shared_on_resize(dict) (or SET_DICT_SHARED(dict)) just before
set_keys(dict, Py_EMPTY_KEYS) at L7896, exactly as the normal resize paths do.
"""
import _testcapi
import faulthandler
import threading
import queue
import sys

faulthandler.enable()


class C:
    pass


q = queue.Queue()


def producer():
    # Mint objects whose materialized __dict__ still points at the inline values,
    # owned by THIS (producer) thread, and hand them to the main thread to free.
    for _ in range(2000):
        o = C()
        o.a = 1
        o.__dict__       # materialize a real dict that points at inline values
        o.b = 2
        q.put(o)
    q.put(None)


t = threading.Thread(target=producer)
t.start()

start = 1
while True:
    o = q.get()
    if o is None:
        break
    _testcapi.set_nomemory(start, 0)   # fail every allocation from #start onward
    try:
        del o            # cross-thread last decref -> dealloc -> PyObject_ClearManagedDict
                         # -> detach_dict_from_object's copy_values fails -> recovery
                         # branch -> set_keys on a non-owned, non-shared dict -> assert
    except MemoryError:
        pass
    finally:
        _testcapi.remove_mem_hooks()
    start += 1
    if start > 300:      # sweep a band of OOM budgets so copy_values eventually fails
        start = 1
t.join()
print("done (no crash this run; re-run -- the abort is racy)")
