"""Bring-up expectations: DC operating point at every board test point, MCU not fitted.

Without the MCU its pins float (no source on the PWM, PULSE, SUB and NOISE nodes):
- the linear CV networks (AMP, RES, VCA) are pulled to 0 V by their 15k last-stage resistor;
- the cutoff network has no DC path of its own, so XCUT_IN floats up to VBIAS through the expo divider and the
  ladder tail runs at the expo reference current (about 8 uA) instead of ~0;
- the DCO level shifter has no base drive, so the reset MOSFET is on and SAW sits at VREF.
The 74HC595 outputs come up random: VTRIM can be anywhere in 0.4..5 V and any number of the 16 red LEDs may light
(about 0.68 mA each), so the +5 V load is bracketed 0 / 10.9 mA.

Revised 2026-10-17 after the first board: the first version drove the PWM nodes to 0 V (MCU fitted, outputs low),
which is wrong for XCUT_IN / TAIL / VBIAS; the TL072 model supply current was corrected (models.lib).

  python bringup_op.py      -> docs/results/bringup_expected.csv and a table on stdout
"""
import os, sys, re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "s7_power"))
import spice
import plotstyle as ps
from s7_power import POWER, voice_quiet

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# board test-point net -> simulation node
TP = [("VP", "vp"), ("+5V", "v5"), ("VREF", "vref"), ("VBIAS", "vbias"), ("V25", "v25"),
      ("VB0", "vb0"), ("VB2", "vb2"), ("VB4", "vb4"), ("TAIL", "tail"), ("LPF", "lpf"), ("XCUT_IN", "bC"),
      ("SAW", "saw"), ("XAMP", "xamp"), ("XRES", "xres"), ("RESOUT", "resout"), ("XVCA", "xvv"),
      ("VCAOUT", "vcaout"), ("VTRIM", "vtrim")]


def op(vin, i_logic, vtrim):
    name = f"op_{vin:g}_{i_logic*1e3:g}_{vtrim:g}".replace(".", "p")
    net = voice_quiet(cv_cut=0.0, cv_res=0.0, cv_vca=0.0).replace("VTR vdac 0 2.025", f"VTR vdac 0 {vtrim}")
    # MCU absent: remove the PWM-average sources, leave the MCU-driven mixer inputs open
    net = "\n".join(l for l in net.splitlines() if not re.match(r"Bcv[acrv] ", l))
    for r, nc in (("RMP", "nc_pulse"), ("RMU", "nc_sub"), ("RMN", "nc_noise")):
        net = net.replace(f"{r} 0 mx", f"{r} {nc} mx")
    vecs = " ".join(f"v({n})" for _, n in TP)
    text = f"""* bring-up operating point
{spice.PREAMBLE}
{POWER.format(vin_src=str(vin), i_logic=f'{i_logic}')}
{net}
{spice.CTRL_HEAD}
op
print {vecs} i(VIN)
.endc
.end
"""
    log = spice.run(text, OUT, name)
    val = {}
    for _, n in TP:
        val[n] = float(re.search(rf"v\({re.escape(n.lower())}\)\s*=\s*([-\d.e+]+)", log).group(1))
    val["iin"] = -float(re.search(r"i\(vin\)\s*=\s*([-\d.e+]+)", log).group(1))
    return val


def main():
    cases = {(vin, il, vt): op(vin, il, vt) for vin in (9.0, 12.0) for il in (0.0, 0.0109) for vt in (0.0, 5.0)}
    rows = []
    print(f"{'test point':10s} {'9 V':>16s} {'12 V':>16s}   (ranges over random 595 state)")
    for tp, n in TP + [("I_in [mA]", "iin")]:
        cells, row = [], [tp]
        for vin in (9.0, 12.0):
            v = [c[n] * (1e3 if n == "iin" else 1) for (vi, _, _), c in cases.items() if vi == vin]
            lo, hi = min(v), max(v)
            row += [lo, hi]
            cells.append(f"{lo:7.3f}" if hi - lo < 5e-3 else f"{lo:7.3f}..{hi:.3f}")
        rows.append(row)
        print(f"{tp:10s} {cells[0]:>16s} {cells[1]:>16s}")
    ps.save_csv("bringup_expected", ["testpoint", "v9_min", "v9_max", "v12_min", "v12_max"], rows)


if __name__ == "__main__":
    main()
