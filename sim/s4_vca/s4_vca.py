"""S4 - main VCA: gain vs CV_VCA, off-attenuation (with LM324 offset), THD, CV feedthrough."""
import os, sys, re
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import spice
import plotstyle as ps
import voice

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
RG = os.environ.get("RG", "22k")

HEAD = """
VPLUS vp 0 8.6
V5 v5 0 5
VREF vref 0 4.5
""" + voice.BIAS


def vca(x="xo", rc2="4.7k", vbe_off=0.0, roff="470k", vt=2.5):
    s = voice.VCA.format(inp="lpfin", vbe_off=vbe_off, rc2=rc2, n="V", x=x, rg=RG)
    s += f"VTR vdac 0 {vt}\nRDAC vdac vtrim 100k\n"   # R-2R DAC: Thevenin = code/256*5 V, 100k
    return s.replace("ROFFV v5 veV 470k", f"ROFFV v5 veV {roff}")


def ac_gain(cv, vos=0.0, roff="470k"):
    name = f"ac_cv{cv}_os{vos}_r{roff}".replace(".", "p").replace("-", "m")
    net = f"""* S4 AC
{spice.PREAMBLE}{HEAD}
VCV cvv 0 {cv}
{voice.CVNET_LIN.format(n='V', src='cvv', x='xv')}
VOS xo xv {vos}
VLPF lpfin 0 DC 4.5 AC 1
{vca(roff=roff)}
{spice.CTRL_HEAD}
ac lin 1 1k 1k
print vdb(lineout)
.endc
.end
"""
    log = spice.run(net, OUT, name)
    return float(re.search(r"vdb\(lineout\)\s*=\s*([-\d.e+]+)", log).group(1))


def thd(amp, cv=5.0):
    name = f"thd_a{amp}".replace(".", "p")
    net = f"""* S4 THD
{spice.PREAMBLE}{HEAD}
VCV cvv 0 {cv}
{voice.CVNET_LIN.format(n='V', src='cvv', x='xv')}
VOS xo xv 0
VLPF lpfin 0 SIN(4.5 {amp/2} 1k)
{vca()}
{spice.CTRL_HEAD}
tran 1u 60m 0 1u
fourier 1k v(lineout)
meas tran vpp PP v(lineout) from=50m to=60m
.endc
.end
"""
    log = spice.run(net, OUT, name)
    t = float(re.search(r"THD:\s*([\d.e+-]+)", log).group(1))
    vpp = float(re.search(r"vpp\s*=\s*([\d.e+-]+)", log).group(1))
    return t, vpp


def feedthrough(rc2, vbe_off, vt=2.5):
    name = f"ft_{rc2}_{vbe_off}_{vt:.4f}".replace(".", "p").replace("-", "m")
    net = f"""* S4 CV feedthrough
{spice.PREAMBLE}{HEAD}
VCV cvv 0 PWL(0 0 20m 0 20.001m 5 60m 5 60.001m 0 100m 0)
{voice.CVNET_LIN.format(n='V', src='cvv', x='xv')}
VOS xo xv 0
VLPF lpfin 0 4.5
{vca(rc2=rc2, vbe_off=vbe_off, vt=vt)}
{spice.CTRL_HEAD}
tran 5u 100m 0 5u
wrdata {{OUT}}/{name}.dat v(lineout) v(xv)
.endc
.end
"""
    spice.run(net, OUT, name)
    d = spice.load(os.path.join(OUT, name + ".dat"))
    return d["time"], d["v(lineout)"], d["v(xv)"]


