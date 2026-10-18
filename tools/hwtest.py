#!/usr/bin/env python3
"""Hardware functional tests over the SWIO console (Windows side): runs synthtest.py on the Linux host that has the
WCH-LinkE, parses the replies and evaluates them. Results go to docs/results/hw_<board>_<test>.csv.

  python hwtest.py dco          T4/T5: DCO pitch and saw amplitude across the range (loopback capture)

Lab PC, its working directory and minichlink: LAB_HOST, LAB_DIR, MINICHLINK in tools/lab.conf (see labconf.py).
Loopback scaling: PD5 = 0.6 x VCAOUT, 12-bit ADC (CH32V00x) referenced to +5V (VDD, measured 5.028 V on board 1).
"""
import os, re, sys, subprocess, shlex
import numpy as np
import labconf

HOST = labconf.get("LAB_HOST")
RDIR = labconf.get("LAB_DIR")
MCL = labconf.get("MINICHLINK", "ch32fun/minichlink/minichlink")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VDD, FS, LB = 5.028, 4095, 0.6
BOARD = os.environ.get("HWTEST_BOARD", "board1")


def console(cmds, wait=6.0, timeout=600):
    args = " ".join(shlex.quote(c) for c in cmds)
    rc = (f"cd {RDIR} && MINICHLINK={MCL} timeout {timeout} "
          f"python3 synthtest.py --wait {wait} --idle 0.4 {args}")
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, rc], capture_output=True, text=True, timeout=timeout + 30)
    return out.stdout


def captures(text, raw=False):
    """All 'cap n us elapsed' replies as (us, samples): volts at VCAOUT, or ADC counts with raw=True.
    Warns if the capture ran slower than requested (ADC could not keep up)."""
    res = []
    for m in re.finditer(r"cap (\d+) (\d+)(?: (\d+))?\n((?:[0-9a-f ]+\n)+)", text):
        n, us = int(m.group(1)), int(m.group(2))
        if m.group(3) and int(m.group(3)) > 1.02 * n * us + 20:
            print(f"warning: capture {n} x {us} us took {m.group(3)} us")
        v = np.array([int(x, 16) for x in m.group(4).split()], float)
        res.append((us, v if raw else v * VDD / FS / LB))
    return res


def save_raw(name, us, counts):
    d = os.path.join(ROOT, "docs", "results", f"hw_{BOARD}")
    os.makedirs(d, exist_ok=True)
    np.savetxt(os.path.join(d, name + ".csv"), counts, fmt="%d", header=f"ADC counts (12 bit, VDD {VDD} V), "
               f"PD5 = {LB} x VCAOUT, sample period {us} us", comments="# ")


def saw_period(v, us):
    """Period of a rising saw from its resets: falling crossings of the mid level (the ramp only rises, so every
    falling crossing is a reset, however much the loopback RC smears it), linear interpolation, slope of a line
    fit. Amplitude from a least-squares fit of the fundamental, as the equivalent saw p-p (pi x amplitude), which
    is insensitive to the harmonic roll-off of the filter and the loopback RC. Returns (period_s, n_edges, vpp)."""
    lo, hi_ = np.percentile(v, 5), np.percentile(v, 95)
    mid, arm = 0.5 * (lo + hi_), hi_ - 0.3 * (hi_ - lo)
    t, armed = [], False                           # hysteresis: count a falling crossing only after the signal
    for k in range(len(v) - 1):                    # was in the top 30 % (ADC noise on the ramp near mid
        if v[k] > arm:                             # level must not look like a reset)
            armed = True
        if armed and v[k] > mid >= v[k + 1]:
            t.append(k + (v[k] - mid) / (v[k] - v[k + 1]))
            armed = False
    t = np.array(t)
    if len(t) < 2:
        return None, len(t), np.ptp(v)
    per = np.polyfit(np.arange(len(t)), t, 1)[0] * us * 1e-6
    n = np.arange(len(v)) * us * 1e-6
    w = 2 * np.pi / per
    A = np.column_stack([np.sin(w * n), np.cos(w * n), np.ones_like(n), n])
    c = np.linalg.lstsq(A, v, rcond=None)[0]
    return per, len(t), np.pi * np.hypot(c[0], c[1])


