#!/usr/bin/env python3
"""Figure for the report's instrument section (behavioural model, sim/behav):

  docs/figures/instr_drums.pdf/.png
    (a) kick: pitch over the first 120 ms, preset v3 (sub square, no pitch envelope) vs v4 (pitch envelope)
    (b) kettle (modal timpani on the PWM DAC): partial levels in two time windows, a recorded timpani (C4
        stroke) vs the kettle preset at C4, in multiples of the principal (the note)
    (c) kettle decay on board 1 vs the model, C4 / C3 / G2 (docs/results/hw_board1_kettle.csv)

  python instrument_figures.py [reference.wav|.ogg]     reference: a recorded timpani F3-A3-C4 triad, the C4
                                                       stroke starts at 5.475 s (decoded with ffmpeg)
"""
import os, sys, subprocess, tempfile
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path[:0] = [os.path.join(ROOT, "sim", "behav"), os.path.join(ROOT, "sim", "lib")]
import plotstyle as ps                                    # noqa: E402  (sets the rcParams)
import behav as B                                         # noqa: E402
import tunes as TU                                        # noqa: E402

KICK_V3 = dict(saw=0.0, sub=1, cutoff=50.0, env_amt=3.5, res=0.3, keytrack=0.0, vol=1.0,
               fenv=("adsr", 0.001, 0.04, 0.0, 0.04), aenv=("adsr", 0.001, 0.25, 0.0, 0.08))
MULT = (0.375, 0.5, 0.75, 1.0, 1.23, 1.46, 1.62, 1.91)
WIN = ((0.03, 0.2), (0.2, 0.6))


def pitch_track(y, fs, t_max=0.12):
    """Instantaneous frequency from the spacing of rising zero crossings (one value per period)."""
    y = y[: int(t_max * fs)]
    z = np.where((y[:-1] < 0) & (y[1:] >= 0))[0]
    zc = z + (-y[z] / (y[z + 1] - y[z]))                  # sub-sample crossing
    return (zc[1:] + zc[:-1]) / 2 / fs, fs / np.diff(zc)


def partials(y, fs, f, t0, t1):
    a, b = int(t0 * fs), min(int(t1 * fs), len(y))
    X = np.abs(np.fft.rfft(y[a:b] * np.hanning(b - a), 1 << 18))
    fr = np.fft.rfftfreq(1 << 18, 1 / fs)
    lv = np.array([X[(fr > m * f * 0.975) & (fr < m * f * 1.025)].max() for m in MULT])
    return 20 * np.log10(lv / lv.max())


def hit(patch, note, dur, span):
    y, _ = B.render([(0.05, dur, note, {})], patch, 0.05 + span)
    return y[int(0.05 * B.FS_OUT):]


def main(ref_path):
    fs = B.FS_OUT
    import matplotlib.pyplot as plt
    f = plt.figure(figsize=(ps.FULL, ps.FULL * 0.62))
    gs = f.add_gridspec(2, 2, height_ratios=[1, 0.85], hspace=0.62, wspace=0.3)
    ax = [f.add_subplot(gs[0, 0]), f.add_subplot(gs[0, 1]), f.add_subplot(gs[1, :])]
    for p, lab, c in ((KICK_V3, "v3: sub square, E2 (41 Hz)", ps.C[1]), (TU.PRESETS["kick"], "v4: pitch envelope, A2", ps.C[0])):
        note = 40 if p is KICK_V3 else 45
        t, fq = pitch_track(hit(p, note, 0.1, 0.15), fs)
        ax[0].plot(t * 1e3, fq, "o-", ms=2.5, color=c, label=lab)
    ax[0].set_xlabel("time after the attack [ms]")
    ax[0].set_ylabel("frequency [Hz]")
    ax[0].set_ylim(0, 260)
    ax[0].legend(loc="upper right", fontsize=6.5)

    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "ref.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ref_path, "-ac", "1", "-ar", str(fs), wav],
                       check=True)
        import wave
        with wave.open(wav) as w:
            r = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768
    r = r[int(5.475 * fs):int(7.0 * fs)]                    # C4 stroke, let ring
    s = hit(TU.PRESETS["kettle"], 60, 1.6, 1.6)
    x = np.arange(len(MULT))
    wbar = 0.2
    for k, (t0, t1) in enumerate(WIN):
        ax[1].bar(x + (2 * k - 1.5) * wbar, partials(r, fs, 261.6, t0, t1) + 60, wbar, bottom=-60,
                  color=ps.C[1], alpha=1.0 if k == 0 else 0.5,
                  label=f"recorded {t0 * 1e3:.0f}-{t1 * 1e3:.0f} ms")
        ax[1].bar(x + (2 * k - 0.5) * wbar, partials(s, fs, 261.6, t0, t1) + 60, wbar, bottom=-60,
                  color=ps.C[0], alpha=1.0 if k == 0 else 0.5,
                  label=f"kettle {t0 * 1e3:.0f}-{t1 * 1e3:.0f} ms")
    ax[1].set_xticks(x, [f"{m:g}" for m in MULT], fontsize=6.5)
    ax[1].set_xlabel("partial / principal (C4)")
    ax[1].set_ylabel("level [dB]")
    ax[1].set_ylim(-60, 3)
    ax[1].legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=5.5, ncol=2)

    import csv
    with open(os.path.join(ROOT, "docs", "results", "hw_board1_kettle.csv")) as fh:
        rows = list(csv.DictReader(fh))
    t = np.array([float(r_["t_s"]) for r_ in rows])
    for nm, lab, c in (("c4", "C4", ps.C[0]), ("c3", "C3", ps.C[1]), ("g2", "G2", ps.C[2])):
        ax[2].plot(t, [float(r_[f"board_{nm}_db"]) for r_ in rows], color=c, label=f"{lab} board 1")
        ax[2].plot(t, [float(r_[f"model_{nm}_db"]) for r_ in rows], color=c, ls="--", lw=0.8)
    ax[2].plot([], [], color=ps.C[6], ls="--", lw=0.8, label="model")
    ax[2].set_xlabel("time after the stroke [s]")
    ax[2].set_ylabel("level [dB]")
    ax[2].set_ylim(-50, 3)
    ax[2].legend(loc="upper right", fontsize=6)
    ps.label_panels(ax)
    ps.save(f, "instr_drums")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "temp", "Timpani_F_major_triad.ogg"))
