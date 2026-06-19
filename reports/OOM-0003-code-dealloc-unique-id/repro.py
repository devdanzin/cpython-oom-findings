"""
Minimal reproducer: abort on assert(co->_co_unique_id == _Py_INVALID_UNIQUE_ID)
in code_dealloc() when init_code() fails under OOM.

Affected:   CPython 3.16.0a0 (main), free-threaded (Py_GIL_DISABLED) builds only.
            The assertion is compiled in on free-threaded DEBUG builds; release
            builds define NDEBUG so assert() is a no-op (see Notes).
Crash:      SIGABRT, Objects/codeobject.c:2440
            Assertion `co->_co_unique_id == _Py_INVALID_UNIQUE_ID' failed.
Requires:   a free-threaded debug build exposing _testcapi.set_nomemory.

Backtrace (gdb):
    #8  code_dealloc      Objects/codeobject.c:2440  (assert _co_unique_id == INVALID)
    #9  _Py_Dealloc       Objects/object.c:3319
    #10 Py_DECREF         Include/refcount.h:359
    #11 _PyCode_New       Objects/codeobject.c:747   (Py_DECREF(co) after init_code(...) < 0)
    #12 r_object          Python/marshal.c:1676      (marshal.loads -> rebuild code object)

Root cause (Objects/codeobject.c):

    _PyCode_New() (L716) allocates the code object with PyObject_GC_NewVar()
    (L736), which does NOT zero-initialize the trailing _co_unique_id field.
    It then calls init_code(co, con) (L746). The _co_unique_id field is only
    assigned *after* init_code() succeeds, at L752:

        if (init_code(co, con) < 0) {
            Py_DECREF(co);             // L747: init_code failed -> dealloc
            return NULL;
        }
        co->_co_unique_id = _PyObject_AssignUniqueId((PyObject *)co);  // L752

    Inside init_code() the free-threaded branch allocates the thread-local
    bytecode array (L570):

        co->co_tlbc = _PyCodeArray_New(INITIAL_SPECIALIZED_CODE_SIZE);
        if (co->co_tlbc == NULL) {     // fails under OOM
            return -1;                 // -> _PyCode_New does Py_DECREF(co)
        }

    Under OOM that PyMem_Calloc fails, init_code returns -1, and Py_DECREF(co)
    runs code_dealloc() on a code object whose _co_unique_id was never set to
    _Py_INVALID_UNIQUE_ID (== 0). The field holds uninitialized garbage, so the
    debug-only assert at L2440 fails and aborts.

The OOM sweep is needed so the code-object allocation itself succeeds (start
small) while a later allocation inside init_code (the tlbc array) fails.
Observed crash at start=9 on this build; a single set_nomemory(9, 0) suffices.

Likely fix: initialize co->_co_unique_id = _Py_INVALID_UNIQUE_ID in init_code()
(or right after PyObject_GC_NewVar in _PyCode_New) before any path that can lead
to code_dealloc().

Self-sweeping: `python repro.py` runs the trigger under set_nomemory(N, 0) for N in a
sweep, each in a FRESH subprocess (a fresh process avoids cache warm-up shifting the OOM
window), and stops at the first N that crashes. Needs a free-threaded debug build (the
assert is compiled out under NDEBUG and the field is gated on Py_GIL_DISABLED). Bare
trigger (fixed N=9):
    import marshal, _testcapi
    blob = marshal.dumps(compile("def f(x):\n    return x + 1\n", "<gen>", "exec"))
    _testcapi.set_nomemory(9, 0)
    marshal.loads(blob)
"""
import os
import sys
import subprocess

TRIGGER = r"""
import marshal
import _testcapi
import faulthandler
faulthandler.enable()
# Build a marshalled code object up front (before any OOM injection), so the
# crashing work is purely the code-object reconstruction in marshal.loads().
blob = marshal.dumps(compile("def f(x):\n    return x + 1\n", "<gen>", "exec"))
_testcapi.set_nomemory({n}, 0)   # fail every allocation from #{n} onward
try:
    marshal.loads(blob)          # _PyCode_New: init_code's _PyCodeArray_New fails
                                 # -> Py_DECREF(co) -> code_dealloc assert -> SIGABRT
finally:
    _testcapi.remove_mem_hooks()
"""

SIGNATURE = "co->_co_unique_id == _Py_INVALID_UNIQUE_ID"

def main():
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=0"}
    env["PYTHON_GIL"] = "0"   # free-threading-only bug: needs the GIL disabled
    for n in range(80):
        out = subprocess.run([sys.executable, "-c", TRIGGER.format(n=n)],
                             capture_output=True, text=True, env=env)
        if SIGNATURE in out.stdout + out.stderr:
            print("reproduced at set_nomemory(%d, 0):" % n)
            sys.stdout.write(out.stderr or out.stdout)
            return 1
    print("no crash in range(80); widen it for your build")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
