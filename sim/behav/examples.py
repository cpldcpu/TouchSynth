"""Render audio examples of every TouchSynth feature with the behavioural model.

Output: docs/audio/features/<id>.wav (48 kHz / 16 bit) and .mp3, a spectrogram PNG per example in
docs/figures/audio/, and manifest.json with titles and explanations. All examples share one level scale
(2 V line out = 0 dBFS) so loudness is comparable between them.
"""
import os, sys, json, subprocess, wave
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import behav as B
from behav import ADSR
import tunes as TU
import plotstyle as ps

AUD = os.path.join(B.ROOT, "docs", "audio", "features")
FIG = os.path.join(B.ROOT, "docs", "figures", "audio")
FULL_SCALE = 2.0


def held(m, t0=0.05, dur=2.6):
    return [(t0, dur, m)]


def seq(ms, step, gate=0.8, t0=0.05):
    return [(t0 + i * step, step * gate, m) for i, m in enumerate(ms) if m]


def ramp(t, t0, t1, a, b, log=False):
    x = np.clip((t - t0) / (t1 - t0), 0, 1)
    return a * (b / a) ** x if log else a + (b - a) * x


OPEN = dict(cutoff=16000.0, res=0.0, env_amt=0.0, aenv=ADSR(0.005, 0.2, 1.0, 0.15))