def test_dco():
    notes = [36, 43, 48, 55, 60, 67, 72, 79, 84, 91, 96]
    setup = ["trim 104", "wave 1", "cv res 0", "cv cut 4095", "cv vca 4095"]
    rows = []
    for n in notes:
        f = 440.0 * 2 ** ((n - 69) / 12)
        us = int(max(5, np.ceil(12.0 / f / 2048 * 1e6)))       # >= 12 periods in 2048 samples
        txt = console(setup + [f"dco {n}", "cap 2048 %d" % us], wait=20)
        caps = captures(txt, raw=True)
        if not caps:
            print(n, "no capture\n", txt[-400:]); continue
        us_, c = caps[0]
        save_raw(f"dco_{n}", us_, c)
        v = c * VDD / FS / LB
        per, ne, app = saw_period(v, us_)
        fm = 1 / per if per else float("nan")
        cents = 1200 * np.log2(fm / f) if per else float("nan")
        rows.append((n, f, fm, cents, app, ne, us_))
        print(f"MIDI {n:3d}  f {f:8.2f} Hz  measured {fm:8.2f} Hz  {cents:+6.2f} cent  saw {app*1000:6.0f} mVpp  "
              f"({ne} edges, {us_} us)")
    if rows:
        a = np.array([r[4] for r in rows])
        print(f"saw amplitude at VCAOUT: mean {a.mean()*1000:.0f} mVpp, {100*(a.min()/a.mean()-1):+.1f} / "
              f"{100*(a.max()/a.mean()-1):+.1f} %")
        os.makedirs(os.path.join(ROOT, "docs", "results"), exist_ok=True)
        with open(os.path.join(ROOT, "docs", "results", f"hw_{BOARD}_dco.csv"), "w", newline="\n") as fh:
            fh.write("midi,f_nominal_hz,f_measured_hz,cents,saw_vpp_vcaout,edges,sample_us\n")
            for r in rows:
                fh.write(",".join(f"{x:.6g}" if isinstance(x, float) else str(x) for x in r) + "\n")


def cut_table():
    """cut_code[] from the generated firmware tables: CV_CUT code for cutoff 16 Hz * 2^(i/16)."""
    src = open(os.path.join(ROOT, "firmware", "touchsynth", "tables.h"), encoding="utf-8").read()
    body = re.search(r"cut_code\[\d+\] = \{[^\n]*\n(.*?)\};", src, re.S).group(1)
    return [int(x) for x in re.findall(r"\d+", body)]


def cut_code_for(f):
    t = cut_table()
    return t[min(len(t) - 1, max(0, round(16 * np.log2(f / 16.0))))]


def tone(v, us):
    """AC rms and frequency (mean-removed zero crossings, linear interpolation) of a roughly sinusoidal signal."""
    x = v - v.mean()
    rms = np.sqrt(np.mean(x ** 2))
    h = 0.5 * rms                                  # hysteresis: a slow sine crossing zero at a high sample rate
    t, armed = [], False                           # must not count ADC noise as extra crossings
    for k in range(len(x) - 1):
        if x[k] < -h:
            armed = True
        if armed and x[k] < 0 <= x[k + 1]:
            t.append(k + (-x[k]) / (x[k + 1] - x[k]))
            armed = False
    if len(t) < 3:
        return rms, float("nan")
    return rms, 1e6 / (np.polyfit(np.arange(len(t)), t, 1)[0] * us)


def write_csv(name, header, rows):
    with open(os.path.join(ROOT, "docs", "results", f"hw_{BOARD}_{name}.csv"), "w", newline="\n") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(f"{x:.6g}" if isinstance(x, float) else str(x) for x in r) + "\n")


def test_vcf():
    """T6: self-oscillation threshold (CV_RES ramp, DCO silent, cutoff 1 kHz). T7: self-oscillation frequency vs
    CV_CUT above the threshold (expo tracking)."""
    quiet = ["trim 104", "wave 0", "cv amp 0", "cv vca 4095"]
    c1k = cut_code_for(1000)
    res_codes = list(range(2000, 3401, 100))
    cmds = quiet + [f"cv cut {c1k}"]
    for rc in res_codes:
        cmds += [f"cv res {rc}", "cap 1 100000", "cap 1024 20"]          # 'cap 1 100000': ~0.1 s settling pause
    caps = captures(console(cmds, wait=10), raw=True)[1::2]
    rows = []
    print(f"T6: cutoff code {c1k} (1 kHz)")
    for rc, (us, c) in zip(res_codes, caps):
        save_raw(f"vcf_res_{rc}", us, c)
        rms, f = tone(c * VDD / FS / LB, us)
        rows.append((rc, rc / 4095 * 5.0, rms, f))
        print(f"  CV_RES code {rc:4d} ({rc/4095*5:.2f} V): {rms*1000:7.1f} mV rms at VCAOUT, f {f:7.1f} Hz")
    write_csv("vcf_res", ["cv_res_code", "cv_res_v", "vcaout_rms_v", "f_hz"], rows)
    osc = [r for r in rows if r[2] > 0.05]
    thr = osc[0][1] if osc else float("nan")
    print(f"T6: self-oscillation from CV_RES {thr:.2f} V (sim 3.1 V, limit 2.7...3.5 V)")

    res_on = (osc[0][0] + 200) if osc else 3300
    cuts = [cut_code_for(f) for f in (100, 200, 400, 800, 1600, 3200, 6400)]
    cmds = quiet + [f"cv res {res_on}"]
    for cc in cuts:
        cmds += [f"cv cut {cc}", "cap 1 100000", "cap 2048 10"]
    caps = captures(console(cmds, wait=20), raw=True)[1::2]
    rows = []
    for cc, (us, c) in zip(cuts, caps):
        save_raw(f"vcf_cut_{cc}", us, c)
        rms, f = tone(c * VDD / FS / LB, us)
        rows.append((cc, cc / 4095 * 5.0, rms, f))
        print(f"  CV_CUT code {cc:4d} ({cc/4095*5:.3f} V): f {f:8.1f} Hz, {rms*1000:6.1f} mV rms")
    write_csv("vcf_track", ["cv_cut_code", "cv_cut_v", "vcaout_rms_v", "f_hz"], rows)
    ok = [(r[1], np.log2(r[3])) for r in rows if np.isfinite(r[3]) and r[2] > 0.02]
    if len(ok) >= 3:
        k = np.polyfit([a for a, _ in ok], [b for _, b in ok], 1)[0]
        print(f"T7: tracking {k:.3f} oct/V (sim 2.05, limit 2.05 +- 0.2)")


