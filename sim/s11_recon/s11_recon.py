"""S11 - the DAC's reconstruction filter and mixer resistor on the 5 V voice core (S10, variant v5m when
Microchip's MCP6002 model is installed, else v5r).

The PWM DAC pin swings 0...3.3 V (MCU on the 3.3 V LDO). It feeds a unity-gain 2-pole Sallen-Key low-pass
(R = 10k, 10k; MCP6002 half) whose output drives the ladder's mixer node through R_mix; with the dual-PWM option
the low byte joins at the filter input through 1.28 MΩ (128:1, 7 + 7 bit). AC analysis, filter open (CV_CUT full
scale), resonance off, VCA full:
  - R_mix for the drive level of rev 0.1's saw (2 Vpp through 150k): the DAC's full scale is 3.3 Vpp;
  - the filter's droop at 10 and 20 kHz (filter output re the DAC pin);
  - the carrier at the line out: the PWM fundamental (2.1 V peak at 50 % duty, centre-aligned) re a full-scale
    1 kHz tone, at 93.75 kHz (dual-PWM option) and 187.5 kHz (standard), without and with the filter.
Not modelled: crosstalk around the filter through the layout (board 1: 5.8 mV at the line out from the
93.75 kHz carrier).

  python s11_recon.py           results: docs/results/s11_recon.csv
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "s10_5v"), os.path.join(HERE, "..", "lib")]
import s10_5v as T                                        # noqa: E402
import spice                                              # noqa: E402
import plotstyle as ps                                    # noqa: E402

V = T.VARIANTS.get("v5m", T.VARIANTS["v5r"])
FULL = 3.3                                                # DAC full scale [Vpp]
CAR_PK = 4 / np.pi * FULL / 2                             # PWM fundamental at 50 % duty [V peak]
R_SAW, SAW_PP = 150e3, 2.0                                # rev 0.1 saw into the mixer


def sk(fc, r=10e3):
    """Unity-gain 2-pole Butterworth Sallen-Key: equal R, C1 (feedback) = 2 C2."""
    c2 = 1 / (2 * np.pi * r * fc * np.sqrt(2))
    return dict(r=r, c1=2 * c2, c2=c2, fc=fc)


def sk3(fc0, fc):
    """Third pole as an RC (10k, C0) in front of the Sallen-Key (assembly option for the dual-PWM DAC)."""
    return dict(sk(fc), r0=10e3, c0=1 / (2 * np.pi * 10e3 * fc0))


FILTERS = {"none": None, "sk30k": sk(30e3), "sk25k": sk(25e3), "sk20k": sk(20e3), "sk15k": sk(15e3),
           "rc25k_sk30k": sk3(25e3, 30e3), "rc20k_sk25k": sk3(20e3, 25e3)}


def net(v, flt, rmix, src):
    """Core with the DAC chain; src = 'dac' (AC on the DAC pin) or 'saw' (AC on the old saw input)."""
    s = T.core(v, cvcut=5.0 * T.fs(v), cvres=0.0, cvvca=5.0 * T.fs(v),
               saw="DC 0 AC 1" if src == "saw" else "DC 0 AC 0")
    s += f"VDAC dacpin 0 DC {FULL / 2} AC {1 if src == 'dac' else 0}\n"
    if flt is None:
        s += f"RMIX dacpin mx {rmix:.0f}\n"
    else:
        oa = "MCP6001" if v.get("vendor") else "OPB"
        a = "dacpin"
        if "c0" in flt:                                    # optional third pole: RC in front
            s += f"RSK0 dacpin sk0 {flt['r0']:.0f}\nCSK0 sk0 0 {flt['c0']:.4g}\n"
            a = "sk0"
        s += (f"RSK1 {a} sk1 {flt['r']:.0f}\nRSK2 sk1 sk2 {flt['r']:.0f}\n"
              f"CSK1 sk1 skout {flt['c1']:.4g}\nCSK2 sk2 0 {flt['c2']:.4g}\n"
              f"XSK sk2 skout vp 0 skout {oa}\nRMIX skout mx {rmix:.0f}\n")
    return s


def ac(tag, v, flt, rmix, src):
    name = f"s11_{tag}_{src}"
    probe = "vm(lineout) vm(skout)" if flt else "vm(lineout)"
    net_ = net(v, flt, rmix, src)
    spice.run(f"* S11 {name}\n{T.head(v)}\n{net_}\n{spice.CTRL_HEAD}\nac dec 40 100 400k\n"
              f"wrdata {{OUT}}/{name}.dat {probe}\n.endc\n.end\n", T.wdir(v), name)
    return spice.load(os.path.join(T.wdir(v), name + ".dat"))


def at(d, key, f0):
    return float(np.interp(np.log10(f0), np.log10(d["frequency"]), d[key]))


def main():
    os.makedirs(T.OUT, exist_ok=True)
    print("variant:", "v5m (MCP6002 vendor model)" if V.get("vendor") else "v5r (behavioural MCP6002)")
    # drive level of the old saw: line-out amplitude for 2 Vpp through 150k
    d = ac("ref", V, None, 1e9, "saw")
    saw_out = at(d, "vm(lineout)", 1e3) * SAW_PP / 2
    # DAC direct through R_mix: R_mix for the same line-out amplitude at full scale (linear in 1/R_mix)
    r_try = 240e3
    d = ac("try", V, None, r_try, "dac")
    dac_out = at(d, "vm(lineout)", 1e3) * FULL / 2
    rmix = r_try * dac_out / saw_out
    rmix_e = min([200e3, 220e3, 240e3, 270e3, 300e3], key=lambda r: abs(np.log(r / rmix)))
    print(f"saw drive level: {saw_out * 2e3:.0f} mVpp at the line out; R_mix for the DAC (3.3 Vpp): "
          f"{rmix / 1e3:.0f}k -> {rmix_e / 1e3:.0f}k")
    rows = [["rmix_k", round(rmix / 1e3, 1)], ["rmix_e12_k", rmix_e / 1e3]]
    for tag, flt in FILTERS.items():
        d = ac(tag, V, flt, rmix_e, "dac")
        sig = at(d, "vm(lineout)", 1e3) * FULL / 2
        res = {f: 20 * np.log10(at(d, "vm(lineout)", f) * CAR_PK / sig) for f in (93.75e3, 187.5e3)}
        droop = {f: 20 * np.log10(at(d, "vm(skout)", f) / at(d, "vm(skout)", 1e3)) for f in (10e3, 20e3)} if flt else {}
        desc = f"C1 {flt['c1'] * 1e9:.2f}n, C2 {flt['c2'] * 1e9:.2f}n" if flt else "direct"
        print(f"{tag:6s} ({desc}): carrier at the line out re full scale: 93.75 kHz {res[93.75e3]:6.1f} dB, "
              f"187.5 kHz {res[187.5e3]:6.1f} dB" + (f"; filter droop 10 kHz {droop[10e3]:.2f} dB, "
                                                     f"20 kHz {droop[20e3]:.2f} dB" if flt else ""))
        rows += [[f"carrier_93k_db_{tag}", round(res[93.75e3], 1)], [f"carrier_188k_db_{tag}", round(res[187.5e3], 1)]]
        if flt:
            rows += [[f"droop_10k_db_{tag}", round(droop[10e3], 2)], [f"droop_20k_db_{tag}", round(droop[20e3], 2)],
                     [f"c1_nf_{tag}", round(flt["c1"] * 1e9, 3)], [f"c2_nf_{tag}", round(flt["c2"] * 1e9, 3)]]
    ps.save_csv("s11_recon", ["quantity", "value"], rows)


if __name__ == "__main__":
    main()
