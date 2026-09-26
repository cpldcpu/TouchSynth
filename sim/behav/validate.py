"""Validate the behavioural model against ngspice: (1) S3 self-oscillation amplitude (fit RSOFT),
(2) S6 full voice on the identical firmware stimulus."""
import os, sys, csv
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "s6_voice"))
import behav as B
import plotstyle as ps
import spice

HERE = os.path.dirname(os.path.abspath(__file__))


def selfosc(cvres, rsoft, cvcut=2.5, t_end=0.3):
    n_ms = int(t_end / B.T_CV)
    ev = dict(t_end=t_end, reset=np.array([]), pulse=([], []), sub=([], []), noise=([0.001, 0.00102], [5.0, 0.0]))
    cv = dict(amp=np.zeros(n_ms), cut=np.full(n_ms, cvcut), res=np.full(n_ms, cvres), vca=np.full(n_ms, 5.0))
    _, sig = B.analog(ev, cv, rsoft=rsoft)
    lpf = sig["lpf"]; t = np.arange(len(lpf)) / B.FS
    seg = lpf[t > t_end - 0.05]
    zc = np.where(np.diff(np.sign(seg - seg.mean())) > 0)[0]
    f = (len(zc) - 1) / ((zc[-1] - zc[0]) / B.FS) if len(zc) > 2 else np.nan
    return np.ptp(seg), f


def edges_from_pwl(pts, falling_only=False):
    t, l = [], []
    prev = pts[0][1]
    for tt, v in pts[1:]:
        if v != prev:
            if not falling_only or v < prev:
                t.append(tt); l.append(v)
            prev = v
    return np.array(t), np.array(l)


def main():
    # ---- (1) pole ratio from the S3 self-oscillation pitch, amplitude check
    with open(os.path.join(B.RES, "s3_selfosc.csv")) as fh:
        rows = [list(map(float, r)) for r in list(csv.reader(fh))[1:]]
    spice_pts = [(r[0], r[2], r[3]) for r in rows if r[0] >= B.RES_THRESH + 0.2]
    f_sp = np.mean([p[2] for p in spice_pts])
    B.POLE_RATIO = 0.435
    for _ in range(3):
        f_m = np.mean([selfosc(cvr, B.RSOFT)[1] for cvr, _, _ in spice_pts])
        B.POLE_RATIO *= f_m / f_sp
    print(f"POLE_RATIO fitted: {B.POLE_RATIO:.4f}")
    best = None
    for sl in (0.5, 1.0, 2.0, 4.0, 8.0):
        B.K_SLOPE = sl
        e = np.sqrt(np.mean([np.log(selfosc(cvr, B.RSOFT)[0] / vpp) ** 2 for cvr, vpp, _ in spice_pts]))
        print(f"K_SLOPE {sl}: rms log amplitude error {e:.3f}")
        if best is None or e < best[1]:
            best = (sl, e)
    B.K_SLOPE = best[0]
    ps.save_csv("behav_cal", ["pole_ratio", "k_slope"], [[B.POLE_RATIO, B.K_SLOPE]])
    rs = B.RSOFT
    osc = [(cvr, vpp, f, *selfosc(cvr, rs)) for cvr, vpp, f in spice_pts]
    for o in osc:
        print(f"CV_RES {o[0]}: SPICE {o[1]*1e3:.0f} mVpp @ {o[2]:.0f} Hz | model {o[3]*1e3:.0f} mVpp @ {o[4]:.0f} Hz")

    # ---- (2) S6 score through the model
    import s6_voice as S6
    reset, pulse, sub, ts, amp, cutv, resv, vcav = S6.firmware()
    rt, _ = edges_from_pwl(reset, falling_only=True)
    ev = dict(t_end=S6.T_END, reset=rt, pulse=edges_from_pwl(pulse), sub=edges_from_pwl(sub), noise=([], []))
    cv = dict(amp=np.array(amp), cut=np.array(cutv), res=np.array(resv), vca=np.array(vcav))
    y, sig = B.analog(ev, cv, rsoft=rs)
    d = spice.load(os.path.join(os.path.dirname(HERE), "s6_voice", "out", "voice.dat"))
    tw = np.arange(len(y)) / B.FS_OUT
    ys = np.interp(tw, d["time"], d["v(lineout)"])
    sel = tw > 0.1
    ys -= ys[sel].mean(); y -= y[sel].mean()
    # metrics: per-50 ms RMS level and spectral centroid
    def frames(x):
        L = 2400
        k = len(x) // L
        X = np.abs(np.fft.rfft(x[:k * L].reshape(k, L) * np.hanning(L), axis=1))
        fq = np.fft.rfftfreq(L, 1 / B.FS_OUT)
        rms = np.sqrt(np.mean(x[:k * L].reshape(k, L) ** 2, axis=1))
        cen = (X * fq).sum(1) / (X.sum(1) + 1e-12)
        return rms, cen
    rm, cm = frames(y); rsp, csp = frames(ys)
    m = rsp > 0.02
    lvl = 20 * np.log10(rm[m] / rsp[m])
    cen = 1200 * np.log2(cm[m] / csp[m])
    print(f"S6 level difference model-SPICE: mean {lvl.mean():+.2f} dB, rms {np.sqrt(np.mean(lvl**2)):.2f} dB")
    print(f"S6 spectral centroid difference: mean {cen.mean():+.0f} cent, rms {np.sqrt(np.mean(cen**2)):.0f} cent")
    with open(os.path.join(HERE, "rsoft.txt"), "w") as fh:
        fh.write(f"{rs}\n")
    ps.save_csv("behav_validation", ["metric", "value"],
                [["pole_ratio", B.POLE_RATIO], ["k_slope", B.K_SLOPE], ["level_mean_db", lvl.mean()], ["level_rms_db", np.sqrt(np.mean(lvl**2))],
                 ["centroid_mean_cent", cen.mean()], ["centroid_rms_cent", np.sqrt(np.mean(cen**2))]])

    import matplotlib.pyplot as plt
    f, ax = plt.subplots(2, 2, figsize=(ps.FULL, 4.2))
    for a, (t0, t1) in zip(ax[0], [(0.75, 0.77), (3.0, 3.02)]):
        s = (tw > t0) & (tw < t1)
        a.plot((tw[s] - t0) * 1e3, ys[s], color=ps.C[0], label="ngspice")
        a.plot((tw[s] - t0) * 1e3, y[s], color=ps.C[1], ls="--", label="behavioural")
        a.set(xlabel=f"$t$ [ms] (from {t0} s)", ylabel="line out [V]")
    ax[0, 0].legend(loc="lower left")
    tf = np.arange(len(rm)) * 0.05 + 0.025
    ax[1, 0].plot(tf, 20 * np.log10(rsp + 1e-6), color=ps.C[0], label="ngspice")
    ax[1, 0].plot(tf, 20 * np.log10(rm + 1e-6), color=ps.C[1], ls="--", label="behavioural")
    ax[1, 0].set(xlabel="$t$ [s]", ylabel="RMS level [dBV]", ylim=(-50, 0))
    ax[1, 1].plot(tf, csp, color=ps.C[0]); ax[1, 1].plot(tf, cm, color=ps.C[1], ls="--")
    ax[1, 1].set(xlabel="$t$ [s]", ylabel="spectral centroid [Hz]")
    for i, a in enumerate(ax.flat):
        a.text(-0.16, 1.02, f"({chr(97 + i)})", transform=a.transAxes, fontsize=9, va="bottom")
    f.tight_layout()
    ps.save(f, "behav_validation")


if __name__ == "__main__":
    main()