EXAMPLES = [
    # ---- oscillator section
    dict(id="01_saw", group="Oscillator", title="Sawtooth (DCO)",
         what="The analog integrator saw, reset by the timer. Filter fully open. Pitch comes from a 48 MHz "
              "timer, so it is exactly in tune; the firmware scales the charging current with frequency to "
              "keep the amplitude constant.",
         patch=dict(OPEN), notes=seq([36, 48, 60, 72], 0.7, 0.9), t_end=3.0),
    dict(id="02_pulse", group="Oscillator", title="Square / pulse wave",
         what="TIM2 CH2 output (0/5 V) mixed into the filter. 50 % duty = square: hollow, odd harmonics only.",
         patch=dict(OPEN, saw=0.0, pulse=1, pw=0.5), notes=seq([36, 48, 60, 72], 0.7, 0.9), t_end=3.0),
    dict(id="03_pw_sweep", group="Oscillator", title="Pulse-width sweep",
         what="The firmware moves the pulse width from 50 % to 5 % and back: the tone gets thinner and nasal.",
         patch=dict(OPEN, saw=0.0, pulse=1), notes=held(45, dur=3.2), t_end=3.5,
         auto=lambda t, q: dict(pw=0.5 - 0.45 * np.sin(np.pi * np.clip((t - 0.1) / 3.0, 0, 1)))),
    dict(id="04_pwm_lfo", group="Oscillator", title="PWM by LFO",
         what="A slow triangle LFO modulates the pulse width: the classic moving, chorus-like string/pad sound.",
         patch=dict(OPEN, saw=0.0, pulse=1, pw=0.5, lfo_pw=0.4, lfo_rate=0.9, cutoff=4000.0),
         notes=seq([45, 52, 57], 1.1, 0.95), t_end=3.6),
    dict(id="05_sub", group="Oscillator", title="Sub oscillator",
         what="Saw alone, then the sub oscillator (square one octave lower, toggled in the timer interrupt) "
              "is switched on at 1.5 s: much more weight in the bass.",
         patch=dict(OPEN, cutoff=3000.0), notes=held(48, dur=2.9), t_end=3.2,
         auto=lambda t, q: dict(sub=1 if t > 1.5 else 0)),
    dict(id="06_noise", group="Oscillator", title="Noise through a resonant sweep",
         what="16-bit LFSR noise (0/5 V from a GPIO) with the filter swept slowly at high resonance: wind.",
         patch=dict(saw=0.0, noise=1, res=0.8, aenv=ADSR(0.3, 0.5, 1.0, 0.4)), notes=held(60, dur=3.6),
         t_end=4.0, auto=lambda t, q: dict(cutoff=float(200 * 2 ** (5 * np.sin(np.pi * np.clip(t / 3.8, 0, 1)))))),
    dict(id="07_mix_drive", group="Oscillator", title="All waveforms mixed: ladder drive",
         what="Saw, pulse and sub together push the transistor ladder into soft saturation (the input pair's "
              "tanh). Compare with the clean saw in example 1.",
         patch=dict(saw=1.0, pulse=1, sub=1, pw=0.35, cutoff=2500.0, res=0.3), notes=seq([33, 40, 45], 1.0, 0.9),
         t_end=3.3),
    # ---- filter
    dict(id="08_cutoff", group="Filter", title="Cutoff sweep (24 dB/oct)",
         what="Saw at 65 Hz, cutoff swept from 40 Hz to 16 kHz and back, no resonance.",
         patch=dict(cutoff=40.0), notes=held(36, dur=3.8), t_end=4.1,
         auto=lambda t, q: dict(cutoff=float(40 * 400 ** np.sin(np.pi * np.clip((t - 0.05) / 3.8, 0, 1))))),
    dict(id="09_resonance", group="Filter", title="Resonance up to self-oscillation",
         what="Fixed cutoff (600 Hz); resonance raised from 0 to just past the self-oscillation threshold. The "
              "peak grows, the bass thins out (classic ladder 'bass loss'), then a sine starts to sing.",
         patch=dict(cutoff=600.0), notes=held(36, dur=3.8), t_end=4.1,
         auto=lambda t, q: dict(res=float(ramp(t, 0.2, 3.6, 0.0, 1.06)))),
    dict(id="10_res_sweep", group="Filter", title="Resonant sweep",
         what="High resonance (0.9) and a cutoff sweep: the squelchy, vocal classic.",
         patch=dict(res=0.9), notes=held(36, dur=3.8), t_end=4.1,
         auto=lambda t, q: dict(cutoff=float(80 * 60 ** np.sin(np.pi * np.clip((t - 0.05) / 3.8, 0, 1))))),
    dict(id="11_self_osc", group="Filter", title="Self-oscillating filter as a sine oscillator",
         what="DCO silent, resonance above threshold: the filter itself is the oscillator. The firmware sets "
              "the cutoff per key; the pitch follows the expo converter (not temperature-compensated, so "
              "tuning is only approximate on real hardware).",
         patch=dict(saw=0.0, res=1.12, aenv=ADSR(0.005, 0.3, 1.0, 0.1)),
         notes=seq([60, 64, 67, 72, 67, 64, 60], 0.4, 0.95), t_end=3.2),
    dict(id="12_filter_env", group="Filter", title="Filter envelope amount",
         what="The same pluck with filter-envelope depth 0, 2, 4 and 6 octaves: from dull to 'wow'.",
         patch=dict(cutoff=150.0, res=0.45, fenv=ADSR(0.002, 0.18, 0.0, 0.1), aenv=ADSR(0.002, 0.35, 0.3, 0.1)),
         notes=[(0.05 + i * 0.8, 0.5, 45, dict(env_amt=a)) for i, a in enumerate((0.0, 2.0, 4.0, 6.0))],
         t_end=3.3),
    dict(id="13_keytrack", group="Filter", title="Keyboard tracking off / on",
         what="An upward scale with a fixed cutoff (high notes get dull), then with 100 % key tracking "
              "(the cutoff follows the note, constant brightness).",
         patch=dict(cutoff=500.0, res=0.3),
         notes=[(0.05 + i * 0.25, 0.2, m, dict(keytrack=0.0 if i < 8 else 1.0))
                for i, m in enumerate([36, 40, 43, 48, 52, 55, 60, 64] * 2)], t_end=4.2),
    # ---- envelopes / VCA
    dict(id="14_amp_env", group="Envelopes & VCA", title="Amplitude envelope shapes",
         what="Pluck (fast decay), organ (gate), pad (slow attack and release): only the VCA envelope "
              "changes, generated in firmware and sent as CV_VCA.",
         patch=dict(cutoff=2500.0, res=0.2),
         notes=[(0.05, 0.25, 57, dict(aenv=ADSR(0.002, 0.25, 0.0, 0.1))),
                (1.0, 0.8, 57, dict(aenv=ADSR(0.004, 0.1, 1.0, 0.03))),
                (2.1, 1.3, 57, dict(aenv=ADSR(0.6, 0.5, 0.8, 0.9)))], t_end=4.5),
    dict(id="15_vca_trim", group="Envelopes & VCA", title="VCA thump: untrimmed vs calibrated trim",
         what="Short bass notes. First half: VCA offset untrimmed (≈150 mV CV feedthrough, heard as a thump "
              "on every note). Second half: after the firmware trim calibration (< 1 mV).",
         patch=dict(cutoff=400.0, env_amt=2.0, aenv=ADSR(0.001, 0.12, 0.0, 0.05)),
         notes=seq([33, 0, 33, 0, 36, 0, 33, 0] * 2, 0.22, 0.6), t_end=3.7, split_thump=1.8),
    # ---- modulation
    dict(id="16_glide", group="Modulation", title="Glide (portamento)",
         what="Firmware pitch slew between notes (timer periods updated every millisecond).",
         patch=dict(cutoff=1500.0, sub=1, glide=0.12), notes=seq([45, 57, 52, 64, 45], 0.55, 0.98), t_end=3.1),
    dict(id="17_vibrato", group="Modulation", title="Vibrato (LFO → pitch)",
         what="Triangle LFO at 5.5 Hz, ±25 cent on the DCO timer — digital, exact and drift-free.",
         patch=dict(cutoff=2000.0, lfo_rate=5.5, lfo_pitch=25.0), notes=seq([69, 72], 1.4, 0.95), t_end=3.1),
    dict(id="18_wah", group="Modulation", title="LFO → cutoff (wah)",
         what="LFO at 3 Hz sweeping the cutoff by ±2 octaves with resonance 0.7.",
         patch=dict(cutoff=900.0, res=0.7, lfo_rate=3.0, lfo_cut=2.0), notes=held(40, dur=3.2), t_end=3.5),
    dict(id="19_arp", group="Modulation", title="Arpeggiator",
         what="Firmware arpeggiator: hold a chord (Am7 → Fmaj7), the notes are played up/down in 16ths at 140 bpm.",
         patch=dict(cutoff=600.0, env_amt=3.0, res=0.5, keytrack=0.5, fenv=ADSR(0.001, 0.1, 0.1, 0.05),
                    aenv=ADSR(0.002, 0.15, 0.3, 0.05)),
         notes=seq(([57, 60, 64, 67, 64, 60] * 3 + [53, 57, 60, 64, 60, 57] * 3), 60 / 140 / 4, 0.7), t_end=4.1),
]


