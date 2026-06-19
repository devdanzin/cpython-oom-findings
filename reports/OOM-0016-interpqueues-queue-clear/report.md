# Abort: `assert(!queue->alive)` in `_queue_clear` (`_interpqueuesmodule.c:559`)

*`queue_create`'s OOM error path calls `_queue_clear` on a still-alive queue after `_queues_add()` fails to allocate its `_queueref`, tripping the `assert(!queue->alive)` because the kill step was skipped.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`queue_create()` allocates a `_queue`, calls `_queue_init()` (which sets `queue->alive = 1`), then registers it via `_queues_add()`. Under OOM, `_queues_add()` fails to allocate the `_queueref` node and returns a negative error. The error path then calls `_queue_clear(queue)` directly on the *still-alive* queue, but `_queue_clear()` opens with `assert(!queue->alive)`. The assertion fires and the interpreter aborts. Reaching `_queues.create` is enough; no extra interpreters are spawned.

## Reproducer

```python
import _testcapi, _interpqueues, faulthandler
faulthandler.enable()
_testcapi.set_nomemory(2, 0)   # fail every allocation from #2 onward
try:
    _interpqueues.create(0, 3, -1)   # maxsize=0, unboundop=UNBOUND(3), fallback=-1
finally:
    _testcapi.remove_mem_hooks()
```

Deterministic at `start=2` on the free-threaded debug+ASan build (and on the JIT build, which also ships assertions). Allocation #0 is the `_queue` struct and #1 the queue mutex (both succeed); allocation #2 is the `_queueref` inside `_queues_add()`, which fails — driving the buggy cleanup path. `unboundop=3` is `UNBOUND` (from `concurrent.interpreters._queues._serialize_unbound(UNBOUND)`).

## Backtrace

```
#8  _queue_clear            Modules/_interpqueuesmodule.c:559   <- assert(!queue->alive); queue->alive == 1
#9  queue_create            Modules/_interpqueuesmodule.c:1104  <- _queue_clear(queue) after _queues_add() < 0
#10 _interpqueues_create_impl  Modules/_interpqueuesmodule.c:1529
#11 _interpqueues_create    Modules/clinic/_interpqueuesmodule.c.h:100
#12 _Py_BuiltinCallFastWithKeywords_StackRef  Python/ceval.c:841
```

`(gdb) frame 8; print queue->alive` -> `1` (never cleared, because the create error path skips `_queue_kill_and_wait()`).

## Root cause

`Modules/_interpqueuesmodule.c`, `queue_create()` (L1089):

```c
    int err = _queue_init(queue, maxsize, defaults);   /* L1097: sets queue->alive = 1 */
    if (err < 0) {
        GLOBAL_FREE(queue);
        return (int64_t)err;
    }
    int64_t qid = _queues_add(queues, queue);          /* L1102: GLOBAL_MALLOC(_queueref) fails under OOM */
    if (qid < 0) {
        _queue_clear(queue);                           /* L1104: queue->alive is still 1 -> assert fires */
        GLOBAL_FREE(queue);
    }
    return qid;
```

`_queue_init()` (L538) sets `.alive = 1`. `_queues_add()` (L906) allocates a `_queueref` with `GLOBAL_MALLOC` at L916; under OOM that returns `NULL`, so `_queues_add` returns `ERR_QUEUE_ALLOC` (< 0). `queue_create` then calls `_queue_clear(queue)`, whose first statement is:

```c
static void
_queue_clear(_queue *queue)
{
    assert(!queue->alive);                 /* L559: FAILS, queue->alive == 1 */
    ...
}
```

Every other teardown path reaches `_queue_clear` only via `_queue_free`, and only *after* `_queue_kill_and_wait()` has set `queue->alive = 0` (see `queue_destroy`, L1119: `_queue_kill_and_wait(queue); _queue_free(queue);`). The `queue_create` OOM error path is the one site that calls `_queue_clear` on a queue that was successfully `_queue_init`'d (alive) but never registered, so it never runs the kill step. This is a missing state transition / wrong-cleanup-helper bug in the error path, not a use-after-free; the actual memory cleanup `_queue_clear` performs (freeing items, the lock, zeroing the struct) is correct for a freshly-initialised queue.

## Suggested fix

In `queue_create()`, mark the queue dead before clearing it on the `_queues_add` failure path, matching the normal teardown order:

```c
    int64_t qid = _queues_add(queues, queue);
    if (qid < 0) {
        queue->alive = 0;          /* never registered; no waiters, so this is safe */
        _queue_clear(queue);
        GLOBAL_FREE(queue);
    }
    return qid;
```

(Equivalently, route through `_queue_kill_and_wait(queue); _queue_free(queue);` — though since the queue was never published there can be no waiters, the simple `queue->alive = 0` before `_queue_clear` is sufficient. Alternatively, relax `_queue_clear`'s `assert(!queue->alive)` to tolerate an unregistered queue.)

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). Reproduces as an **abort** on builds that compile assertions in: the free-threaded debug+ASan build and the JIT build both fire `Modules/_interpqueuesmodule.c:559`. Release builds define `-DNDEBUG`, so the `assert` is compiled out; on `ft_release` and `upstream` the same error path runs `_queue_clear` on the live queue but only frees items/lock and zeroes the struct (no UAF), so they cleanly raise `MemoryError` and exit 0/1. Per the OOM-catalog convention for assert-based aborts, the non-debug builds are recorded as `n/a` (they do not crash).

Three fuzzer vehicles (`python-4`, `python-5`, `python-7`, all `concurrent_interpreters__queues-assertion-sigabrt`) abort at the identical `_interpqueuesmodule.c:559` assertion; each calls `concurrent.interpreters._queues.create()` under an OOM sweep, which dispatches to `_interpqueues.create` -> `queue_create`.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build and the JIT build. Release/upstream builds: assertion compiled out, clean `MemoryError` (`n/a`).
