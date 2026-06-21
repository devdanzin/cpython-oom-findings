# ENVIRONMENT.md — recreating the dev/fuzzing environment

What to install/build on a new machine to work the way we do here. Paths assume the
`danzin` dev user and the layout in `CLAUDE.md`; adjust as needed. The root parts (the
`fusil` user + fleet dirs + permissions) are handled by `scripts/setup_machine.sh` — this
doc is the rest (mostly non-root).

## 1. The two repos

```
~/projects/fusil                 # the fuzzer (public: github.com/devdanzin/fusil)
~/projects/cpython-oom-findings  # this catalog (public: github.com/devdanzin/cpython-oom-findings)
```

Plus a CPython source checkout to build the matrix from (`~/projects/cpython` or reuse one
of the build trees below — several builds keep their own source tree).

## 2. The CPython build matrix

We test every crasher across several locally-built CPython `main` (3.16.0a0) interpreters.
Each lives in its own dir with a `./python`. Configure flags are the standard ones — match
your exact builds; the **purpose** is what matters:

| build dir | flags (approx.) | purpose |
|---|---|---|
| `~/projects/3.16_ft_debug_asan_cpython` | `--with-pydebug --disable-gil --with-address-sanitizer` | **the triage build** — free-threaded, debug asserts, ASan, `_testcapi.set_nomemory`, gdb, source tree. Most reports' `confirmed_commit` (`15d7406`). |
| `~/projects/3.16_debug_asan_pymalloc` | `--with-pydebug --with-address-sanitizer` (+ pymalloc, GIL) | **UAF producer-pinning build** — accepts `PYTHONMALLOC=malloc`, so frees route through ASan and you get a `heap-use-after-free` report *with the free stack*. (The `ft_debug_asan` build is `--without-pymalloc`, which rejects `PYTHONMALLOC=malloc`.) |
| `~/projects/3.16_ft_release_cpython` | `--disable-gil` (release) | free-threaded release — checks whether a debug-only assert is latent on release. |
| `~/projects/jit_cpython` | `--enable-experimental-jit --with-pydebug --with-address-sanitizer` (GIL) | JIT build — Tier-2/JIT path; debug asserts. |
| `~/projects/upstream_cpython` | release (GIL) | plain release — where release **segfaults** show up (rc 139, no ASan). |

Reading the matrix, exit codes, and the flag-default / commit-gated gotchas: see
**`CLAUDE.md` → "Build matrix & reading it"**.

To lower JIT thresholds for fuzzing, `jit_config.py` in the fusil repo rewrites CPython
source headers (point it at a checkout).

## 3. Python venvs

```
~/venvs/fusil_venv        # fleet runner (GIL); needs python-ptrace
~/venvs/fusil_ft_venv     # fleet runner (free-threaded); built from a FT CPython + python-ptrace
~/venvs/shrinkray_venv    # shrinkray (test-case minimizer)
```

- `python-ptrace` (0.9.9) is a **hard** runtime dependency of fusil (`fusil.application`
  imports it at load). The `oom_dedup` engine itself is pure-Python and imports without it.
- The fusil console script is `fusil-python-threaded` (`pip install -e ~/projects/fusil`).
- Optional fusil extras: `pip install -e '~/projects/fusil[numpy,h5py]'` (generators/tests
  skip gracefully when absent).

## 4. System packages & tools

- **Build CPython:** a C toolchain + CPython build deps (`build-essential`, `libssl-dev`,
  `zlib1g-dev`, `libffi-dev`, …) and **Clang** (we build ASan with clang).
- **`gdb`** — crash triage / fallback backtraces (perturbs OOM timing; cross-check only).
- **`addr2line`** (binutils) — resolve static-function offsets from faulthandler C stacks.
- **`ruff`** — lint (`/snap/bin/ruff` here). `pyflakes`/`pytest` are **not** used (fusil
  tests run under `unittest`).
- **`shrinkray`** (in its venv) and **`creduce`** (`/usr/bin`) — test-case minimization.
- **`rr`** — record/replay debugging. **Gotcha:** `rr` + an ASan build fails to record
  (new ASan uses `MADV_GUARD_INSTALL`, advice 102, which older `rr` returns `ENOSYS` for);
  use a non-ASan build for `rr`, or pin a producer via the ASan free-stack instead.
  `rr` also needs `kernel.perf_event_paranoid <= 3` (`sudo sysctl kernel.perf_event_paranoid=3`).

## 5. The fleet (multi-instance fuzzing)

`scripts/setup_machine.sh` (root) creates the `fusil` user and `/home/fusil/runs/fleet`.
The runner lives in the fusil repo (`fleet/`): `sudo -E F=~/projects/fusil/fleet/fleet;
$F up <N>` etc., with a `FLEET_CONF` pointing at a `fleet.conf`. `RUNNER_PY` must be an
**absolute** venv python (a free-threaded runner venv for GIL-off instances). See the fusil
`CLAUDE.md` / `fleet/` for the systemd details and the clean-env gotchas.

## 6. Quick bring-up checklist

1. `git clone` both repos under `~/projects`.
2. Build at least `ft_debug_asan` (triage) and `debug_asan_pymalloc` (UAF free-stacks);
   add the others as needed.
3. Create the venvs (§3); `pip install -e` fusil into the runner venv(s) (+ `python-ptrace`).
4. `sudo -E scripts/setup_machine.sh` (creates the `fusil` user, fleet dirs, permissions).
5. Point `OOM_PY` (see `scripts/min_oracle.sh`) at the `ft_debug_asan` python; sanity-run a
   known repro (e.g. `reports/OOM-0036-*/repro.py`) on it.
6. Configure the fleet (`fleet.conf`, `RUNNER_PY`, `FLEET_CONF`) and `sudo -E $F up`.
