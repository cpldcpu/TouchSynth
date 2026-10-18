#!/usr/bin/env python3
"""Figure for the report's instrument section (behavioural model, sim/behav):

  docs/figures/instr_drums.pdf/.png
    (a) kick: pitch over the first 120 ms, preset v3 (sub square, no pitch envelope) vs v4 (pitch envelope)
    (b) timpani: partial levels in two time windows, a recorded timpani (C3 stroke) vs the timpani preset

  python instrument_figures.py [reference.wav|.ogg]     reference: a recorded timpani F-A-C triad, the C3
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
MULT = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.25)
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
    f, ax = ps.fig(2, 1, aspect=0.5)
    for p, lab, c in ((KICK_V3, "v3: sub square, E2 (41 Hz)", ps.C[1]), (TU.PRESETS["kick"], "v4: pitch envelope, A2", ps.C[0])):
        note = 40 if p is KICK_V3 else 45
        t, fq = pitch_track(hit(p, note, 0.1, 0.15), fs)
        ax[0].plot(t * 1e3, fq, "o-", ms=2.5, color=c, label=lab)
    ax[0].set_xlabel("time after the attack [ms]")
    ax[0].set_ylabel("frequency [Hz]")
    ax[0].set_ylim(0, 260)
    ax[0].legend(loc="upper right")

    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "ref.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ref_path, "-ac", "1", "-ar", str(fs), wav],
                       check=True)
        import wave
        with wave.open(wav) as w:
            r = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768
    r = r[int(5.475 * fs):int(7.0 * fs)]                    # C3 stroke, let ring
    s = hit(TU.PRESETS["timpani"], 48, 1.6, 1.6)
    x = np.arange(len(MULT))
    wbar = 0.2
    for k, (t0, t1) in enumerate(WIN):
        ax[1].bar(x + (2 * k - 1.5) * wbar, partials(r, fs, 130.8, t0, t1) + 60, wbar, bottom=-60,
                  color=ps.C[1], alpha=1.0 if k == 0 else 0.5,
                  label=f"recorded {t0 * 1e3:.0f}-{t1 * 1e3:.0f} ms")
        ax[1].bar(x + (2 * k - 0.5) * wbar, partials(s, fs, 130.8, t0, t1) + 60, wbar, bottom=-60,
                  color=ps.C[0], alpha=1.0 if k == 0 else 0.5,
                  label=f"synth {t0 * 1e3:.0f}-{t1 * 1e3:.0f} ms")
    ax[1].set_xticks(x, [f"{m:g}" for m in MULT])
    ax[1].set_xlabel("partial / nominal pitch (C3)")
    ax[1].set_ylabel("level [dB]")
    ax[1].set_ylim(-60, 3)
    ax[1].legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=6, ncol=2)
    ps.label_panels(ax)
    ps.save(f, "instr_drums")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "temp", "Timpani_F_major_triad.ogg"))
