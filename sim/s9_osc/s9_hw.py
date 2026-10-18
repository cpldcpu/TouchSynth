"""S9c - the three-oscillator voice on board 1 against the model: scope takes of the DSP test tunes (tunes.TESTS)
from the line out, decimated with a proper low-pass (raw 8-bit scope samples, as tools/mix_parts.py), aligned to
the model render of the same tune and written side by side.

  python s9_hw.py <dir with moog_bass.u8, moog_lead.u8, moog_open.u8 (+ .txt)>

Output: docs/audio/s9_osc/hw_<take>.mp3 and model_<take>.mp3 (same level scale, 2 V = 0 dBFS),
docs/figures/s9_hw.(pdf|png): spectrograms board vs model.
"""
import os, sys
import numpy as np
from fractions import Fraction
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s9_osc as S                                        # noqa: E402
from s9_osc import B, ps                                  # noqa: E402
import tunes as TU                                        # noqa: E402

TAKES = {"moog_bass": "moog_bass_test", "moog_lead": "moog_lead_test", "moog_open": "moog_open_test"}


def load_take(path):
    rate, yinc, yorg, yref = map(float, open(path + ".txt").read().split()[:4])
    v = (np.fromfile(path, np.uint8).astype(np.float64) - yorg - yref) * yinc
    fr = Fraction(B.FS_OUT / rate).limit_denominator(1000)
    y = resample_poly(v, fr.numerator, fr.denominator, window=("kaiser", 10.0))
    return y - np.median(y)


def envelope(y, n=480):
    return np.sqrt(np.convolve(y ** 2, np.ones(n) / n, mode="same"))


def align(y, m):
    """Shift the take so its envelope lines up with the model's (cross-correlation, 10 ms resolution)."""
    d = 480
    ey, em = envelope(y)[::d], envelope(m)[::d]
    c = np.correlate(ey - ey.mean(), em - em.mean(), mode="full")
    lag = (int(np.argmax(c)) - (len(em) - 1)) * d
    y = y[lag:] if lag >= 0 else np.concatenate([np.zeros(-lag), y])
    return np.pad(y, (0, max(0, len(m) - len(y))))[:len(m)]


def main(d):
    import matplotlib.pyplot as plt
    from scipy.signal import spectrogram
    f, axes = ps.fig(2, len(TAKES), aspect=0.42, sharey=True)
    for row, (take, tune) in enumerate(TAKES.items()):
        t = TU.TESTS[tune]
        notes, t_end = TU.to_notes(t)
        m = B.render(notes, TU.PRESETS[t["preset"]], t_end)[0]
        y = align(load_take(os.path.join(d, take + ".u8")), m)
        q = envelope(m) < 1e-3 * np.abs(m).max()                 # VCA closed in the model: the take's floor
        print(f"{take}: peak board {np.abs(y).max():.3f} V, model {np.abs(m).max():.3f} V; "
              f"rms board {np.std(y) * 1e3:.0f} mV, model {np.std(m) * 1e3:.0f} mV; "
              f"floor in rests {np.std(y[q]) * 1e3 if q.any() else float('nan'):.2f} mV")
        S.write_audio("hw_" + take, y)
        S.write_audio("model_" + take, m)
        for col, (lab, x) in enumerate((("board 1", y), ("model", m))):
            ax = axes[row, col]
            fq, tt, P = spectrogram(x, B.FS_OUT, nperseg=2048, noverlap=1536)
            ax.pcolormesh(tt, fq / 1000, 10 * np.log10(P + 1e-14), shading="auto", cmap="magma", vmin=-130,
                          vmax=-40, rasterized=True)
            ax.set_title(f"{take}, {lab}", fontsize=8)
            ax.set_ylim(0, 20)
            ax.grid(False)
            if col == 0:
                ax.set_ylabel("$f$ [kHz]")
            if row == len(TAKES) - 1:
                ax.set_xlabel("$t$ [s]")
    f.tight_layout()
    ps.save(f, "s9_hw")
    plt.close(f)


if __name__ == "__main__":
    main(sys.argv[1])