def main():
    os.makedirs(OUT, exist_ok=True)
    cvs = np.round(np.arange(0, 5.01, 0.25), 2)
    curves = {}
    for label, vos, roff in [("nominal", 0.0, "470k"), ("+7 mV offset", 7e-3, "470k"),
                             ("+7 mV, no 470k", 7e-3, "1e12")]:
        curves[label] = [ac_gain(c, vos, roff) for c in cvs]
        print(label, " ".join(f"{g:.1f}" for g in curves[label]))
    full = curves["nominal"][-1]
    off_nom = full - curves["nominal"][0]
    off_os = full - curves["+7 mV offset"][0]
    off_noroff = full - curves["+7 mV, no 470k"][0]
    print(f"gain full {full:.1f} dB; off attenuation: nominal {off_nom:.0f} dB, +7mV {off_os:.0f} dB, "
          f"+7mV without 470k {off_noroff:.0f} dB")
    thds = [(a, *thd(a)) for a in (0.3, 0.6, 1.2)]
    for a, t, v in thds:
        print(f"THD @ {a} Vpp in (CV 5 V): {t:.2f} %  out {v:.2f} Vpp")
    # CV feedthrough ("thump"): mismatch cases, firmware trim calibration (2-point + 8-bit quantisation)
    def step(t, v):
        return v[(t > 50e-3) & (t < 60e-3)].mean() - v[(t > 12e-3) & (t < 20e-3)].mean()
    ft, cal = {}, []
    cases = [("matched", "4.7k", 0.0), ("A: +1 % Rc, +1 mV", "4.747k", 1e-3), ("B: −1 % Rc, −2 mV", "4.653k", -2e-3)]
    for label, rc2, off in cases:
        t, v, x = feedthrough(rc2, off)
        s0 = step(t, v)
        if label == "matched":
            ft["matched, mid code"] = (t, v, x)
            cal.append((label, s0, s0, 128, 0))
            print(f"feedthrough {label}: {s0*1e3:.1f} mV step")
            continue
        t1, v1, _ = feedthrough(rc2, off, vt=3.5)
        s1 = step(t1, v1)
        vt0 = 2.5 - s0 * (3.5 - 2.5) / (s1 - s0)
        code = int(np.clip(round(vt0 / 5 * 256), 0, 255))
        tc, vc, _ = feedthrough(rc2, off, vt=code / 256 * 5)
        sc = step(tc, vc)
        ft[label + ", raw"] = (t, v, x)
        ft[label + f", trim {code}"] = (tc, vc, x)
        cal.append((label, s0, sc, code, vt0))
        print(f"feedthrough {label}: untrimmed {s0*1e3:.1f} mV, trimmed (code {code}) {sc*1e3:.2f} mV")
    ps.save_csv("s4_vca_feedthrough", ["case", "step_untrimmed_v", "step_trimmed_v", "trim_code", "vt_null_v"],
                [list(c) for c in cal])
    ps.save_csv("s4_vca_gain", ["cv_vca_v"] + [k.replace(",", "") for k in curves],
                [[c] + [curves[k][i] for k in curves] for i, c in enumerate(cvs)])
    ps.save_csv("s4_vca_thd", ["vin_pp", "thd_pct", "vout_pp"], [list(x) for x in thds])

    f, ax = ps.fig(2, 1, aspect=0.75)
    for i, k in enumerate(curves):
        ax[0].plot(cvs, np.array(curves[k]) - full, "o-" if i == 0 else ".-", color=ps.C[i], label=k)
    ax[0].set(xlabel=r"$CV_\mathrm{VCA}$ [V]", ylabel="gain re full [dB]", ylim=(-110, 5))
    ax[0].axhline(-70, color=ps.C[6], lw=0.6, ls="--")
    ax[0].legend(loc="lower right")
    for i, k in enumerate(ft):
        t, v, x = ft[k]
        ax[1].plot(t * 1e3, (v - 0) * 1e3, color=ps.C[i], lw=0.9, ls="-" if "trim" in k or "mid code" in k else "--",
                   label=k)
    ax[1].set(xlabel="$t$ [ms]", ylabel="line out [mV]", xlim=(10, 100), ylim=(-140, 260))
    axr = ax[1].twinx(); axr.grid(False)
    k0 = next(iter(ft)); axr.plot(ft[k0][0] * 1e3, ft[k0][2], color=ps.C[6], lw=0.6, ls=":")
    axr.set_ylabel("CV node [V] (dotted)")
    ax[1].legend(loc="upper right", fontsize=6.5)
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, "s4_vca")


if __name__ == "__main__":
    main()
