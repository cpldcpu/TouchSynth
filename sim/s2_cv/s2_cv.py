"""S2 - PWM -> CV filters (TIM1, 10 bit @ 48 MHz / 1024 = 46.9 kHz + 2-bit sigma-delta dither = 12 bit).

Two variants of the same 3-pole RC chain:
  LIN : PWM -30R- 1k -[100n]- 4k7 -[33n]- 4k7 -+- 15k||22n -> LM324 +in (DCO amp, RES, VCA)
  EXP : PWM -30R- 1k -[100n]- 4k7 -[33n]- 33k -+- 1k5||100n to VBIAS -> expo base (cutoff)
Checks: ripple at worst-case duty 50 %, 10->90 % step settling (to 0.1 % of step), small-step settling.
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import spice
import plotstyle as ps
import voice

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
FPWM = 48e6 / 1024
LSB = 1 / 1024
TPWM = 1 / FPWM
VT = 0.02585

NET = """* S2 CV filter {name}
{PRE}
VBIAS vb 0 1.5
* PWM: duty d1 until t_step, then d2 (B-source comparator against sawtooth carrier)
VCAR car 0 PULSE(0 1 0 {tpwm} 1n {tpwm1} {tpwm})
VD duty 0 PWL(0 {d1} {tstep} {d1} {tstep2} {d2})
* 2-bit sigma-delta dither, worst case fraction 1/2: +1 LSB every other PWM period
VDI dith 0 PULSE(0 1 0 1n 1n {tpwm1} {tpwm2})
BPWM pwmi 0 V = (v(duty) + {lsb}*v(dith)) > v(car) ? 5 : 0
RSRC pwmi pwm 30
{last}
{CTRL}
tran 0.1u {tstop} 0 0.1u
wrdata {{OUT}}/{name}.dat v(x) v(duty)
.endc
.end
"""
LAST = {
    "LIN": voice.CVNET_LIN.format(n="", src="pwm", x="x") + "XU x x 0 0 0 LM324",   # op-amp input load only
    "EXP": voice.CVNET_EXP.format(n="", src="pwm") + "R3 b x 33k\nR4 x vb 1.5k\nC3 x vb 100n",
}
GAIN = {"LIN": voice.LIN_RATIO, "EXP": voice.EXP_RATIO}


def run(kind, d1, d2, name, tstop=6e-3, tstep=2e-3):
    net = NET.format(name=name, PRE=spice.PREAMBLE, CTRL=spice.CTRL_HEAD, tpwm=TPWM, tpwm1=TPWM - 2e-9, tpwm2=2 * TPWM, lsb=LSB,
                     d1=d1, d2=d2, tstep=tstep, tstep2=tstep + 1e-9, tstop=tstop, last=LAST[kind])
    # the LM324 instance above is only there to present its input; tie its output nowhere useful
    net = net.replace("XU x x 0 0 0 LM324", "VCCU vcu 0 9\nXU x fb vcu 0 fb LM324")
    spice.run(net, OUT, name)
    d = spice.load(os.path.join(OUT, name + ".dat"))
    return d["time"], d["v(x)"]


def settle(t, v, t0, v_final, v_start, tol):
    after = t > t0
    err = np.abs(v[after] - v_final) > tol * abs(v_final - v_start)
    idx = np.where(err)[0]
    return (t[after][idx[-1]] - t0) if len(idx) else 0.0


def main():
    rows, res = [], {}
    for kind in ("LIN", "EXP"):
        # ripple at 50 %: steady state after long settle
        t, v = run(kind, 0.5, 0.5, f"{kind}_ripple", tstop=8e-3, tstep=7e-3)
        sel = t > 6e-3
        rip = v[sel].max() - v[sel].min()
        fs = 5 * GAIN[kind]
        # 10 -> 90 % step
        t2, v2 = run(kind, 0.1, 0.9, f"{kind}_step", tstop=8e-3, tstep=2e-3)
        base = 1.5 * (1 - GAIN[kind]) if kind == "EXP" else 0.0
        vs, vf = base + 0.1 * fs, base + 0.9 * fs
        # use the PWM-averaged final value from the tail
        vf_sim = v2[t2 > 7e-3].mean()
        ts1 = settle(t2, v2, 2e-3, vf_sim, vs, 0.01)
        ts01 = settle(t2, v2, 2e-3, vf_sim, vs, 0.001)
        res[kind] = (t, v, t2, v2, fs)
        r = dict(kind=kind, fs=fs, ripple=rip, ripple_db=20 * np.log10(rip / fs), ts1=ts1, ts01=ts01)
        if kind == "EXP":
            r["ripple_cents"] = rip / (VT * np.log(2)) * 1200
        rows.append(r)

    lines = ["| channel | CV full scale at node | ripple pp @50 % | ripple re FS | settle 1 % | settle 0.1 % |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        extra = f" (= {r['ripple_cents']:.1f} cent of cutoff)" if "ripple_cents" in r else ""
        lines.append(f"| {r['kind']} | {r['fs']*1e3:.0f} mV | {r['ripple']*1e6:.0f} µV{extra} | {r['ripple_db']:.1f} dB | "
                     f"{r['ts1']*1e3:.2f} ms | {r['ts01']*1e3:.2f} ms |")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(OUT, "s2_results.md"), "w", encoding="utf-8").write(txt + "\n")
    ps.save_csv("s2_cv", ["channel", "fs_v", "ripple_v", "ripple_db", "settle_1pct_s", "settle_0p1pct_s"],
                [[r["kind"], r["fs"], r["ripple"], r["ripple_db"], r["ts1"], r["ts01"]] for r in rows])

    f, ax = ps.fig(2, 1, aspect=0.75)
    for i, kind in enumerate(("LIN", "EXP")):
        t, v, t2, v2, fs = res[kind]
        base = v2[t2 < 2e-3][-1]
        ax[0].plot((t2 - 2e-3) * 1e3, (v2 - v2[(t2 > 1.5e-3) & (t2 < 2e-3)].mean()) /
                   (v2[t2 > 7e-3].mean() - v2[(t2 > 1.5e-3) & (t2 < 2e-3)].mean()), label=kind)
        sel = (t > 7e-3) & (t < 7e-3 + 3 * TPWM)
        ax[1].plot((t[sel] - 7e-3) * 1e6, (v[sel] - v[sel].mean()) * 1e6, label=kind)
    ax[0].set(xlabel="$t$ [ms]", ylabel="normalised CV", xlim=(-0.5, 4))
    ax[0].axhspan(0.99, 1.01, color=ps.C[2], alpha=.15, lw=0, label="±1 %")
    ax[0].legend(loc="lower right")
    ax[1].set(xlabel="$t$ [µs]", ylabel="ripple [µV]")
    ax[1].legend(loc="upper right")
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, "s2_cv_filter")


if __name__ == "__main__":
    main()
