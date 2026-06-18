"""
Minimal reproducer: Py_DECREF(NULL) segfault in PyContextVar_Set under OOM.

Affected:   CPython 3.16.0a0 (main). Build-agnostic: reproduces on free-threaded
            and default (GIL) builds, debug and release.
Crash:      SIGSEGV in Py_DECREF(tok) with tok == NULL, Python/context.c:367.
Requires:   a build exposing _testcapi.set_nomemory (debug/test builds).

Run:
    python repro_contextvar_set_oom_minimal.py
    # exits via SIGSEGV (rc 139, or rc 1 under ASan)

Backtrace (gdb):
    #0 _Py_atomic_load_uint32_relaxed
    #1 Py_DECREF              Include/refcount.h:345   (op == 0x0)
    #2 PyContextVar_Set       Python/context.c:367     (Py_DECREF(tok), tok == NULL)

Root cause (Python/context.c, PyContextVar_Set, ~L346):

    PyContextToken *tok = token_new(ctx, var, old_val);  /* L363: may return NULL (OOM), UNCHECKED */
    Py_XDECREF(old_val);
    if (contextvar_set(var, val)) {                      /* L366: also fails under OOM */
        Py_DECREF(tok);                                  /* L367: tok == NULL -> SIGSEGV */
        return NULL;
    }
    return (PyObject *)tok;

token_new() can return NULL under allocation failure, but its result is not
NULL-checked. The reproducer sweeps the OOM budget so that the earlier
context_get()/_PyHamt_Find succeed (start=0 alone exits cleanly), then token_new
returns NULL *and* contextvar_set() fails (its _PyHamt_Assoc returns NULL),
reaching Py_DECREF(NULL). Observed crash at start=2.

Likely fix: NULL-check tok after token_new (`if (tok == NULL) return NULL;`), or
use Py_XDECREF(tok) on the error path.
"""
import contextvars
from _testcapi import set_nomemory, remove_mem_hooks

cv = contextvars.ContextVar("x")
for start in range(16):            # observed crash at start=2
    set_nomemory(start, 0)         # fail every allocation from #start onward
    try:
        try:
            cv.set(object())       # token_new()==NULL (unchecked) + contextvar_set fail -> Py_DECREF(NULL)
        finally:
            remove_mem_hooks()
    except MemoryError:
        pass
