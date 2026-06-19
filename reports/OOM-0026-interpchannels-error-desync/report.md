# Title

Abort: `_interpchannels.create()` desyncs its integer error code from the exception state under OOM — both `handle_channel_error` asserts fire (`Modules/_interpchannelsmodule.c:398` / `:443`)

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

The `_interpchannels` channel-create path threads a hand-rolled integer error code in
parallel with the Python exception state, and `handle_channel_error()` asserts the two
agree: `err == 0 ⟹ !PyErr_Occurred()`, and an unhandled `err < 0 ⟹ PyErr_Occurred()`.
Under OOM these diverge. A callee can return the success code `0` while leaving a
`MemoryError` pending (→ `assert(!PyErr_Occurred())` at L398), or return a generic
failure code without setting any exception (→ `assert(PyErr_Occurred())` at L443).
Either aborts on debug builds.

## Reproducer

Minimal, stdlib-only — deterministically hits the success-branch form (L398):

```python
import _interpchannels
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(1, 4000):
    set_nomemory(start, 0)
    try:
        try:
            _interpchannels.create(1)     # channelsmod_create -> newchannelid() returns 0 w/ MemoryError pending
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
#9  channelsmod_create    _interpchannelsmodule.c:2955   # handle_channel_error(newchannelid(...), self, cid)

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

Callers in `channelsmod_create`:

```c
    int64_t cid = channel_create(&_globals.channels, defaults);
    if (cid < 0) {
        (void)handle_channel_error(-1, self, cid);   /* L2941: -1 is unhandled -> L443 */
        return NULL;
    }
    ...
    int err = newchannelid(state->ChannelIDType, cid, 0, &_globals.channels, 0, 0, &cidobj);
    if (handle_channel_error(err, self, cid)) { ... } /* L2955: err==0 -> L398 */
```

Under OOM, `channel_create()` allocates (mutex, queue, ID) and can fail returning the
generic `-1` **without** calling `PyErr_NoMemory()` — failure-branch form. And
`newchannelid()` can allocate the `channelid` object, fail internally, set a
`MemoryError`, yet still return `err == 0` to its out-param caller — success-branch
form. In both cases the int-code channel and the exception state disagree.

## Suggested fix

Make the two channels consistent at the source:

- `channel_create()` must set an exception (`PyErr_NoMemory()` / a `ChannelError`) on
  every `< 0` return, so the L443 `assert(PyErr_Occurred())` holds; and
- `newchannelid()` must return a negative error code (not `0`) whenever it leaves an
  exception set, so the L398 `assert(!PyErr_Occurred())` holds.

Alternatively make `handle_channel_error` authoritative: on the `err == 0` branch
clear/ignore a stray exception, and on the unhandled-`err` branch set a generic
`ChannelError` if none is pending — but fixing the producers is cleaner.

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
