"""
Minimal reproducer: abort on assert(!PyErr_Occurred()) in specialize()
(Python/specialize.c:364) when LOAD_ATTR is specialized while a stale
MemoryError is pending under OOM.

Affected:   CPython 3.16.0a0 (main), builds with assertions enabled.
            Reproduces on the free-threaded debug+ASan build and on the JIT
            build (both compile assert() in). Release builds define NDEBUG so
            the assert is a no-op (see Notes) -> they exit cleanly.
Crash:      SIGABRT, Python/specialize.c:364
            Assertion `!PyErr_Occurred()' failed in void specialize(...).
Requires:   a debug build (assertions on) exposing _testcapi.set_nomemory.

Run:
    python repro.py
    # aborts (rc 134) on the FT debug+ASan build and on the JIT build.

Backtrace (gdb):
    #8  specialize                          Python/specialize.c:364   (assert !PyErr_Occurred())
    #9  specialize_module_load_attr_lock_held Python/specialize.c:443   (specialize(LOAD_ATTR_MODULE))
    #10 specialize_module_load_attr          Python/specialize.c:460
    #11 _Py_Specialize_LoadAttr              Python/specialize.c:1010
    #12 _PyEval_EvalFrameDefault             generated_cases.c.h:8761  (_SPECIALIZE_LOAD_ATTR)
    At the crash, the pending exception (PyErr_Occurred()) is a MemoryError.

Root cause (Python/specialize.c):

    The adaptive specializer for LOAD_ATTR runs at the start of the opcode
    (_SPECIALIZE_LOAD_ATTR, before the attribute is actually loaded). The
    specializer's helpers assume no exception is pending: specialize() opens
    with `assert(!PyErr_Occurred())` (L364), and _PyType_LookupStackRefAndVersion
    has the same assumption ("We may end up clearing live exceptions below, so
    make sure it's ours.", typeobject.c:6343).

    Under set_nomemory OOM injection a prior allocation in the same expression
    leaves a MemoryError set. The specializer (_Py_Specialize_LoadAttr ->
    specialize_module_load_attr_lock_held) does not check PyErr_Occurred() and
    proceeds to specialize(instr, LOAD_ATTR_MODULE), tripping the debug assert
    and aborting the interpreter. The specializer is meant to be best-effort
    and must never observe/act on a pre-existing pending exception.

Likely fix: have the specialization entry points bail out (return without
specializing) when an exception is already pending, e.g. at the top of
_Py_Specialize_LoadAttr:

    if (PyErr_Occurred()) {
        unspecialize(instr);
        return;
    }

(or guard each specialize() callsite / make the eval loop not invoke the
specializer while an error is pending). The defect is a missing pending-error
check, not a use-after-free.

The OOM sweep is needed so that some earlier allocation in the gettext call
fails (setting MemoryError) at the exact moment the still-unspecialized
LOAD_ATTR is hot enough to trigger specialization. Observed crash within the
sweep on this build; `warnings` is pre-imported and warnings silenced so the
OOM budget is not consumed building the warning machinery (which would instead
hit the unrelated OOM-0003 code_dealloc assert).
"""
import _testcapi
import faulthandler
import gettext
import warnings

faulthandler.enable()
warnings.simplefilter("ignore")  # don't build warning machinery under OOM

# gettext.npgettext(context, msgid1, msgid2, n): a non-int `n` drives
# gettext._as_int2(n), whose `n.__class__.__name__` / module-level LOAD_ATTRs
# are still unspecialized. Pre-run once outside OOM so 'warnings' is imported
# and the code path is warm.
try:
    gettext.npgettext("ctx", "a", "b", "not-an-int")
except Exception:
    pass

# Sweep the failing-allocation index. Some `start` leaves a MemoryError pending
# right as a LOAD_ATTR is specialized -> specialize() assert fires (~start 54
# on this build).
for start in range(1, 260):
    _testcapi.set_nomemory(start, 0)
    try:
        try:
            gettext.npgettext("ctx", "a", "b", "not-an-int")
        finally:
            _testcapi.remove_mem_hooks()
    except MemoryError:
        pass
    except BaseException:
        pass
print("done (no crash on this build)")
