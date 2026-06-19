# Title

Segfault: `iter()` on a t-string `Template` frees a partially-initialized iterator under OOM — `template_iter` (`Objects/templateobject.c`) leaves `stringsiter`/`interpolationsiter` uninitialized before the error-path `Py_DECREF`

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`template_iter()` allocates the iterator with `PyObject_GC_New`, which does **not**
zero the object body, then calls `PyObject_GetIter()` on the template's `strings`
and `interpolations`. If either allocation fails (e.g. under memory pressure), the
error path does `Py_DECREF(iter)` while `iter->stringsiter` and
`iter->interpolationsiter` are still **uninitialized**. The decref runs
`templateiter_dealloc` → `templateiter_clear`, which does
`Py_CLEAR(self->stringsiter)` on the garbage pointer → crash.

## Reproducer

Minimal, stdlib-only (needs the t-string syntax, CPython 3.14+):

```python
from _testcapi import set_nomemory, remove_mem_hooks

t = t"x{1}y{2}z"          # a PEP 750 Template

for start in range(1, 1000):
    set_nomemory(start, 0)
    try:
        try:
            iter(t)          # template_iter(): GetIter fails -> Py_DECREF(uninit iter)
        finally:
            remove_mem_hooks()
    except MemoryError:
        pass
```

Crashes (SIGSEGV) on the free-threaded debug+ASan and JIT (debug+ASan) builds. On
the non-ASan release builds it exits cleanly within the swept budget (see Notes).

## Backtrace

```
Program received signal SIGSEGV, Segmentation fault.
#0  _Py_atomic_load_uint32_relaxed at ./Include/cpython/pyatomic_gcc.h:367
#1  Py_DECREF                       at ./Include/refcount.h:345
#2  templateiter_clear              at Objects/templateobject.c:53   # Py_CLEAR(self->stringsiter), uninitialized
#3  templateiter_dealloc            at Objects/templateobject.c:45   # Py_TYPE(op)->tp_clear(op)
#4  _Py_Dealloc                     at Objects/object.c:3319
#5  Py_DECREF                       at ./Include/refcount.h:359
#6  template_iter                   at Objects/templateobject.c:232  # Py_DECREF(iter) on the stringsiter==NULL error path
#7  PyObject_GetIter                at Objects/abstract.c:2825
#8  cfunction_vectorcall_FASTCALL   at Objects/methodobject.c:449
```

The faulting object is `self->stringsiter`, never assigned (uninitialized heap from
`PyObject_GC_New`); under ASan it holds the 0xbe poison pattern, so the `Py_DECREF`
dereferences a wild pointer.

## Root cause

`Objects/templateobject.c`, `template_iter` (≈ L222-247):

```c
static PyObject *
template_iter(PyObject *op)
{
    templateobject *self = templateobject_CAST(op);
    templateiterobject *iter = PyObject_GC_New(templateiterobject, &_PyTemplateIter_Type);
    if (iter == NULL) {
        return NULL;
    }
    /* iter->stringsiter / iter->interpolationsiter are UNINITIALIZED here */

    PyObject *stringsiter = PyObject_GetIter(self->strings);
    if (stringsiter == NULL) {
        Py_DECREF(iter);          /* L232: dealloc -> tp_clear -> Py_CLEAR(garbage) */
        return NULL;
    }

    PyObject *interpolationsiter = PyObject_GetIter(self->interpolations);
    if (interpolationsiter == NULL) {
        Py_DECREF(iter);          /* same defect on the second error path */
        Py_DECREF(stringsiter);
        return NULL;
    }

    iter->stringsiter = stringsiter;          /* fields only set here, after both GetIter calls */
    iter->interpolationsiter = interpolationsiter;
    iter->from_strings = 1;
    PyObject_GC_Track(iter);
    return (PyObject *)iter;
}
```

`PyObject_GC_New` allocates but does not zero the struct body, so
`iter->stringsiter` and `iter->interpolationsiter` are indeterminate until the two
assignments near the end. Both `PyObject_GetIter` failure paths drop the last
reference to `iter` before those assignments, so `templateiter_clear`
(`Py_CLEAR(self->stringsiter); Py_CLEAR(self->interpolationsiter);`) dereferences
uninitialized memory. `tp_traverse` (`templateiter_traverse`) has the same exposure
if GC runs between allocation and field init.

## Suggested fix

Initialize the two object fields to `NULL` immediately after allocation, before any
operation that can fail and unwind:

```c
    templateiterobject *iter = PyObject_GC_New(templateiterobject, &_PyTemplateIter_Type);
    if (iter == NULL) {
        return NULL;
    }
    iter->stringsiter = NULL;
    iter->interpolationsiter = NULL;
```

(`Py_CLEAR`/`Py_VISIT` are then safe on the error paths.) Equivalently, build the two
sub-iterators into locals first and only allocate/populate `iter` once both succeed.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`). 2 fuzzing vehicles
(`importlib.resources._itertools`, `importlib.metadata._itertools`); reduced to the
3-line trigger above. **Build dependence:** the defect is an uninitialized-field read,
so observability depends on allocator state. On the ASan builds (`ft_debug_asan`,
`jit`) freshly returned memory is poisoned non-NULL → deterministic SIGSEGV. On the
non-ASan builds the first allocation often reads back as zero, so the field is NULL
and `Py_CLEAR(NULL)` is a safe no-op → no crash in the swept budget; but a
`templateiterobject` freed and re-allocated from a dirty freelist slot would carry a
stale (freed) pointer, making this a latent use-after-free on release builds too.
This is t-string (PEP 750) code, new in 3.14; the same pattern should be audited in
the sibling `template_*` constructors.

## Versions

- main (3.16.0a0), commit 15d7406. Reproduces (SIGSEGV) on free-threaded debug+ASan
  and JIT debug+ASan; exits cleanly on free-threaded release and upstream release
  (invariant of allocator state, see Notes).