def write_wav(path, y):
    pcm = np.int16(np.clip(y / FULL_SCALE, -1, 1) * 32767)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(B.FS_OUT); w.writeframes(pcm.tobytes())


def to_mp3(wav):
    mp3 = wav[:-4] + ".mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-codec:a", "libmp3lame", "-q:a", "3", mp3],
                   check=True)
    return mp3


def spectro_png(y, path, title=None):
    import matplotlib.pyplot as plt
    from scipy.signal import spectrogram
    f, ax = plt.subplots(2, 1, figsize=(ps.FULL, 2.3), gridspec_kw=dict(height_ratios=[1, 2.2]), sharex=True)
    t = np.arange(len(y)) / B.FS_OUT
    ax[0].plot(t, y, color=ps.C[0], lw=0.3)
    ax[0].set(ylabel="[V]", ylim=(-FULL_SCALE, FULL_SCALE))
    fq, tt, S = spectrogram(y, B.FS_OUT, nperseg=4096, noverlap=3584)
    ax[1].pcolormesh(tt, np.maximum(fq, 1) / 1000, 10 * np.log10(S + 1e-14), shading="auto", cmap="magma", vmin=-120, vmax=-40,
                     rasterized=True)
    ax[1].set_yscale("log")
    ax[1].set(xlabel="$t$ [s]", ylabel="$f$ [kHz]", ylim=(0.04, 12)); ax[1].grid(False)
    ax[1].set_yticks([0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10]); ax[1].set_yticklabels(["0.05", "0.1", "0.2", "0.5", "1", "2", "5", "10"])
    f.tight_layout(h_pad=0.2)
    f.savefig(path, dpi=110)
    plt.close(f)


