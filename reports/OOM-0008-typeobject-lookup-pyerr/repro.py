"""
Minimal reproducer: abort on assert(!PyErr_Occurred()) in
_PyType_LookupStackRefAndVersion() (Objects/typeobject.c:6343) when reading
frame.f_back under OOM swallows a MemoryError.

Affected:   CPython 3.16.0a0 (main). The assert is compiled in on DEBUG builds
            (ft_debug_asan, jit); release builds define NDEBUG so the assert is a
            no-op -- there the swallowed MemoryError instead surfaces later as a
            spurious "SystemError: ... returned a result with an exception set".
Crash:      SIGABRT, Objects/typeobject.c:6343
            Assertion `!PyErr_Occurred()' failed.
Requires:   a debug build exposing _testcapi.set_nomemory.

Backtrace (gdb):
    #8  _PyType_LookupStackRefAndVersion  Objects/typeobject.c:6343  (assert !PyErr_Occurred())
    #9  _PyObject_GenericGetAttrWithDict   Objects/object.c:1919
    #10 _PyObject_GetAttrStackRef          Objects/object.c:1369
    #11 _PyEval_EvalFrameDefault           Python/generated_cases.c.h:8786  (LOAD_ATTR)

Root cause (Objects/frameobject.c):

    PyFrame_GetBack() (L2395) lazily materializes the parent PyFrameObject:

        back = _PyFrame_GetFrameObject(prev);   // L2404
        ...
        return (PyFrameObject*)Py_XNewRef(back); // L2407

    _PyFrame_GetFrameObject -> _PyFrame_MakeAndSetFrameObject allocates a new
    PyFrameObject; under OOM that PyObject_GC_New fails and returns NULL with
    MemoryError set. PyFrame_GetBack does NOT check for the error: it returns
    NULL, and frame_back_get_impl() (L1116) treats NULL as "no parent frame":

        if (res == NULL) {
            Py_RETURN_NONE;    // L1118: swallows the pending MemoryError
        }

    So `frame.f_back` evaluates to None while a MemoryError is still set. The
    LOAD_ATTR opcode reports success; the *next* LOAD_ATTR enters
    _PyType_LookupStackRefAndVersion, which asserts !PyErr_Occurred() and aborts.

The walk() below just guarantees at least one f.f_back access whose lazy frame
allocation fails under OOM; the trailing `sys.maxsize` is any subsequent
LOAD_ATTR that then trips the assert. Deterministic at start=1.

Likely fix: in PyFrame_GetBack, `return NULL;` (propagating the error) when
_PyFrame_GetFrameObject fails; in frame_back_get_impl, only convert a clean
NULL (no pending error) to None.

Original fuzzer vehicle: ~/crashers/python-4/gettext-assertion (gettext._as_int2
walked frames via f.f_back to compute a DeprecationWarning stacklevel under OOM).

Self-sweeping: `python repro.py` runs the trigger under set_nomemory(N, 0) for N in a
sweep, each in a FRESH subprocess (a fresh process avoids cache warm-up shifting the OOM
window), and stops at the first N that crashes. Needs a debug build (the check is compiled
out under NDEBUG). Bare trigger (fixed N=1):
    import sys, _testcapi
    def walk():
        f = sys._getframe()
        while f is not None:
            f = f.f_back
    _testcapi.set_nomemory(1, 0)
    walk()
    x = sys.maxsize       # next LOAD_ATTR trips assert(!PyErr_Occurred())
"""
import os
import sys
import subprocess

TRIGGER = r"""
import sys
import _testcapi
import faulthandler

faulthandler.enable()


def walk():
    f = sys._getframe()
    while f is not None:
        f = f.f_back          # under OOM, materializing the parent frame fails:
                              # MemoryError is set but f.f_back returns None


_testcapi.set_nomemory({n}, 0)  # fail every allocation from #{n} onward
try:
    try:
        walk()                # returns with a pending MemoryError after yielding None
        x = sys.maxsize       # next LOAD_ATTR -> _PyType_LookupStackRefAndVersion
                              # -> assert(!PyErr_Occurred()) fails -> SIGABRT
    finally:
        _testcapi.remove_mem_hooks()
except MemoryError:
    pass
"""

SIGNATURE = "Assertion `!PyErr_Occurred()' failed."


def main():
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=0"}
    # env["PYTHON_GIL"] = "0"   # ONLY if this bug is free-threading-only
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
