#!/usr/bin/env bash
#
# setup_machine.sh -- prepare a machine to run the fusil OOM fuzzing fleet.
#
# Run as root. Creates the unprivileged `fusil` fuzzing account and the fleet output
# tree, and sets permissions so `fusil` can run the fuzzer from your (already-existing)
# dev user's checkout WITHOUT exposing the dev user's whole home. Idempotent.
#
# It does NOT install system packages, build the CPython matrix, or create the Python
# venvs -- those are (mostly non-root, interactive) steps; see docs/ENVIRONMENT.md.
#
set -euo pipefail

# ---- config (override via env, e.g. DEV_USER=alice sudo -E ./setup_machine.sh) ----
DEV_USER="${DEV_USER:-danzin}"          # your interactive dev user (must already exist)
FUZZ_USER="${FUZZ_USER:-fusil}"         # the unprivileged fuzzing account (created here)
DEV_HOME="$(getent passwd "$DEV_USER" 2>/dev/null | cut -d: -f6)"; DEV_HOME="${DEV_HOME:-/home/$DEV_USER}"
FUZZ_HOME="/home/$FUZZ_USER"
FLEET_DIR="$FUZZ_HOME/runs/fleet"
# Paths under the dev home the fuzz user must read (the fusil checkout + the venvs):
SHARED=( "$DEV_HOME/projects/fusil" "$DEV_HOME/venvs" )
# Dev-home mode. 0711 = traverse-only: fusil can REACH the shared paths (and read a known
# file like ~/fleet.conf by exact path) but cannot LIST or read the rest of your home.
# Set DEV_HOME_MODE=0755 to replicate a fully world-readable home instead.
DEV_HOME_MODE="${DEV_HOME_MODE:-0711}"
# ----------------------------------------------------------------------------------

[ "$(id -u)" -eq 0 ] || { echo "ERROR: run as root (sudo -E $0)" >&2; exit 1; }
id "$DEV_USER" &>/dev/null || { echo "ERROR: dev user '$DEV_USER' does not exist" >&2; exit 1; }

echo "== fusil-fleet machine setup =="
echo "   dev user : $DEV_USER ($DEV_HOME)"
echo "   fuzz user: $FUZZ_USER ($FUZZ_HOME)"
echo "   fleet    : $FLEET_DIR"
echo

# 1) the unprivileged fuzzing account
if id "$FUZZ_USER" &>/dev/null; then
    echo "[=] user $FUZZ_USER already exists"
else
    echo "[+] creating user $FUZZ_USER"
    useradd --create-home --shell /bin/bash "$FUZZ_USER"
fi

# 2) the fleet output tree (the fuzzer, running as $FUZZ_USER, writes crash dirs here;
#    the fleet runner -- launched via sudo -- populates per-instance subdirs)
echo "[+] fleet dirs: $FLEET_DIR (owner $FUZZ_USER)"
install -d -o "$FUZZ_USER" -g "$FUZZ_USER" -m 0755 "$FUZZ_HOME/runs" "$FLEET_DIR"

# 3) permissions: let $FUZZ_USER reach the checkout + venvs without exposing the home.
#    (Default umask 022 already makes the subtrees other-readable; we just fix the home
#    mode and make sure the shared roots are traversable.)
echo "[+] $DEV_HOME : $(stat -c %a "$DEV_HOME") -> $DEV_HOME_MODE"
chmod "$DEV_HOME_MODE" "$DEV_HOME"
for p in "${SHARED[@]}"; do
    if [ -e "$p" ]; then
        chmod o+rx "$p"
        echo "    reachable by $FUZZ_USER: $p"
    else
        echo "    (not present yet) $p  -- after you clone/build, ensure it is o+rx"
    fi
done

# 4) keep obvious secrets private regardless of the home mode
for s in "$DEV_HOME/.ssh" "$DEV_HOME/.gnupg"; do
    [ -d "$s" ] && { chmod 0700 "$s"; echo "[+] hardened $s -> 0700"; }
done

echo
echo "[done] $FUZZ_USER can run the fuzzer from $DEV_HOME/projects/fusil"
echo "       (home is traverse-only at $DEV_HOME_MODE; set DEV_HOME_MODE=0755 to undo)."
echo "       Next, as $DEV_USER: build the CPython matrix + venvs -- see docs/ENVIRONMENT.md."