def render_example(ex):
    notes, patch = ex["notes"], ex["patch"]
    auto = ex.get("auto")
    if ex["id"] == "11_self_osc":
        # firmware maps key -> cutoff so the self-oscillation pitch equals the note
        def auto(t, q, notes=notes):
            cur = [n for n in notes if n[0] <= t]
            m = cur[-1][2] if cur else notes[0][2]
            return dict(cutoff=float(B.mtof(m)) * B.POLE_RATIO * 1.0)
    if "split_thump" in ex:
        ev, cv = B.firmware(notes, patch, ex["t_end"], auto)
        y1, _ = B.analog(ev, cv, thump=0.15)
        y2, _ = B.analog(ev, cv, thump=0.0007)
        k = int(ex["split_thump"] * B.FS_OUT)
        y = np.concatenate([y1[:k], y2[k:]])
    else:
        y, _ = B.render(notes, patch, ex["t_end"], auto)
    fade = int(0.01 * B.FS_OUT)
    y[:fade] *= np.linspace(0, 1, fade); y[-fade:] *= np.linspace(1, 0, fade)
    return y


def render_tune(name):
    tune = TU.TUNES[name]
    notes, t_end = TU.to_notes(tune)
    y, _ = B.render(notes, TU.PRESETS[tune["preset"]], t_end)
    fade = int(0.01 * B.FS_OUT)
    y[:fade] *= np.linspace(0, 1, fade); y[-fade:] *= np.linspace(1, 0, fade)
    return y, tune


def main():
    os.makedirs(AUD, exist_ok=True); os.makedirs(FIG, exist_ok=True)
    manifest = []
    for ex in EXAMPLES:
        y = render_example(ex)
        wav = os.path.join(AUD, ex["id"] + ".wav")
        write_wav(wav, y); to_mp3(wav)
        spectro_png(y, os.path.join(FIG, ex["id"] + ".png"))
        pk = np.max(np.abs(y))
        print(f"{ex['id']:16s} peak {pk:.2f} V  {'CLIP' if pk > FULL_SCALE else ''}")
        manifest.append(dict(id=ex["id"], group=ex["group"], title=ex["title"], what=ex["what"],
                             seconds=round(len(y) / B.FS_OUT, 2), peak_v=round(float(pk), 3)))
    for name, desc in [("acid", "Original 16-step acid bass line: high resonance, filter-envelope accents and slides."),
                       ("prelude", "J. S. Bach, Prelude in C major BWV 846, bars 1–4 (public domain), as a 16th-note "
                                   "arpeggio with saw + pulse and a slow PWM."),
                       ("ode", "L. v. Beethoven, 'Ode to Joy' (public domain) on a lead patch with sub oscillator, "
                               "glide and vibrato.")]:
        y, tune = render_tune(name)
        wav = os.path.join(AUD, f"tune_{name}.wav")
        write_wav(wav, y); to_mp3(wav)
        spectro_png(y, os.path.join(FIG, f"tune_{name}.png"))
        pk = np.max(np.abs(y))
        print(f"tune_{name:10s} peak {pk:.2f} V  {'CLIP' if pk > FULL_SCALE else ''}")
        manifest.append(dict(id=f"tune_{name}", group="Demo tunes (stored in the MCU)", title=name.capitalize(),
                             what=desc, seconds=round(len(y) / B.FS_OUT, 2), peak_v=round(float(pk), 3),
                             bpm=tune["bpm"], preset=tune["preset"], steps=len(tune["steps"]),
                             flash_bytes=3 * len(tune["steps"])))
    with open(os.path.join(AUD, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
