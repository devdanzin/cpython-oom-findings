#!/usr/bin/env python3
"""Match a new backtrace against the known-bug catalog (reports/*/meta.json).

Usage:
    dedupe.py <backtrace.txt>

Prints the matching bug id (and how strong the match is) or NEW. Matching is by
crash SITE frame first, then by the top-frame hash. The decision is advisory --
a human/agent confirms before assigning a vehicle to a bug or minting a new id.
"""
import sys, json, pathlib
from signature import signature

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"


def load_catalog():
    cat = []
    for meta in REPORTS.glob("*/meta.json"):
        d = json.loads(meta.read_text())
        sig = d.get("signature", {})
        cat.append((d["id"], d.get("description", ""), sig.get("site_frame"),
                    sig.get("top_frames", [])))
    return cat


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: dedupe.py <backtrace.txt>")
    sig = signature(sys.argv[1])
    print(f"new crash: kind={sig['kind']} site={sig['site_frame']}")
    site_hits = [c for c in load_catalog() if c[2] == sig["site_frame"]]
    if site_hits:
        for bid, desc, site, _ in site_hits:
            print(f"  MATCH (same site) -> {bid}: {desc}")
        return
    # secondary: top-frame overlap (e.g. sibling decref in same function pair)
    near = [c for c in load_catalog()
            if c[3] and sig["top_frames"] and c[3][0].split("@")[0].split(":")[0]
            == sig["top_frames"][0].split("@")[0].split(":")[0]]
    if near:
        for bid, desc, site, _ in near:
            print(f"  NEAR (same function, different line) -> {bid}: {desc} [{site}]")
        print("  -> confirm manually: same bug or sibling?")
    else:
        print("  NEW -> mint a new OOM-#### id")


if __name__ == "__main__":
    main()
