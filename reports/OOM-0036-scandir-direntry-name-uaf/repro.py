"""OOM-0036: use-after-free of an os.DirEntry's name string under OOM.

Walking a directory tree with os.scandir while allocations intermittently fail leaves an
os.DirEntry whose `name` (a str) has already been freed; when that DirEntry is later
deallocated, DirEntry_dealloc Py_XDECREFs the dangling pointer:

    _Py_NegativeRefcount  (Objects/object.c:275)
      <- Py_XDECREF(entry->name)  in DirEntry_dealloc  (Modules/posixmodule.c:16199)

-> abort on a debug/JIT build (the negative-refcount assert), SIGSEGV on the upstream
release build (the assert is compiled out under NDEBUG; the UAF is latent).

Deterministic on the ft_debug_asan build, GIL on and off, window 1 or fail-forever.

The warm-up walk() is load-bearing: without it the much more common
code_dealloc/_co_unique_id crash (OOM-0003) fires first under OOM and masks this one
(this is why the single-call OOM harness never surfaced it -- it needs to get *past* that
shallow crash, which the windowed/sequence harness does).
"""
import os
from _testcapi import set_nomemory, remove_mem_hooks

TREE = "/usr/share/zoneinfo"   # any directory tree with enough entries works


def walk(top):
    stack = [top]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in entries:
            stack.append(e.path)   # recurse; os.scandir on a file just raises (caught)


def main():
    walk(TREE)                              # warm-up: build code objects so OOM-0003 can't mask this
    for start in range(600):
        set_nomemory(start, start + 1)      # fail the allocation at #start, then resume
        try:
            try:
                walk(TREE)
            finally:
                remove_mem_hooks()
        except BaseException:
            pass


if __name__ == "__main__":
    main()
