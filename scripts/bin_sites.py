#!/usr/bin/env python3
"""Bin the deterministic local crash sites from segv_sweep.sh and cross-reference
them against the known-bug catalog (reports/*/meta.json). Tells you, per crash SITE:
how many vehicles hit it, the signal(s), whether it's a KNOWN bug (and which OOM id)
or NEW, and example vehicles. NEW sites (sorted by vehicle count) are the work-list.

Usage: bin_sites.py [sites.tsv]   (default /tmp/segv_sites.tsv)
       bin_sites.py --json        emit NEW-site -> vehicles as JSON for the workflow
"""
import sys, re, json, pathlib, collections

ROOT = pathlib.Path(__file__).resolve().parent.parent
AS_JSON = "--json" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
TSV = pathlib.Path(args[0]) if args else pathlib.Path("/tmp/segv_sites.tsv")

FILELINE = re.compile(r'([\w./+-]+\.(?:c|h)):(\d+)')


def load_known():
    """Return (byfileline{(file,line)->id}, byfilefunc{(file,func)->id}, idlines{id:{file:set(lines)}})."""
    byfl, byff, idlines = {}, {}, collections.defaultdict(lambda: collections.defaultdict(set))
    for meta in ROOT.glob("reports/*/meta.json"):
        d = json.loads(meta.read_text())
        oid = d["id"]
        strings = list(d.get("sites", []))
        sf = d.get("signature", {}).get("site_frame")
        if sf:
            strings.append(sf)
        strings += d.get("signature", {}).get("top_frames", [])
        for s in strings:
            # func from "func@file:line" or "file func:line" or trailing "func"
            func = None
            m = re.match(r'([A-Za-z_]\w+)@', s)
            if m:
                func = m.group(1)
            else:
                m2 = re.search(r'\b([A-Za-z_]\w+):\d+', s)
                if m2:
                    func = m2.group(1)
            for fm in FILELINE.finditer(s):
                f = fm.group(1).lstrip("./")
                ln = int(fm.group(2))
                byfl[(f, ln)] = oid
                idlines[oid][f].add(ln)
                if func:
                    byff[(f, func)] = oid
    return byfl, byff, idlines


def match(site, byfl, byff, idlines):
    """site = 'func@file:line' -> (oid or None, how)."""
    m = re.match(r'([A-Za-z_]\w+)@([\w./+-]+):(\d+)', site)
    if not m:
        return None, "unparsed"
    func, f, ln = m.group(1), m.group(2).lstrip("./"), int(m.group(3))
    if (f, ln) in byfl:
        return byfl[(f, ln)], "exact"
    # within +/-12 lines of a known line in the same file -> same site (line drift)
    for oid, files in idlines.items():
        for kl in files.get(f, ()):
            if abs(kl - ln) <= 12:
                return oid, f"near(+/-{ln-kl})"
    if (f, func) in byff:
        return byff[(f, func)], "func"
    return None, "NEW"


def main():
    if not TSV.exists():
        sys.exit(f"no {TSV} yet (run segv_sweep.sh)")
    byfl, byff, idlines = load_known()
    rows = []
    for line in TSV.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        veh, sig, site = parts[0], parts[1], parts[2]
        rows.append((veh, sig, site))

    bysite = collections.defaultdict(list)
    for veh, sig, site in rows:
        bysite[site].append((veh, sig))

    resolved = {}  # site -> (oid, how)
    for site in bysite:
        resolved[site] = match(site, byfl, byff, idlines)

    if AS_JSON:
        new = {site: [v for v, _ in veh] for site, veh in bysite.items()
               if resolved[site][0] is None and site != "?"}
        print(json.dumps(new, indent=2))
        return

    norepro = sum(1 for _, s, _ in rows if s == "NOREPRO")
    print(f"# {len(rows)} vehicles swept | {len(bysite)} distinct local sites | "
          f"NOREPRO={norepro}\n")
    known_tally = collections.Counter()
    print(f"{'cnt':>4} {'kind':9} {'bug':10} {'how':12} site")
    for site, veh in sorted(bysite.items(), key=lambda kv: -len(kv[1])):
        oid, how = resolved[site]
        sigs = "/".join(sorted({s for _, s in veh}))
        tag = oid or "NEW"
        if oid:
            known_tally[oid] += len(veh)
        print(f"{len(veh):>4} {sigs:9} {tag:10} {how:12} {site}")
    print("\n## NEW sites (work-list) ----------------------------------------")
    for site, veh in sorted(bysite.items(), key=lambda kv: -len(kv[1])):
        if resolved[site][0] is None and site != "?":
            exes = ", ".join(v for v, _ in veh[:4])
            print(f"{len(veh):>4}  {site}\n        e.g. {exes}")
    print("\n## vehicles attributed to existing bugs -------------------------")
    for oid, n in known_tally.most_common():
        print(f"  {oid}: +{n} segv vehicles")


if __name__ == "__main__":
    main()
