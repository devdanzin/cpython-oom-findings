"""OOM-0029: negative refcount on a MemoryError under OOM (over-decref).

A MemoryError is decref'd one time too many on an allocation-failure path; the
negative refcount is detected later by _Py_NegativeRefcount (Objects/object.c:275)
when the object is freed again during an unrelated dealloc cascade
(list_dealloc -> subtype_dealloc -> tuple_dealloc) -> abort on debug builds.

NOT minimized: the defect is an unbalanced MemoryError decref whose exact site isn't
isolated from one vehicle. Reproduce via the fuzzing vehicle
(~/crashers/_pyrepl_utils-sigabrt-assertion-oomNEW/source.py): it fuzzes _pyrepl.utils
functions (gen_colors_from_token_stream, iter_display_chars, _ascii_control_repr, ...)
inside a dense _testcapi.set_nomemory sweep. Deterministic abort on a debug build
(ft_debug_asan / jit); the _Py_NegativeRefcount detector is compiled out on release.

Shape of the vehicle:

    from _testcapi import set_nomemory, remove_mem_hooks
    import _pyrepl.utils as m
    for start in range(1000):
        set_nomemory(start, 0)
        try:
            try:
                <call m.<func>(...) -- see the vehicle's oom_call() wrappers>
            finally:
                remove_mem_hooks()
        except BaseException:
            pass
"""
