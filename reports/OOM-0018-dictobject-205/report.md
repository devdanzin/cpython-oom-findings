# Title

Abort: `assert(_Py_IsOwnedByCurrentThread(mp) || IS_DICT_SHARED(mp))` in `set_keys` (`Objects/dictobject.c:205`) from `PyObject_ClearManagedDict`'s OOM-recovery branch under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

On free-threaded builds, `PyObject_ClearManagedDict()` clears an object whose materialized dict still points at the object's inline values by calling `detach_dict_from_object()`, which `copy_values()`-copies the inline values out. Under OOM that copy fails and the function enters a recovery branch that rewrites `dict->ma_keys` via `set_keys(dict, Py_EMPTY_KEYS)` (`Objects/dictobject.c:7896`). Unlike every other path that rewrites `ma_keys`, this branch never marks the dict shared. When the managed-dict object is *owned by one thread but freed on another* (biased reference counting routes the free through `_Py_brc_queue_object` / `_Py_HandlePending`), `set_keys` runs on a non-owning thread on a non-shared dict, so its debug assert `_Py_IsOwnedByCurrentThread(mp) || IS_DICT_SHARED(mp)` fails and the interpreter aborts.

## Reproducer

```python
import _testcapi, faulthandler, threading, queue
faulthandler.enable()

class C: pass
q = queue.Queue()

def producer():
    for _ in range(2000):
        o = C(); o.a = 1; o.__dict__; o.b = 2   # materialize dict pointing at inline values
        q.put(o)
    q.put(None)

threading.Thread(target=producer).start()
start = 1
while True:
    o = q.get()
    if o is None: break
    _testcapi.set_nomemory(start, 0)            # fail every allocation from #start
    try:
        del o                                   # cross-thread last decref -> clear managed dict
    except MemoryError:
        pass
    finally:
        _testcapi.remove_mem_hooks()
    start = start + 1 if start < 300 else 1
```

Aborts on the free-threaded debug+ASan build, usually within seconds. The exact abort site is **racy** (`minimization: partial`): the same cross-thread-dealloc-under-OOM machinery also produces sibling aborts (a mimalloc realloc failure in the BRC merge; `_Py_Dealloc` "cleared the current exception"). About 1 run in 20 lands on the `dictobject.c:205` assert; a `set_nomemory` band of `start` 1..300 is swept so `copy_values` eventually fails at the right moment. The original fuzzer vehicle reaches the identical assert by freeing a `MagicMock`-created managed-dict object on the main eval thread under OOM.

## Backtrace

```
#8  set_keys                  Objects/dictobject.c:205    <- assert _Py_IsOwnedByCurrentThread(mp) || IS_DICT_SHARED(mp)
#9  PyObject_ClearManagedDict Objects/dictobject.c:7896   <- set_keys(dict, Py_EMPTY_KEYS) in the OOM-recovery branch
#10 subtype_dealloc           Objects/typeobject.c:2847
#11 _Py_Dealloc              Objects/object.c:3319
#12 _Py_brc_queue_object      Python/brc.c:91             <- object owned by another thread, freed here
#13 Py_DECREF                ./Include/refcount.h:363      <- cross-thread last decref
```

`set_keys` is `static inline`; in the original vehicle's faulthandler C stack it is inlined into `PyObject_ClearManagedDict+0x8be`, with the free running on the main thread via `_Py_HandlePending` (BRC merge).

## Root cause

`Objects/dictobject.c`, `PyObject_ClearManagedDict()` (L7865), the `detach_dict_from_object()`-failed branch:

```c
    Py_BEGIN_CRITICAL_SECTION(dict);
    err = detach_dict_from_object(dict, obj);   /* L7885: copy_values() fails under OOM -> -1 */
    Py_END_CRITICAL_SECTION();
    if (err) {
        assert(PyErr_Occurred() == PyExc_MemoryError);
        PyErr_FormatUnraisable(...);
        Py_BEGIN_CRITICAL_SECTION(dict);
        PyDictKeysObject *oldkeys = dict->ma_keys;
        set_keys(dict, Py_EMPTY_KEYS);                  /* L7896: rewrites ma_keys WITHOUT marking shared */
        dict->ma_values = NULL;
        dictkeys_decref(oldkeys, IS_DICT_SHARED(dict)); /* L7898: same wrong shared flag */
        STORE_USED(dict, 0);
        clear_inline_values(_PyObject_InlineValues(obj));
        Py_END_CRITICAL_SECTION();
    }
```

`set_keys()` (L202) asserts `_Py_IsOwnedByCurrentThread((PyObject *)mp) || IS_DICT_SHARED(mp)` (L205). Every other site that rewrites `ma_keys` -- `dictresize` (L2167), `clear` (L3098), update (L4144) -- first calls `ensure_shared_on_resize(mp)` (L1418), which marks a dict that isn't owned by the current thread as `DICT_SHARED`. This recovery branch, added in commit `6c450f44c283`, skips that step. Because the object is freed via biased reference counting on a thread other than its owner, `_Py_IsOwnedByCurrentThread(dict)` is false and the dict was never marked shared, so the invariant is violated. It is a missing "mark shared before resize", not a use-after-free.

## Suggested fix

Mark the dict shared before rewriting `ma_keys`, mirroring the normal resize paths. Inside the recovery critical section, just before `set_keys`:

```c
    Py_BEGIN_CRITICAL_SECTION(dict);
    PyDictKeysObject *oldkeys = dict->ma_keys;
    ensure_shared_on_resize(dict);     /* <-- add: marks DICT_SHARED if not owned by current thread */
    set_keys(dict, Py_EMPTY_KEYS);
    dict->ma_values = NULL;
    dictkeys_decref(oldkeys, IS_DICT_SHARED(dict));   /* now sees the correct shared flag */
    ...
```

This also corrects the `IS_DICT_SHARED(dict)` argument to `dictkeys_decref` (L7898), so the old keys are freed with the proper QSBR delay protecting concurrent lock-free readers.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). Free-threading-specific: `set_keys`'s ownership assert and the `_Py_IsOwnedByCurrentThread`/`IS_DICT_SHARED` machinery only exist under `Py_GIL_DISABLED` (the non-FT `set_keys` at L270 is a bare `mp->ma_keys = keys`). Reproduces as an **abort only on the FT debug build** -- the FT release build defines `NDEBUG`, so the assert is compiled out, but the same branch then rewrites `ma_keys` and decrefs the old keys with the wrong `IS_DICT_SHARED()` value, skipping the QSBR delay (a latent memory-safety hazard for concurrent readers, not just a debug assert). GIL builds (`jit`, `upstream`) lack the field and the assert entirely and run the reproducer cleanly. Per the OOM-catalog convention for assert-based aborts, non-debug builds are recorded as `n/a`.

The abort is inherently racy: the trigger requires a managed-dict object (a) owned by one thread, (b) freed on another, while (c) `copy_values` inside `detach_dict_from_object` fails under OOM. The same cross-thread-dealloc-under-OOM window also produces sibling aborts (mimalloc realloc failure during the BRC merge; `_Py_Dealloc` "cleared the current exception"); only some runs land on `dictobject.c:205`. Minimization is therefore **partial** (vehicle-style threaded reproducer). Three fuzzer vehicles (`wsgiref_util`, `pickletools`, `sched`) all abort at the identical `dictobject.c:205` assertion, each constructing a `MagicMock()` under an OOM sweep with fuzzer threads running.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build. Release/JIT/upstream builds: assertion compiled out / not present (`n/a`). Recovery branch introduced in commit `6c450f44c283`.
