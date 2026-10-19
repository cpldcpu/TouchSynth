"""Compare the design (schematic source) with its simulated netlist (voice card: S13 A on S10 v5c; backplane: S12
--bus2, the mixer).

Every part with a 'sim' name is looked up in the ngspice netlist; its nodes are mapped to schematic net names
(D.SIM_NODES) and its value compared. Reports parts that differ, simulated elements without a design part, and
design parts that should have a simulation name (analog parts on the signal path) but have none.
"""
import re, sys
from board import D

OPAMP_PINS = {"dual": {1: (3, 2, 8, 4, 1), 2: (5, 6, 8, 4, 7)},
              "quad": {1: (3, 2, 4, 11, 1), 2: (5, 6, 4, 11, 7), 3: (10, 9, 4, 11, 8), 4: (12, 13, 4, 11, 14)}}
MULT = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "M": 1e6, "g": 1e9}


def num(v):
    m = re.match(r"^([\d.]+(?:[eE][-+]?\d+)?)(meg|Meg|[fpnuµmkMg])?", str(v))
    if not m:
        return None
    x = float(m.group(1))
    s = m.group(2)
    return x * MULT[s.lower() if s and s.lower() == "meg" else s] if s else x


def sim_elements():
    els = {}
    for line in D.sim_netlist().splitlines():
        t = line.split()
        if not t or t[0][0] in "*.+" or t[0].upper().startswith(("V", "B", "I", "E")):
            continue
        els[t[0].upper()] = t[1:]
    return els


def main():
    els = sim_elements()
    used, errs, checked = set(), 0, 0
    units = getattr(D, "SIM_UNITS", {})
    derated = getattr(D, "SIM_DERATED", {})
    for p in D.PARTS:
        if not p.sim:
            continue
        for k, name in enumerate(p.sim.split("/")):
            if not name:
                continue                               # spare op-amp unit
            src = name.upper()
            if src not in els:
                print(f"  {p.ref} ({name}): not in simulation netlist"); errs += 1; continue
            used.add(src)
            e = els[src]
            m = lambda nd: D.SIM_NODES.get(nd.lower(), f"?{nd}")
            if src[0] in "RC":
                want = {m(e[0]), m(e[1])}
                have = {p.pins["1"], p.pins["2"]}
                val = derated.get(src, num(p.value.replace("Ω", "")))
                ok = want == have and abs(num(e[2]) - val) < 1e-3 * num(e[2])
            elif src[0] == "Q":
                c, b, em = (m(x) for x in e[:3])
                pins = (("6", "2", "1"), ("3", "5", "4"))[k] if p.lib_id.endswith("BC847BS") else ("3", "1", "2")
                ok = (p.pins[pins[0]], p.pins[pins[1]], p.pins[pins[2]]) == (c, b, em)
            elif src[0] == "X":
                quad = p.lib_id.endswith("LM324")
                unit = units[src] if quad else k + 1
                pn = OPAMP_PINS["quad" if quad else "dual"][unit]
                ok = tuple(p.pins[str(x)] for x in pn) == tuple(m(x) for x in e[:5])
            else:
                ok = True
            checked += 1
            if not ok:
                errs += 1
                print(f"  MISMATCH {p.ref} {p.value} ({name}): design {p.pins} vs sim {e}")
    skip = getattr(D, "SIM_ONLY", set())
    unused = sorted(n for n in set(els) - used if n not in skip and not n.startswith("RNZ"))
    if unused:
        errs += len(unused)
        print("simulation elements without a design part:", unused)
    print(f"checked {checked} simulated elements against the design: {errs} problems")
    return errs


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
