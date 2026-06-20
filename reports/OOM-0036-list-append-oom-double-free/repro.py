"""OOM-0036: list.append(x) under OOM double-frees the appended item.

Root cause is in the specialized _CALL_LIST_APPEND bytecode (Python/bytecodes.c):

    int err = _PyList_AppendTakeRef((PyListObject *)self_o, PyStackRef_AsPyObjectSteal(arg));
    if (err) { ERROR_NO_POP(); }

`arg` (the appended item) is STOLEN; when the list has to grow and `list_resize` fails
under OOM, `_PyList_AppendTakeRef` decrefs the item (listobject.c:531) -- consuming the
stolen ref. But the uop then takes ERROR_NO_POP(), leaving the already-consumed `arg`
stackref on the value stack; the eval loop's `exception_unwind` then PyStackRef_XCLOSEs it
(generated_cases.c.h:13857) -> the item is decreffed a SECOND time -> double-free.

If the item is referenced elsewhere (a __slots__ attribute here, an os.DirEntry field in
the original fleet vehicle), the double-free becomes a use-after-free, detected when that
other holder is later cleared: _Py_NegativeRefcount abort on debug/JIT builds, SIGSEGV on
the upstream release build.

Deterministic on the debug build (GIL on and off). The warm-up f() is load-bearing: it
specializes `out.append(e.a)` to CALL_LIST_APPEND (and builds the code objects so the more
common OOM-0003 doesn't mask this). Pure Python -- no os.scandir, no filesystem, no C type;
`os.DirEntry` was only the object that happened to be on the stack when this was first found.
"""
from _testcapi import set_nomemory, remove_mem_hooks


class E:                            # any object holding a second reference to the item works
    __slots__ = ("a",)
    def __init__(self, a):
        self.a = a


def f():
    items = [E(str(i) + "_value") for i in range(200)]   # E.a holds the only other ref
    out = []
    for e in items:
        out.append(e.a)             # CALL_LIST_APPEND; under OOM the grow fails -> double-free of e.a


f()                                  # warm-up: specialize CALL_LIST_APPEND + build code objects
for start in range(1500):
    set_nomemory(start, start + 1)   # fail one allocation at #start, then resume
    try:
        try:
            f()
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
