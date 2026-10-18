"""S9d - DCO against DAC on board 1: the same patches with the saw from the analog DCO or from one DAC oscillator
(187.5 kHz carrier, 7 bit, second-order error feedback), recorded from the line out (scope.py record, raw 8 bit):

  cmp_scale_dco / _dac   single saw, filter open, C2 ... C7, 1.5 s per note (tunes.COMPARE)
  acid_dco / _dac        the acid demo tune (resonant filter, slides, accents)
  ode_dco / _dac         the 'lead' patch (saw + sub, glide, vibrato); DAC: saw + square one octave down

  python s9_hwcmp.py <dir with the .u8 takes>

Per scale note: level, and the inharmonic content (energy away from the harmonics: aliasing, noise, spurs) re the
total, 20 Hz - 20 kHz; f0 is fitted per note (board clock). Output: docs/results/hw_board1_dco_vs_dac.csv,
docs/audio/s9_osc/cmp_<take>.mp3, docs/figures/s9_hwcmp.(pdf|png).
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s9_osc as S                                        # noqa: E402
import s9_hw as H                                         # noqa: E402
from s9_osc import B, ps                                  # noqa: E402

FS = B.FS_OUT
NOTES = (36, 48, 60, 72, 84, 96)
TAKES = ("cmp_scale_dco", "cmp_scale_dac", "acid_dco", "acid_dac", "ode_dco", "ode_dac")


def trim(y, thr=0.03):
    """From 0.2 s before the first sound to 0.5 s after the last."""
    e = H.envelope(y)
    act = np.nonzero(e > thr * e.max())[0]
    return y[max(0, act[0] - int(0.2 * FS)):act[-1] + int(0.5 * FS)]


def f0_fit(x, f_nom):
    """Fundamental near f_nom (board clock within +-2 %): maximise the summed magnitude of the DFT evaluated at
    the harmonics below 20 kHz (up to 40), coarse then fine, so the high harmonics fall on their bins."""
    from scipy.signal.windows import blackmanharris
    xw = x * blackmanharris(len(x))
    t = np.arange(len(x)) / FS

    def score(c):
        h = c * np.arange(1, 41)
        h = h[h < 20e3]
        return np.abs(np.exp(-2j * np.pi * np.outer(h, t)) @ xw).sum()

    c0 = f_nom
    for span, n in ((0.02, 81), (0.0006, 31), (0.00003, 31)):
        cs = np.linspace(c0 * (1 - span), c0 * (1 + span), n)
        c0 = cs[int(np.argmax([score(c) for c in cs]))]
    return c0


def scale_notes(y):
    """Steady windows of the six notes: onsets from the envelope, then 0.25 ... 1.05 s after each."""
    e = H.envelope(y)
    on = np.nonzero((e[1:] > 0.5 * e.max()) & (e[:-1] <= 0.5 * e.max()))[0]
    keep = [on[0]]
    for k in on[1:]:
        if k - keep[-1] > 1.4 * FS:                 # notes are 1.8 s apart
            keep.append(k)
    return [(k + int(0.25 * FS), k + int(1.05 * FS)) for k in keep[:len(NOTES)]]


def main(d):
    import matplotlib.pyplot as plt
    from scipy.signal import spectrogram
    ys, floor = {}, {}
    for t in TAKES:
        y = H.load_take(os.path.join(d, t + ".u8"))
        floor[t] = np.std(y[-int(2.0 * FS):])          # VCA closed after the tune (DAC mode: DAC still running)
        ys[t] = trim(y)
        S.write_audio("cmp_" + t, ys[t])
    rows = []
    for m, (a, b), (c, e) in zip(NOTES, scale_notes(ys["cmp_scale_dco"]), scale_notes(ys["cmp_scale_dac"])):
        row = [m]
        for x in (ys["cmp_scale_dco"][a:b], ys["cmp_scale_dac"][c:e]):
            f0 = f0_fit(x, float(B.mtof(m)) / 1.008)
            row += [round(f0, 2), round(np.std(x) * 1e3, 1), round(S.inharmonic_db(x, f0), 1)]
        rows.append(row)
    ps.save_csv("hw_board1_dco_vs_dac", ["midi", "dco_f0_hz", "dco_rms_mv", "dco_inharm_db",
                                         "dac_f0_hz", "dac_rms_mv", "dac_inharm_db"], rows)
    print(f"{'note':>4s} {'DCO f0':>9s} {'rms mV':>7s} {'inharm':>7s}   {'DAC f0':>9s} {'rms mV':>7s} {'inharm':>7s}")
    for r in rows:
        print(f"{r[0]:4d} {r[1]:9.2f} {r[2]:7.1f} {r[3]:7.1f}   {r[4]:9.2f} {r[5]:7.1f} {r[6]:7.1f}")
    for t in TAKES:
        print(f"{t}: {len(ys[t]) / FS:.1f} s, rms {np.std(ys[t]) * 1e3:.1f} mV, "
              f"floor after the tune {floor[t] * 1e3:.2f} mV")

    f, axes = ps.fig(2, 2, aspect=0.55)
    for ax, t, lab in zip(axes[0], TAKES[:2], ("DCO", "DAC")):
        fq, tt, P = spectrogram(ys[t], FS, nperseg=4096, noverlap=3072)
        ax.pcolormesh(tt, fq / 1000, 10 * np.log10(P + 1e-14), shading="auto", cmap="magma", vmin=-140, vmax=-50,
                      rasterized=True)
        ax.set(title=f"{lab}: saw C2 ... C7, filter open", xlabel="$t$ [s]", ylim=(0, 20))
        ax.grid(False)
    axes[0, 0].set_ylabel("$f$ [kHz]")
    ax = axes[1, 0]
    x = np.arange(len(rows))
    ax.bar(x - 0.2, [r[3] for r in rows], 0.4, label="DCO", color=ps.C[0])
    ax.bar(x + 0.2, [r[6] for r in rows], 0.4, label="DAC", color=ps.C[1])
    ax.set(xticks=x, xticklabels=["C2", "C3", "C4", "C5", "C6", "C7"], ylabel="inharmonic [dB]",
           title="aliasing + noise + spurs re total")
    ax.legend()
    ax = axes[1, 1]
    ax.bar(x - 0.2, [r[2] for r in rows], 0.4, label="DCO", color=ps.C[0])
    ax.bar(x + 0.2, [r[5] for r in rows], 0.4, label="DAC", color=ps.C[1])
    ax.set(xticks=x, xticklabels=["C2", "C3", "C4", "C5", "C6", "C7"], ylabel="rms [mV]", title="line-out level")
    ax.legend()
    ps.label_panels(axes)
    f.tight_layout()
    ps.save(f, "s9_hwcmp")
    plt.close(f)


if __name__ == "__main__":
    main(sys.argv[1])
