"""Compare the design (schematic source) with the simulated netlists (S6 full voice + S7 power section).

Every part with a 'sim' name is looked up in the ngspice netlist; its nodes are mapped to schematic net names and
its value compared. Reports parts that differ, and simulated elements that have no counterpart in the design.
"""
import os, sys, re

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(os.path.dirname(HERE), "sim")
sys.path.insert(0, os.path.join(SIM, "lib")); sys.path.insert(0, os.path.join(SIM, "s6_voice"))
sys.path.insert(0, os.path.join(SIM, "s7_power"))
import design as D

NODE = {"0": "GND", "vp": "VP", "v5": "+5V", "vref": "VREF", "vbias": "VBIAS", "v25": "V25",
        **{f"vb{i}": f"VB{i}" for i in range(5)},
        "xamp": "XAMP", "aa": "CVA_A", "ba": "CVA_B", "vea": "VIA_E", "uoa": "VIA_OUT", "bqa": "VIA_B", "n": "DCO_INT",
        "saw": "SAW", "g": "DCO_GATE", "gd": "DCO_GD", "b2": "DCO_B2", "mcu": "DCO_RST", "cva": "PWM_AMP",
        "cvc": "PWM_CUT", "ac": "CVC_A", "bc": "XCUT_IN", "xcut": "XCUT", "na": "EXPO_NA", "ee": "EXPO_E",
        "tail": "TAIL", "uexo": "EXPO_OUT",
        **{f"n{i}{s}": f"N{i}{s.upper()}" for i in range(1, 5) for s in "ab"},
        "bin1": "BIN1", "bin2": "BIN2", "ia": "INA_A", "ib": "INA_B", "oa": "INA_OA", "lpf": "LPF",
        "mx": "MIX", "pls": "PULSE", "sub": "SUB", "noi": "NOISE",
        "cvr": "PWM_RES", "ar": "CVR_A", "br": "CVR_B", "xres": "XRES", "ver": "VIR_E", "uor": "VIR_OUT",
        "bqr": "VIR_B", "rtail": "RES_TAIL", "ri": "RES_RI", "rin1": "RES_IN1", "rin2": "RES_IN2", "rc1": "RES_C1",
        "rc2": "RES_C2", "rdm": "RES_DM", "rdp": "RES_DP", "resout": "RESOUT", "rfb": "RES_FB",
        "cvv": "PWM_VCA", "av": "CVV_A", "bv": "CVV_B", "xvv": "XVCA", "vev": "VIV_E", "uov": "VIV_OUT",
        "bqv": "VIV_B", "vtail": "VCA_TAIL", "vi": "VCA_VI", "vin1": "VCA_IN1", "vin2": "VCA_IN2", "vin2m": "VCA_IN2",
        "vc1": "VCA_C1", "vc2": "VCA_C2", "dm": "VCA_DM", "dp": "VCA_DP", "vcaout": "VCAOUT", "lineout": "LINEOUT",
        "vtrim": "VTRIM", "adca": "ADC_AUDIO", "vin": "VIN", "vrd": "VREF_DIV", "vsn": "VREF_SN"}
ALIAS = {"RBVA": "RBA", "REVA": "REA"}          # design (VI helper) names -> S6 inline DCO V->I names
OPAMP_PINS = {"TL072": {1: (3, 2, 8, 4, 1), 2: (5, 6, 8, 4, 7)},
              "LM324": {1: (3, 2, 4, 11, 1), 2: (5, 6, 4, 11, 7), 3: (10, 9, 4, 11, 8), 4: (12, 13, 4, 11, 14)}}
LM_UNIT = {"XUA": 1, "XUV": 2, "XUEXP": 3, "XUR": 4}
MULT = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "M": 1e6, "g": 1e9}


def num(v):
    m = re.match(r"^([\d.]+)(meg|[fpnuµmkMg])?", str(v))
    if not m:
        return None
    x = float(m.group(1))
    s = m.group(2)
    return x * MULT[s] if s else x


def sim_elements():
    import s6_voice as S6, s7_power as S7
    text = S6.netlist() + "\n" + S7.POWER.format(vin_src="9", i_logic="0")
    els = {}
    for line in text.splitlines():
        t = line.split()
        if not t or t[0][0] in "*.+" or t[0].upper().startswith(("V", "B", "I")):
            continue
        els[t[0].upper()] = t[1:]
    return els


def main():
    els = sim_elements()
    used, errs, checked = set(), 0, 0
    for p in D.PARTS:
        if not p.sim:
            continue
        names = p.sim.split("/")
        for k, name in enumerate(names):
            key = ALIAS.get(name, name).upper()
            src = None
            for cand in (name.upper(), key):
                if cand in els:
                    src = cand
            if src is None:
                print(f"  {p.ref} ({name}): not in simulation netlist"); errs += 1; continue
            used.add(src)
            e = els[src]
            m = lambda nd: NODE.get(nd.lower(), f"?{nd}")
            if src[0] in "RC":
                want = {m(e[0]), m(e[1])}
                have = {p.pins["1"], p.pins["2"]}
                ok = want == have and abs(num(e[2]) - num(p.value.replace("Ω", ""))) < 1e-3 * num(e[2])
            elif src[0] == "Q":
                c, b, em = (m(x) for x in e[:3])
                if p.lib_id.endswith("BC847BS"):
                    pins = (("6", "2", "1"), ("3", "5", "4"))[k]
                else:
                    pins = ("3", "1", "2")
                ok = (p.pins[pins[0]], p.pins[pins[1]], p.pins[pins[2]]) == (c, b, em)
            elif src[0] == "M":
                ok = (p.pins["3"], p.pins["1"], p.pins["2"]) == tuple(m(x) for x in e[:3])
            elif src[0] == "D":
                ok = (p.pins["2"], p.pins["1"]) == tuple(m(x) for x in e[:2])
            elif src[0] == "X":
                model = e[-1].upper()
                if model == "REG78L05":
                    ok = (p.pins["3"], p.pins["1"], p.pins["2"]) == tuple(m(x) for x in e[:3])
                else:
                    unit = LM_UNIT[name] if model == "LM324" else k + 1
                    pn = OPAMP_PINS[model][unit]
                    ok = tuple(p.pins[str(x)] for x in pn) == tuple(m(x) for x in e[:5])
            else:
                ok = True
            checked += 1
            if not ok:
                errs += 1
                print(f"  MISMATCH {p.ref} {p.value} ({name}): design {p.pins} vs sim {e}")
    unused = sorted(set(els) - used)
    print(f"checked {checked} simulated elements against the design: {errs} mismatches")
    print("simulation elements without a design part:", unused)
    return errs


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
