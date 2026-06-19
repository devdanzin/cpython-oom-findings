# Title

Segfault / negative-refcount: a module import under OOM over-decrefs a `sys.path` entry — `PyType_IsSubtype` (`Objects/typeobject.c:2931`) reads a freed entry's garbage type, or `list_ass_slice` (`Objects/listobject.c:1030`) decrefs it again

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

With `sys.path` holding mortal string entries, running a module import under memory
pressure makes the path-based finder **over-decref a `sys.path` entry**. The freed /
over-decreffed entry then surfaces in one of two places:

- **Segfault** — `PathFinder._get_spec` iterates `sys.path` and does
  `isinstance(entry, str)`; `entry`'s `ob_type` is now garbage, so
  `object_isinstance → PyObject_TypeCheck → PyType_IsSubtype(Py_TYPE(entry), str)`
  dereferences `a->tp_mro` on a bad pointer (`typeobject.c:2931`). (Faulting read at an
  address like `0x03e9........` — a small count value bled into the type pointer.)
- **Negative refcount abort** — the next list slice-assignment decrefs the same entry
  again as a *recycled* old element, tripping `_Py_NegativeRefcount` at the
  recycle-cleanup loop of `list_ass_slice_lock_held` (`listobject.c:1030`).

Two faces of one over-decref. On a debug build the negrefcount check fires first (abort);
on release/jit/upstream the corruption flows downstream to the `PyType_IsSubtype` segv.

## Reproducer

Minimal, stdlib-only, **deterministic** (6/6 on the free-threaded debug+ASan build):

```python
import sys, faulthandler
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks
saved = list(sys.path)
S = "轆ﰲ匀漏㗢攥㥔䘧ꝺᲮ緧"
for start in range(0, 1000):
    try:
        set_nomemory(start, 0)
        try:
            sys.path[:] = S        # sys.path becomes a list of mortal 1-char strings
            __import__("H")        # path finder walks the new sys.path under OOM
        finally:
            remove_mem_hooks()
    except (MemoryError, ImportError):
        pass
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
        try: sys.path[:] = saved   # restore
        except Exception: pass
```

The `__import__` is **required**: `sys.path[:] = S` *alone* (no import) does not crash
(5/5), so the over-decref producer is the import's path-based finder walking `sys.path`
under OOM, not the slice assignment itself. Small-int entries do **not** expose it (small
ints are immortal, so an over-decref is a no-op) — mortal entries (path strings) are needed.

The fleet vehicle (`vehicle_source.py`) reaches the same path via
`multiprocessing.forkserver._handle_preload(preload="H//", main_path=None,
sys_path="轆...")`: `_handle_preload` runs `sys.path[:] = sys_path` (a string → a list
of 1-char strings) and then `__import__` of each char.

## Backtrace

Segv face (vehicle / release builds):

```
Fatal Python error: Segmentation fault            # READ at 0x03e9........
#5  PyType_IsSubtype           Objects/typeobject.c:2931   # is_subtype_with_mro(a->tp_mro, ...), a = Py_TYPE(freed entry)
#7  object_isinstance          Objects/abstract.c:2608
#13 PyObject_CallMethodObjArgs  Objects/call.c:960
#14 import_find_and_load        Python/import.c:4133
#16 builtin___import__          Python/bltinmodule.c:286
Python: _get_spec (importlib._bootstrap_external:1240, `if not isinstance(entry, str)`)
```

Negrefcount face (debug / minimal repro):

```
Fatal Python error: _Py_NegativeRefcount: object has negative ref count
#12 list_ass_slice_lock_held    Objects/listobject.c:1030   # Py_XDECREF(recycle[k]); -- recycled old element
#14 list_ass_subscript          Objects/listobject.c:3902
#15 PyObject_SetItem            Objects/abstract.c:245      # STORE_SUBSCR: sys.path[:] = ...
```

## Root cause

A module import under allocation failure over-decrefs a `sys.path` entry. The
path-based finder (`PathFinder._get_spec`, `importlib._bootstrap_external`) walks
`sys.path`, consulting `sys.path_importer_cache` / `sys.path_hooks`; somewhere on that
path an unchecked allocation failure leaves an entry's refcount one too low (a borrowed
reference decreffed, or a decref on an error path that the caller also performs). The
defect is **not** in `list_ass_slice` — that function is the *detector* (its
recycle-cleanup `Py_XDECREF(recycle[k])` at `listobject.c:1030` is simply the next thing
to touch the already-freed entry). The exact over-decref line inside the import machinery
is **not yet pinned** (root-cause partial); the mechanism, both detection sites, and a
deterministic reproducer are established.

## Suggested fix

Audit the path-based finder's handling of `sys.path` entries under allocation failure
(`PathFinder._get_spec` / `_path_importer_cache` / `_path_hooks` and the C import glue
`import_find_and_load`) for a reference-count error on the OOM error path — a borrowed
`sys.path` entry decreffed, or an entry decreffed on both an error path and by its owner.
Pinning it wants a refcount watchpoint on the entry that goes negative.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`) by the local systemd fleet
(`multiprocessing.forkserver` target), flagged `oomNEW`. **This is the "import-time
`PyType_IsSubtype` outlier" that was NOREPRO on the host** (see
`catalog/norepro_investigation.md`) — now locally reproduced and root-caused to the
import/`sys.path` over-decref. Vehicle-discovered but **reduced to a deterministic public
minimal repro** (list slice-assignment of a string into `sys.path` + an import under OOM).
Distinct from OOM-0004 (`list_dealloc`/`PyList_New`/`free_list_items`) and from the other
negative-refcount bugs OOM-0005/0019/0029 (different sites). The vehicle is a
multi-bug/flaky vehicle: a plain run usually shows the `PyType_IsSubtype` segv (~10–20%),
a gdb run drifts to the `list_ass_slice` negrefcount — both are this bug.

## Versions

- main (3.16.0a0), commit `15d7406`. Repro matrix: `ft_debug_asan` abort (negrefcount),
  `jit` segv, `upstream` segv, `ft_release` no-crash (this run).
