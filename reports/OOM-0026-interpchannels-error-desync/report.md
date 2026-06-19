# Abort: err-code vs `PyErr` desync in `handle_channel_error` (`_interpchannelsmodule.c:398` / `:443`)

*`_interpchannels.create()` threads a hand-rolled integer error code alongside the exception state; under OOM `newchannelid()` fails with a pending `MemoryError` while the `channel_destroy()` cleanup returns `0`, so `handle_channel_error`'s `assert(!PyErr_Occurred())` (L398) fires — and separately a `channel_create()` `-1` return sets no exception, tripping `assert(PyErr_Occurred())` (L443).*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

The `_interpchannels` channel-create path threads a hand-rolled integer error code in
parallel with the Python exception state, and `handle_channel_error()` asserts the two
agree: `err == 0 ⟹ !PyErr_Occurred()`, and an unhandled `err < 0 ⟹ PyErr_Occurred()`.
Under OOM these diverge. In the **L398** form a prior step fails with a `MemoryError`
pending and the cleanup path then calls `handle_channel_error(channel_destroy()==0)` —
`channel_destroy()` returns the success code `0` but does not clear the still-pending
`MemoryError`, so `assert(!PyErr_Occurred())` fires. In the **L443** form `channel_create()`
returns a generic failure code (`-1`) without setting any exception, so
`assert(PyErr_Occurred())` fires. Either aborts on debug builds.

## Reproducer

Minimal, stdlib-only — deterministically hits the success-branch form (L398):

```python
import _interpchannels
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(1, 4000):
    set_nomemory(start, 0)
    try:
        try:
            _interpchannels.create(1)     # newchannelid() fails (-1); cleanup handle_channel_error(channel_destroy()==0) aborts w/ MemoryError still pending
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
```

The fuzzing vehicle (`python-7/_interpchannels-assertion-sigabrt`) hits the
failure-branch form (L443): `channel_create()` returns `-1` with no exception set.

## Backtrace

```
_interpchannelsmodule.c:398: handle_channel_error: Assertion `!PyErr_Occurred()' failed.   # minimal repro
#8  handle_channel_error  _interpchannelsmodule.c:398    # if (err==0) assert(!PyErr_Occurred())
#9  channelsmod_create    _interpchannelsmodule.c:2955   # handle_channel_error(channel_destroy()==0) in the cleanup block, MemoryError still pending

_interpchannelsmodule.c:443: handle_channel_error: Assertion `PyErr_Occurred()' failed.    # vehicle
#9  channelsmod_create    _interpchannelsmodule.c:2941   # handle_channel_error(-1, self, cid) when cid < 0
```

## Root cause

`handle_channel_error` (L395-445) trusts that the integer `err` and `tstate`'s
exception state are consistent:

```c
static int
handle_channel_error(int err, PyObject *mod, int64_t cid)
{
    if (err == 0) {
        assert(!PyErr_Occurred());     /* L398 */
        return 0;
    }
    assert(err < 0);
    ... /* map known ERR_* codes to PyErr_Format/PyErr_SetString */
    else {
        assert(PyErr_Occurred());      /* L443: caller must have set one */
    }
    return 1;
}
```

Callers in `channelsmod_create` (`_interpchannelsmodule.c:2938-2958`):

```c
    int64_t cid = channel_create(&_globals.channels, defaults);
    if (cid < 0) {
        (void)handle_channel_error(-1, self, cid);   /* L2940: -1 unhandled, no exc set -> L443 (vehicle) */
        return NULL;
    }
    ...
    int err = newchannelid(..., &cidobj);            /* L2948: fails under OOM -> -1, MemoryError set */
    if (handle_channel_error(err, self, cid)) {      /* L2951: err<0 + exc set -> L443 holds, returns 1 */
        assert(cidobj == NULL);
        err = channel_destroy(&_globals.channels, cid);   /* L2953: succeeds, returns 0, MemoryError still pending */
        if (handle_channel_error(err, self, cid)) { }     /* L2954: err==0 -> assert(!PyErr_Occurred()) at L398 (minimal repro) */
        return NULL;
    }
```

Under OOM, `newchannelid()` (L2948) allocates the `channelid` object, fails, and returns
`-1` with a `MemoryError` pending. The first `handle_channel_error(-1)` (L2951) sees
`err < 0` with the exception set, so L443 holds and it returns 1, entering the cleanup
block. `channel_destroy()` (L2953) then succeeds and returns `0` but does **not** clear the
pending `MemoryError`, so the second `handle_channel_error(0)` (L2954) takes the `err == 0`
branch and trips `assert(!PyErr_Occurred())` at L398. (The L443 vehicle form is separate:
`channel_create()` (L2938) can fail returning the generic `-1` **without** calling
`PyErr_NoMemory()`, so `handle_channel_error(-1)` at L2940 hits `assert(PyErr_Occurred())`.)

## Suggested fix

Two independent producers:

- **L443:** `channel_create()` must set an exception (`PyErr_NoMemory()` / a `ChannelError`)
  on every `< 0` return, so `handle_channel_error(-1)` at L2940 finds one pending.
- **L398:** the cleanup in `channelsmod_create` (≈L2951-2956) must not route
  `channel_destroy()`'s success code `0` through the `err == 0` assert while a *prior*
  exception is still pending — e.g. preserve/restore the original exception across the
  `channel_destroy` cleanup (`PyErr_GetRaisedException`/`PyErr_SetRaisedException`), or skip
  the second `handle_channel_error` once the first has already established the error.
  (Note `newchannelid()` already returns `-1` here, so "make `newchannelid` return `< 0`
  when it sets an exception" — an earlier draft's suggestion — does not apply.)

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`). Two faces of one defect
(int error code vs `PyErr` desync in the `_interpchannels` create path); minimal repro
deterministically reproduces the L398 form, vehicle shows the L443 form. Debug-only
asserts (compiled out under NDEBUG → release builds return a possibly-wrong
error/None silently). Distinct from OOM-0014 (`channelsmod__channel_id`,
_interpchannelsmodule.c:3487). Exception-state-under-OOM family.

## Versions

- main (3.16.0a0), commit 15d7406. Aborts on free-threaded debug+ASan and JIT
  debug+ASan; clean exit on the release builds (asserts compiled out).