def fundamental(v, us, f):
    """Amplitude (peak) of the component at frequency f by least squares (with DC and slope terms)."""
    n = np.arange(len(v)) * us * 1e-6
    w = 2 * np.pi * f
    A = np.column_stack([np.sin(w * n), np.cos(w * n), np.ones_like(n), n])
    c = np.linalg.lstsq(A, v, rcond=None)[0]
    return np.hypot(c[0], c[1])


def sim_rows(name):
    lines = open(os.path.join(ROOT, "docs", "results", name + ".csv"), encoding="utf-8").read().split("\n")
    return [[float(x) for x in l.split(",")] for l in lines[1:] if l.strip()]


def test_vca():
    """T9: VCA gain law: 1046.5 Hz saw (C6), filter open, CV_VCA swept; fundamental at VCAOUT relative to full,
    against S4 (nominal curve)."""
    f0 = 440 * 2 ** ((84 - 69) / 12)
    sim = sim_rows("s4_vca_gain")
    cvs = [r[0] for r in sim]
    cmds = ["trim 104", "wave 1", "cv res 0", "cv cut 4095", "dco 84"]
    for cv in cvs:
        cmds += [f"cv vca {round(cv / 5 * 4095)}", "wait 50", "cap 2048 10"]
    caps = captures(console(cmds, wait=20), raw=True)
    amp = []
    for cv, (us, c) in zip(cvs, caps):
        save_raw(f"vca_{round(cv / 5 * 4095)}", us, c)
        amp.append(fundamental(c * VDD / FS / LB, us, f0))
    full = amp[-1]
    rows = []
    for cv, a, s in zip(cvs, amp, sim):
        db = 20 * np.log10(a / full) if a > 0 else -200
        rows.append((cv, a, db, s[1] - sim[-1][1]))
        print(f"  CV_VCA {cv:4.2f} V: fundamental {a*1000:8.3f} mV pk  {db:+7.1f} dB re full  (sim {s[1]-sim[-1][1]:+7.1f})")
    write_csv("vca_gain", ["cv_vca_v", "fund_pk_v", "gain_re_full_db", "sim_re_full_db"], rows)
    dev = [r[2] - r[3] for r in rows if r[0] >= 1.0]
    print(f"T9: deviation from S4 for CV >= 1 V: {min(dev):+.1f} ... {max(dev):+.1f} dB; "
          f"saw fundamental at full gain {full*1000:.0f} mV pk")


def test_settle():
    """T11: CV_VCA step 0 -> full with a 1046.5 Hz saw; envelope of the fundamental, 10-90 % rise and 1 % settling."""
    f0 = 440 * 2 ** ((84 - 69) / 12)
    cmds = ["trim 104", "wave 1", "cv res 0", "cv cut 4095", "dco 84", "cv vca 0", "wait 200",
            "capcv 3 4095 2048 5"]
    us, c = captures(console(cmds, wait=20), raw=True)[0]
    save_raw("vca_step", us, c)
    v = c * VDD / FS / LB
    per = int(round(1e6 / f0 / us))                         # sliding one-period fundamental magnitude
    t = np.arange(len(v)) * us * 1e-3
    env = np.array([fundamental(v[k:k + per], us, f0) if k + per <= len(v) else np.nan for k in range(len(v))])
    final = np.nanmean(env[-3 * per:-per])
    tt = t + per * us * 1e-3 / 2
    t10 = tt[np.nanargmax(env > 0.1 * final)]
    t90 = tt[np.nanargmax(env > 0.9 * final)]
    outside = np.where(np.abs(env - final) > 0.01 * final)[0]
    outside = outside[outside < len(env) - per]
    t1 = tt[outside[-1]] if len(outside) else 0
    print(f"T11: VCA step: 10-90 % {t90 - t10:.2f} ms, within 1 % after {t1:.2f} ms (sim 1.3 ms, limit 2.5 ms)")
    write_csv("vca_step_env", ["t_ms", "fund_pk_v"], [(a, b) for a, b in zip(tt, env) if np.isfinite(b)])


