"""OOM-0027: a conditional-jump opcode (POP_JUMP_IF_FALSE) finds a non-bool on the
value stack under OOM -> assert(PyStackRef_BoolCheck(cond)) aborts
(Python/generated_cases.c.h).

Reproduced via the fuzzing vehicle python-7/_pyrepl_windows_eventqueue-assertion
(annotation evaluation under the set_nomemory sweep). The bad stack value is a
downstream effect of an allocation failing inside an EARLIER opcode, so reproduction
depends on precise OOM timing rather than a specific construct -- no minimal stdlib
trigger was isolated. Needs a debug build (assert stripped under NDEBUG).

The vehicle's effective shape is: import a module whose body evaluates a boolean
expression (here a deferred __annotate__), inside a dense set_nomemory sweep:

    from _testcapi import set_nomemory, remove_mem_hooks
    for start in range(1, 4000):
        set_nomemory(start, 0)
        try:
            try:
                <evaluate code containing `if <expr>:` / boolean branches>
            finally:
                remove_mem_hooks()
        except BaseException:
            pass

See reports/OOM-0027-pop-jump-boolcheck/backtrace.txt and the vehicle source
(~/crashers/python-7/_pyrepl_windows_eventqueue-assertion/source.py) for the exact
reproducer.
"""
