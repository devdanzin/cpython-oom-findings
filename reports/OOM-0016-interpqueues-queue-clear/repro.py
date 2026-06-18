"""
Minimal reproducer: abort on assert(!queue->alive) in _queue_clear()
when _queues_add() fails under OOM inside queue_create().

Affected:   CPython 3.16.0a0 (main). Fires on builds that compile assertions
            in: the free-threaded debug+ASan build and the JIT build. Release
            builds define NDEBUG so assert() is a no-op (see Notes) and raise
            a clean MemoryError instead.
Crash:      SIGABRT, Modules/_interpqueuesmodule.c:559
            Assertion `!queue->alive' failed.
Requires:   a debug/JIT build exposing _testcapi.set_nomemory and the
            _interpqueues extension module.

Run:
    python repro.py
    # aborts (rc 134) on the FT debug+ASan build and the JIT build.

Backtrace (gdb):
    #8  _queue_clear              Modules/_interpqueuesmodule.c:559   (assert !queue->alive; alive == 1)
    #9  queue_create              Modules/_interpqueuesmodule.c:1104  (_queue_clear after _queues_add() < 0)
    #10 _interpqueues_create_impl Modules/_interpqueuesmodule.c:1529
    #11 _interpqueues_create      Modules/clinic/_interpqueuesmodule.c.h:100

Root cause (Modules/_interpqueuesmodule.c):

    queue_create() (L1089) allocates a _queue, then calls _queue_init()
    (L1097) which sets queue->alive = 1. It then registers the queue with
    _queues_add() (L1102):

        int64_t qid = _queues_add(queues, queue);
        if (qid < 0) {
            _queue_clear(queue);          // L1104
            GLOBAL_FREE(queue);
        }

    Under OOM, _queues_add() (L906) fails to GLOBAL_MALLOC the _queueref
    node (L916) and returns ERR_QUEUE_ALLOC (< 0). queue_create then calls
    _queue_clear(queue) directly -- but _queue_clear() begins with:

        static void
        _queue_clear(_queue *queue)
        {
            assert(!queue->alive);        // L559: FAILS, queue->alive == 1
            ...
        }

    Every correct teardown path reaches _queue_clear only via _queue_free,
    and only after _queue_kill_and_wait() has set queue->alive = 0 (see
    queue_destroy, L1119). The queue_create OOM error path skips that step,
    so it clears a still-"alive" queue and trips the debug-only assert.

    This is a wrong-cleanup-helper bug, not a use-after-free: the work
    _queue_clear performs (free items, free the lock, zero the struct) is
    correct for a freshly-initialised, never-registered queue. Hence on
    NDEBUG (release/upstream) the same path runs cleanly and raises
    MemoryError.

The OOM sweep targets the _queueref allocation: allocation #0 is the _queue
struct and #1 is the queue mutex (both must succeed) so the queue becomes
alive; allocation #2, the _queueref in _queues_add, must fail. Observed crash
at start=2 on this build; a single set_nomemory(2, 0) suffices.

unboundop=3 is UNBOUND, i.e.
    concurrent.interpreters._queues._serialize_unbound(UNBOUND) == (3,)

Likely fix: set queue->alive = 0 before _queue_clear in the queue_create
error path (or route through _queue_kill_and_wait/_queue_free), so cleanup
matches the invariant _queue_clear asserts.
"""
import _testcapi
import _interpqueues
import faulthandler

faulthandler.enable()

_testcapi.set_nomemory(2, 0)   # fail every allocation from #2 onward
try:
    # maxsize=0, unboundop=3 (UNBOUND), fallback=-1
    _interpqueues.create(0, 3, -1)   # queue_create: _queues_add's _queueref
                                     # malloc fails -> _queue_clear on a live
                                     # queue -> assert(!queue->alive) -> SIGABRT
finally:
    _testcapi.remove_mem_hooks()