def test_hum():
    """T12: hum and noise at VCAOUT: VCA open, DCO silent, filter open; 2048 x 100 us (205 ms)."""
    cmds = ["trim 104", "wave 0", "cv amp 0", "cv res 0", "cv cut 4095", "cv vca 4095", "wait 200", "cap 2048 100"]
    us, c = captures(console(cmds, wait=20), raw=True)[0]
    save_raw("hum", us, c)
    v = c * VDD / FS / LB
    x = (v - v.mean()) * np.hanning(len(v))
    spec = np.abs(np.fft.rfft(x)) * 2 / np.sum(np.hanning(len(v)))
    f = np.fft.rfftfreq(len(v), us * 1e-6)
    ref = 1.33 / 2                                           # 1.33 Vpp nominal output (S7 reference)
    def peak(fc):
        k = np.argmin(np.abs(f - fc)); return spec[max(0, k - 2):k + 3].max()
    h50, h100 = peak(50), peak(100)
    rms = np.std(v)
    print(f"T12: 50 Hz {20*np.log10(h50/ref):.0f} dB, 100 Hz {20*np.log10(h100/ref):.0f} dB re 1.33 Vpp; "
          f"total noise {rms*1e3:.2f} mV rms ({20*np.log10(rms*np.sqrt(2)/ref):.0f} dB) up to 5 kHz "
          f"(ADC LSB = {VDD/FS/LB*1e3:.2f} mV at VCAOUT)")
    write_csv("hum_spectrum", ["f_hz", "amp_pk_v"], list(zip(f, spec)))


def test_lpf():
    """T8: low-pass: 110 Hz saw (A2), CV_CUT at the 1 kHz code, no resonance. Harmonic amplitudes relative to an
    ideal saw (1/n), fitted with a 4-pole response |H| = 1 / (1 + (f/fp)^2)^2 to get the pole frequency fp, which
    must agree with the self-oscillation frequency at the same code (T7)."""
    f0 = 440 * 2 ** ((45 - 69) / 12)
    c1k = cut_code_for(1000)
    out = []
    for cut in (4095, c1k):                                  # reference (open filter) and 1 kHz
        cmds = ["trim 104", "wave 1", "cv res 0", f"cv cut {cut}", "cv vca 4095", "dco 45", "wait 100",
                "cap 2048 20"]
        us, c = captures(console(cmds, wait=20), raw=True)[0]
        save_raw(f"lpf_{cut}", us, c)
        v = c * VDD / FS / LB
        out.append([fundamental(v, us, k * f0) for k in range(1, 21)])
    ref, filt = np.array(out[0]), np.array(out[1])
    h = filt / ref                                           # filter response at the harmonics (open = reference)
    k = np.arange(1, 21)
    fs = k * f0
    cand = np.linspace(500, 5000, 4501)
    err = [np.sum((20 * np.log10(h[:12]) - 20 * np.log10(h[0]) + 40 * np.log10(1 + (fs[:12] / fp) ** 2)
                   - 40 * np.log10(1 + (f0 / fp) ** 2)) ** 2) for fp in cand]
    fp = cand[int(np.argmin(err))]
    for i in range(12):
        model = 1 / (1 + (fs[i] / fp) ** 2) ** 2 / (1 / (1 + (f0 / fp) ** 2) ** 2)
        print(f"  harmonic {k[i]:2d} ({fs[i]:6.0f} Hz): {20*np.log10(h[i]/h[0]):+7.1f} dB re fundamental  "
              f"(4-pole fit {20*np.log10(model):+7.1f})")
    print(f"T8: 4-pole fit pole frequency {fp:.0f} Hz (self-oscillation at this code ~2.0 kHz, T6); harmonic 10: "
          f"{20*np.log10(h[9]/h[0]):+.1f} dB")
    write_csv("lpf_harmonics", ["harmonic", "f_hz", "open_pk_v", "filtered_pk_v", "response_db"],
              [(int(k[i]), fs[i], ref[i], filt[i], 20 * np.log10(h[i])) for i in range(20)])


if __name__ == "__main__":
    {"dco": test_dco, "vcf": test_vcf, "vca": test_vca, "settle": test_settle, "hum": test_hum,
     "lpf": test_lpf}[sys.argv[1]]()
