"""Export the KiCad netlist and compare it with design.py (connectivity, values, footprints, LCSC)."""
import os, subprocess, sys
import sexp as S
import design as D

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(S.KICAD, "bin", "kicad-cli.exe")


def main():
    sch = os.path.join(HERE, "touchsynth", "touchsynth.kicad_sch")
    net = os.path.join(HERE, "touchsynth", "touchsynth.net")
    subprocess.run([CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net, sch], check=True,
                   capture_output=True)
    doc = S.parse(open(net, encoding="utf-8").read())
    comps = {S.find1(c, "ref")[1]: c for c in S.find(S.find1(doc, "components"), "comp")}
    groups_k = set()
    for n in S.find(S.find1(doc, "nets"), "net"):
        nodes = frozenset((str(S.find1(x, "ref")[1]), str(S.find1(x, "pin")[1])) for x in S.find(n, "node"))
        if len(nodes) > 1 or not str(S.find1(n, "name")[1]).split("/")[-1].startswith("unconnected"):
            groups_k.add(nodes)
    groups_d = {frozenset(v) for k, v in D.nets().items() if not k.startswith("NC_")}
    # KiCad also lists single-node nets for no-connect pins; drop singletons that are NC in the design
    nc = {(p.ref, pin) for p in D.PARTS for pin, n in p.pins.items() if n.startswith("NC_")}
    groups_k = {g for g in groups_k if not (len(g) == 1 and next(iter(g)) in nc)}
    groups_k = {g for g in groups_k if not all(r.startswith("#") for r, _ in g)}
    groups_k = {frozenset((r, p) for r, p in g if not r.startswith("#")) for g in groups_k}
    missing = groups_d - groups_k
    extra = groups_k - groups_d
    errs = 0
    for g in list(missing)[:10]:
        print("design net not found in KiCad:", sorted(g)); errs += 1
    for g in list(extra)[:10]:
        print("KiCad net not in design:", sorted(g)); errs += 1
    for p in D.PARTS:
        c = comps.get(p.ref)
        if c is None:
            print("missing component", p.ref); errs += 1; continue
        fpk = S.find1(c, "footprint"); fpk = str(fpk[1]) if fpk else ""
        props = {str(S.find1(x, "name")[1]): str(S.find1(x, "value")[1]) for x in S.find(c, "property")
                 if S.find1(x, "name") and S.find1(x, "value")}
        if fpk != p.fp:
            print("footprint mismatch", p.ref, fpk, p.fp); errs += 1
        if (p.lcsc or "") != props.get("LCSC", ""):
            print("LCSC mismatch", p.ref); errs += 1
    print(f"{len(D.PARTS)} parts, {len(groups_d)} design nets, {len(groups_k)} KiCad nets -> "
          f"{'OK' if not errs else str(errs) + ' problems'}")
    return errs


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
