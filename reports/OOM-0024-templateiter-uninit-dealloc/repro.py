"""OOM-0024: iter() on a t-string Template frees a partially-initialized iterator.

template_iter() (Objects/templateobject.c) allocates the iterator with
PyObject_GC_New (which does NOT zero the struct body), then calls PyObject_GetIter()
on the template's strings/interpolations. If that allocation fails under memory
pressure, the error path runs Py_DECREF(iter) while iter->stringsiter and
iter->interpolationsiter are still uninitialized -> templateiter_dealloc ->
templateiter_clear -> Py_CLEAR(garbage) -> SIGSEGV.

Needs CPython 3.14+ (t-string / PEP 750 syntax) and a build where _testcapi is
importable. Deterministic crash on ASan builds; see report.md for build dependence.
"""
from _testcapi import set_nomemory, remove_mem_hooks

t = t"x{1}y{2}z"          # a PEP 750 Template

for start in range(1, 1000):
    set_nomemory(start, 0)
    try:
        try:
            iter(t)
        finally:
            remove_mem_hooks()
    except MemoryError:
        pass
