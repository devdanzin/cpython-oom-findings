"""
Minimal reproducer: crash in channelsmod__channel_id() when
_get_current_module() fails under OOM.

Affected:   CPython 3.16.0a0 (main), all build configurations.
Crash:      SIGABRT on debug builds (ft_debug_asan, jit):
                ./Modules/_interpchannelsmodule.c:3487
                Assertion `mod == self' failed.
            SIGSEGV on release builds (ft_release, upstream): the assert is
            compiled out, so the same NULL module pointer is dereferenced a
            few lines later (Py_DECREF(NULL) at L3488), or inside the import
            lookup at L3486 (see Notes).
Requires:   a build exposing _testcapi.set_nomemory.

Backtrace (gdb, ft_debug_asan):
    #8  channelsmod__channel_id   _interpchannelsmodule.c:3487  (assert mod == self)
    #9  cfunction_call            Objects/methodobject.c:564
    #10 _PyObject_Call            Objects/call.c:361
    #11 _PyEval_EvalFrameDefault  Python/generated_cases.c.h:2831

Root cause (Modules/_interpchannelsmodule.c):

    channelsmod__channel_id() (L3478) is the C implementation of
    _interpchannels._channel_id().  After fetching the module state it does:

        PyObject *mod = get_module_from_owned_type(cls);   // L3486
        assert(mod == self);                               // L3487
        Py_DECREF(mod);                                    // L3488

    get_module_from_owned_type() (L165) just calls _get_current_module()
    (L149), whose very first step is:

        PyObject *name = PyUnicode_FromString(MODULE_NAME_STR);  // L151
        if (name == NULL) {
            return NULL;                                          // L153
        }
        PyObject *mod = PyImport_GetModule(name);                // L155

    Under OOM, PyUnicode_FromString() (or PyImport_GetModule's internal
    allocations) fails and _get_current_module() returns NULL *with an
    exception set*. The caller never checks the return value: it asserts
    mod == self (NULL != self -> abort on debug builds) and then does
    Py_DECREF(mod) -> Py_DECREF(NULL) (segfault on release builds). The
    pre-existing MemoryError is also silently masked.

The OOM sweep needs only start=0: the first allocation the function performs
is inside _get_current_module(), so failing allocation #0 deterministically
drives mod == NULL.

Likely fix: check the return value instead of asserting, e.g.

    PyObject *mod = get_module_from_owned_type(cls);
    if (mod == NULL) {
        return NULL;
    }
    assert(mod == self);   // keep the invariant only once mod is known non-NULL
    Py_DECREF(mod);

Self-sweeping: `python repro.py` runs the trigger under set_nomemory(N, 0) for N in a
sweep, each in a FRESH subprocess (a fresh process avoids cache warm-up shifting the OOM
window), and stops at the first N that crashes. Needs a debug build (the check is compiled
out under NDEBUG). Bare trigger (fixed N=0):
    import _interpchannels, _testcapi
    _testcapi.set_nomemory(0, 0)
    _interpchannels._channel_id(0)
"""
import os
import sys
import subprocess

TRIGGER = r"""
import _interpchannels
import _testcapi
import faulthandler
faulthandler.enable()
_testcapi.set_nomemory({n}, 0)
try:
    _interpchannels._channel_id(0)   # -> get_module_from_owned_type -> NULL
                                     #    -> assert mod == self (SIGABRT, debug)
                                     #    -> Py_DECREF(NULL)     (SIGSEGV, release)
finally:
    _testcapi.remove_mem_hooks()
"""

SIGNATURE = "_interpchannelsmodule.c:3487: PyObject *channelsmod__channel_id"


def main():
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=0"}
    # This bug is build-agnostic (not free-threading-only); GIL=1 works.
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
