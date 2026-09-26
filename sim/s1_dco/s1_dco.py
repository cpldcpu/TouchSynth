"""S1 - DCO core: TL072 integrator, LM324 V->I charge sink, 2N7002 reset via NPN level shifter.

Checks: saw amplitude vs note (CV_AMP law incl. 12-bit quantisation), reset recovery,
TL072 headroom, at V+ = 8.6 V (9 V in) and 11.6 V (12 V in).
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import spice
import plotstyle as ps
import voice

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# --- design values -----------------------------------------------------------
C_INT = 10e-9      # integrator cap
RE = 33e3          # V->I emitter resistor
K_DIV = voice.LIN_RATIO   # load-aware LIN CV network DC ratio
A_TGT = 2.0        # target saw amplitude [Vpp]
TP = 3e-6          # reset pulse width (MCU low)
VREF = 4.5
PWM_BITS = 12
RGS = float(os.environ.get('RGS', 2.2e3))  # gate series resistor


def cv_for(f):
    """Firmware law: CV_AMP so that I*(T-TP)/C = A_TGT, quantised to 12 bit."""
    T = 1 / f
    i = A_TGT * C_INT / (T - TP)
    cv = i * RE / K_DIV
    code = round(cv / 5.0 * (2**PWM_BITS - 1))
    return code / (2**PWM_BITS - 1) * 5.0, code


NET = """* S1 DCO f={f:.3f}Hz V+={vp}
{PRE}
VPLUS vp 0 {vp}
VREF vref 0 {vref}
VCV cv 0 {cv:.6f}
{cvnet}
XU1 cvd ve vp 0 u1o LM324
RB1 u1o b1 1k
Q1 n b1 ve MMBT3904
RE ve 0 {re}
XU2 vref n vp 0 saw TL072
CI saw n {cint}
M1 saw g n 2N7002
RGS gd g {rgs}
RG vp gd 10k
Q2 gd b2 0 MMBT3904
RB2 mcu b2 4.7k
VMCU mcu 0 PULSE(5 0 {td} 20n 20n {tp} {T})
{CTRL}
tran {tstep} {tstop} 0 {tmax}
wrdata {{OUT}}/{name}.dat v(saw) v(g) v(mcu) v(n)
.endc
.end
"""


def simulate(midi, vp):
    f = 440 * 2 ** ((midi - 69) / 12)
    T = 1 / f
    cv, code = cv_for(f)
    name = f"dco_m{midi}_v{vp}".replace(".", "p")
    net = NET.format(cvnet=voice.CVNET_LIN.format(n='A', src='cv', x='cvd'), rgs=RGS, f=f, vp=vp, vref=VREF, cv=cv, re=RE, cint=C_INT, td=T * 0.5, tp=TP, T=T,
                     tstep=T / 4000, tstop=T * 3.5, tmax=min(T / 4000, 0.2e-6 * 50),
                     name=name, PRE=spice.PREAMBLE, CTRL=spice.CTRL_HEAD)
    spice.run(net, OUT, name)
    d = spice.load(os.path.join(OUT, name + ".dat"))
    t, saw = d["time"], d["v(saw)"]
    # analyse the cycle between 2nd and 3rd pulse
    t0 = T * 1.5 + TP
    sel = (t > t0) & (t < t0 + T - TP)
    ts, seg = t[sel] - t0, saw[sel]
    Te = T - TP
    fit = (ts > 0.1 * Te) & (ts < 0.9 * Te)
    k, c = np.polyfit(ts[fit], seg[fit], 1)
    amp = k * Te
    # glitch: deviation from the fitted line during the first 2 us after the switch opens
    g = ts < 2e-6
    glitch = np.max(np.abs(seg[g] - (k * ts[g] + c))) if g.any() else 0.0
    return dict(midi=midi, f=f, vp=vp, cv=cv, code=code, amp=amp, vmin=c, vmax=c + amp, glitch=glitch,
                t=t, saw=saw, g=d["v(g)"], mcu=d["v(mcu)"], T=T)


def main():
    os.makedirs(OUT, exist_ok=True)
    notes = list(range(24, 109, 6))  # C1 .. C8
    res = {vp: [simulate(m, vp) for m in notes] for vp in (8.6, 11.6)}

    lines = ["| note | f [Hz] | CV_AMP [V] | code | amp @8.6V | amp @11.6V | ramp @8.6V | glitch pk @8.6V |",
             "|---|---|---|---|---|---|---|---|"]
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    worst = 0
    for a, b in zip(res[8.6], res[11.6]):
        nn = f"{names[a['midi'] % 12]}{a['midi'] // 12 - 1}"
        lines.append(f"| {nn} | {a['f']:.1f} | {a['cv']:.4f} | {a['code']} | {a['amp']:.3f} | {b['amp']:.3f} | "
                     f"{a['vmin']:.3f}…{a['vmax']:.3f} | {a['glitch']*1e3:.0f} mV |")
        worst = max(worst, abs(a['amp'] / A_TGT - 1), abs(b['amp'] / A_TGT - 1))
    lines.append("")
    allamp = np.array([x["amp"] for vp in res for x in res[vp]])
    mean = allamp.mean()
    lines.append(f"Mean amplitude {mean:.3f} Vpp (gain error {100*(mean/A_TGT-1):+.1f} %, removed by one firmware "
                 f"calibration constant); flatness across notes and supplies: "
                 f"{100*(allamp.min()/mean-1):+.1f} % / {100*(allamp.max()/mean-1):+.1f} % (spec ±5 %)")
    table = "\n".join(lines)
    print(table)
    with open(os.path.join(OUT, "s1_results.md"), "w") as f:
        f.write(table + "\n")

    ps.save_csv("s1_cal", ["dco_gain"], [[mean / A_TGT]])
    # data for the report
    ps.save_csv("s1_dco", ["midi", "f_hz", "cv_amp_v", "pwm_code", "amp_8v6", "amp_11v6", "ramp_start_v", "glitch_mv"],
                [[a["midi"], a["f"], a["cv"], a["code"], a["amp"], b["amp"], a["vmin"], a["glitch"] * 1e3]
                 for a, b in zip(res[8.6], res[11.6])])

    # Fig. s1_waveforms: (a) saw over two periods, (b) reset detail
    f, ax = ps.fig(2, 1, aspect=0.75)
    for r in [res[8.6][0], res[8.6][6], res[8.6][-2]]:
        T = r["T"]
        sel = (r["t"] > T * 1.4) & (r["t"] < T * 3.5)
        ax[0].plot((r["t"][sel] - T * 1.5) / T, r["saw"][sel], label=f"{r['f']:.0f} Hz")
    ax[0].set(xlabel="$t/T$", ylabel="$V_\mathrm{saw}$ [V]")
    ax[0].legend(loc="upper left")
    r = res[8.6][-1]
    T = r["T"]; t0 = T * 2.5
    sel = (r["t"] > t0 - 1e-6) & (r["t"] < t0 + 6e-6)
    x = (r["t"][sel] - t0) * 1e6
    ax[1].plot(x, r["mcu"][sel], "--", color=ps.C[6], lw=0.8, label="MCU pin")
    ax[1].plot(x, r["g"][sel], color=ps.C[1], label="2N7002 gate")
    ax[1].plot(x, r["saw"][sel], color=ps.C[0], label="saw")
    ax[1].set(xlabel="$t$ [µs]", ylabel="[V]")
    ax[1].legend(loc="lower left", bbox_to_anchor=(0.55, 0.3))
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, "s1_dco_waveforms")

    # Fig. s1_amplitude: (a) amplitude vs note, (b) CV law
    f, ax = ps.fig(2, 1, aspect=0.75)
    for i, vp in enumerate((8.6, 11.6)):
        ax[0].semilogx([x["f"] for x in res[vp]], [x["amp"] for x in res[vp]], "o-", color=ps.C[i],
                       label=f"$V_+$ = {vp} V")
    ax[0].axhspan(mean * 0.95, mean * 1.05, color=ps.C[2], alpha=.12, lw=0, label="±5 % of mean")
    ax[0].set(xlabel="$f$ [Hz]", ylabel="saw amplitude [V$_\mathrm{pp}$]", ylim=(1.8, 2.1))
    ax[0].legend(loc="lower right")
    ax[1].loglog([x["f"] for x in res[8.6]], [x["cv"] for x in res[8.6]], "o-")
    ax2 = ax[1].twinx(); ax2.grid(False)
    ax2.loglog([x["f"] for x in res[8.6]], [x["code"] for x in res[8.6]], alpha=0)
    ax2.set_ylabel("12-bit PWM code")
    ax[1].set(xlabel="$f$ [Hz]", ylabel="$CV_\mathrm{AMP}$ [V]")
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, "s1_dco_amplitude")


if __name__ == "__main__":
    main()
