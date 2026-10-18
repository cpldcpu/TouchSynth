#!/usr/bin/env python3
"""Mix a multitrack TouchSynth piece into a stereo WAV / MP3.

  python mix_parts.py hw    <dir> [piece]   parts recorded from the line out: <dir>/<piece>_<part>.f32 (+ .txt
                                            rate), as written by 'scope.py record' while the board plays the part
  python mix_parts.py model <dir> [piece]   render every part with the behavioural model (cached .npy)

Pieces: 'demo' (TouchSynth Demo, sim/behav/tunes.py PARTS) and those in sim/behav/pieces.py (march, toccata,
aero). Default: demo.

Alignment (hw): every part starts with an empty lead-in and a sync step ('Y'), at which the firmware opens the
VCA fully for 4 ms. The first event above the noise of the lead-in is that pulse; the music starts a fixed
number of steps later. The takes run on the board's RC clock, which drifts ~0.1 % between takes recorded at
different times (tens of ms over a piece), so each take's clock is fitted from its own note onsets and the take
is resampled onto a common clock. Per track: gentle noise gate (the noise floors would otherwise add up), gain,
pan; Haas widening on pads, ping-pong delay on the lead, optional convolution reverb on the sum.
"""
import os, sys, wave, subprocess
from fractions import Fraction
import numpy as np
from scipy.signal import resample_poly, fftconvolve, lfilter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "sim", "behav"))
sys.path.insert(0, os.path.join(ROOT, "sim", "lib"))
import tunes as TU                                               # noqa: E402
import pieces as PC                                              # noqa: E402

FS = 48000
CLOCK = 1.0080                  # board 1: MCU clock 0.80 % slow (47.62 MHz HSI), measured over 232 kick hits


def piece(name):
    """Common description: step (s), lead-in steps after the sync, total music steps, parts {name: tune}, mix."""
    if name == "demo":
        parts = {k[5:]: v for k, v in TU.PARTS.items() if k.startswith("demo_")}
        return dict(step=(15000 // TU.DEMO_BPM) / 1000, lead=16, total=TU._N_BARS * 16, parts=parts,
                    mix={"kick": (0.0, 0.0), "snare": (-3.0, 0.12), "hat": (-9.0, 0.35), "bass": (-2.0, 0.0),
                         "arp": (-8.0, -0.4), "lead": (-3.0, 0.08), "pad": (-6.0, -0.15)},
                    reverb=0.0, delay="lead", haas=("pad",), ref="hat")
    pc = PC.PIECES[name]
    any_part = next(iter(pc["parts"].values()))
    return dict(step=(pc.get("step_ms") or 15000 // pc["bpm"]) / 1000, lead=any_part["lead"], total=pc["total"], parts=pc["parts"],
                mix=pc["mix"], reverb=pc.get("reverb", 0.0), delay=pc.get("delay"),
                haas=tuple(k for k in pc["parts"] if k.startswith("pad")), ref=pc.get("ref"))


def onsets_s(P, part):
    """Expected attack times (s, nominal clock) from the start of the music (sync step + lead steps)."""
    t, sync, out = 0, None, []
    for n, ln, fl in P["parts"][part]["steps"]:
        if n >= TU.CTRL:
            continue
        if "Y" in fl and sync is None:
            sync = t
        if sync is not None and n and "T" not in fl and "S" not in fl:
            out.append(t - (sync + P["lead"]))
        t += ln
    return np.array(out) * P["step"]


def load_hw(d, prefix, part, P):
    f = os.path.join(d, f"{prefix}_{part}.f32")
    rate = float(open(f + ".txt").read().split()[0])
    v = np.fromfile(f, np.float32).astype(np.float64)
    fr = Fraction(FS / rate).limit_denominator(1000)
    y = resample_poly(v, fr.numerator, fr.denominator)
    y -= np.median(y)
    lead = y[: int(0.3 * FS)]                                    # recording starts in the silent lead-in
    noise = np.std(lead - np.convolve(lead, np.ones(48) / 48, mode="same"))
    hp = y - np.convolve(y, np.ones(480) / 480, mode="same")      # the pulse is a 4 ms step: high-pass first
    k = int(np.argmax(np.abs(hp) > max(10 * noise, 0.004)))
    start = k + int(round(P["lead"] * P["step"] * CLOCK * FS))
    print(f"  {part:6s}: sync at {k / FS:6.3f} s, noise {noise * 1e3:.2f} mV, pulse {np.abs(hp[k:k + 200]).max() * 1e3:.0f} mV")
    # check against the score: the scope only triggers once its pre-trigger memory is full (25 s at 20 s/div),
    # so a part that is silent at first can be captured without its sync pulse. Cross-correlate the take's attack
    # strength with the expected onsets over all offsets; if the sync position disagrees, the score wins.
    e = onsets_s(P, part)
    m = load_model(d, prefix, part, P) if os.path.exists(os.path.join(d, f"model_{prefix}_{part}.npy")) else None
    if m is not None:                                            # best reference: the model render of the part
        pad = len(m)                                             # (also for parts with few attacks); the music
                                                                 # may start up to its length before the record
        yp = np.concatenate([np.zeros(pad), y])
        lag = model_lag(yp, m) - pad
        if abs(lag - start) > 1.0 * FS:
            print(f"          model alignment differs by {(lag - start) / FS:+.2f} s: using the model")
            return yp[pad + lag:] if pad + lag >= 0 else np.concatenate([np.zeros(-pad - lag), y])
        return y[max(0, start):]
    if len(e) >= 6:                                              # the music may start before the record: pad
        pad = int((e.max() * CLOCK + 10) * FS)
        yp = np.concatenate([np.zeros(pad), y])
        lag = score_lag(yp, e) - pad
        if abs(lag - start) > 1.0 * FS:                          # a valid sync is more precise: only gross errors
            print(f"          score alignment differs by {(lag - start) / FS:+.2f} s: using the score")
            return yp[pad + lag:]
    return y[max(0, start):]


def model_lag(y, m):
    """Sample offset of the music start in y from the cross-correlation (10 ms grid) of the log envelopes of the
    take and of the model render m (starting at the music start, stretched by CLOCK)."""
    def env(x):
        p = np.convolve(x ** 2, np.ones(480) / 480, mode="same")[::480]
        le = np.log10(np.sqrt(p) + 1e-3)                         # floor ~ the take's noise (1 mV)
        return le - le.mean()
    a, b = env(y), env(m)
    b = np.interp(np.arange(int(len(b) * CLOCK)) / CLOCK, np.arange(len(b)), b)
    c = fftconvolve(a, b[::-1], mode="valid") if len(a) > len(b) else fftconvolve(a, b[::-1])[len(b) - 1:]
    return int(np.argmax(c)) * 480


def score_lag(y, e):
    """Sample offset of the music start in y: cross-correlation (10 ms grid) of the attack strength with the
    expected onsets e (s, nominal clock, scaled by CLOCK), each smeared to +-30 ms."""
    a = np.abs(y)
    fast = np.convolve(a, np.ones(96) / 96, mode="same")
    slow = np.convolve(a, np.ones(960) / 960, mode="same")
    flux = np.maximum(fast - slow, 0)[::480]                     # 100 Hz
    flux = flux / (np.median(flux) + 1e-9)
    imp = np.zeros(int(e.max() * CLOCK * 100) + 10)
    for t in e:
        imp[int(t * CLOCK * 100)] = 1.0
    imp = np.convolve(imp, np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2), mode="same")
    c = np.correlate(flux, imp, "valid") if len(flux) > len(imp) else np.zeros(1)
    return int(np.argmax(c)) * 480


def fit_clock(y, e):
    """Clock ratio k (recorded time = b + k * nominal time) of one take from its note onsets e (s): onset
    strength = fast minus slow envelope. A grid search over k (+-0.3 %) and b (+-50 ms) maximises the summed
    onset strength at the predicted times (dense parts such as 16th hats otherwise lock onto a neighbouring
    grid), then peaks within +-20 ms of the prediction give a robust line fit.
    Returns (k, b, n_found, n_used, residual rms) or None if there are too few onsets."""
    if len(e) < 6:
        return None
    a = np.abs(y)
    fast = np.convolve(a, np.ones(96) / 96, mode="same")
    slow = np.convolve(a, np.ones(960) / 960, mode="same")
    flux = np.maximum(fast - slow, 0)
    fl = np.convolve(flux, np.ones(96) / 96, mode="same")[::48]            # 1 kHz, smoothed over 2 ms
    best = (-1.0, CLOCK, 0.0)
    for k in CLOCK * (1 + np.arange(-0.003, 0.003, 0.00002)):
        for b in np.arange(-0.05, 0.051, 0.002):
            i = np.round((b + k * e) * 1000).astype(int)
            i = i[(i >= 0) & (i < len(fl))]
            sc = fl[i].sum()
            if sc > best[0]:
                best = (sc, k, b)
    _, k, b = best
    for it in range(3):
        pts = []
        for t in e:
            c = int((b + k * t) * FS)
            lo, hi = c - int(0.02 * FS), c + int(0.02 * FS)
            if lo < 0 or hi > len(flux):
                continue
            w = flux[lo:hi]
            if w.max() > 4 * np.median(flux[max(0, lo - FS // 2):lo + 1] + 1e-9):
                pts.append((t, (lo + np.argmax(w)) / FS))
        if len(pts) < 6:
            return None
        p = np.array(pts)
        k, b = np.polyfit(p[:, 0], p[:, 1], 1)
        r = p[:, 1] - (k * p[:, 0] + b)
        keep = np.abs(r) < 3 * 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-3
        k, b = np.polyfit(p[keep, 0], p[keep, 1], 1)
    r = p[keep, 1] - (k * p[keep, 0] + b)
    return k, b, len(p), int(keep.sum()), np.std(r)


def warp(y, k, k_ref):
    """Resample a take so that its notes fall at k_ref * nominal time (anchored at the music start)."""
    n = int(len(y) * k_ref / k)
    t = (k / k_ref) * (np.arange(n) / FS)
    return np.interp(t * FS, np.arange(len(y)), y, right=0.0)


def load_model(d, prefix, part, P):
    cache = os.path.join(d, f"model_{prefix}_{part}.npy")
    tune = P["parts"][part]
    if not os.path.exists(cache):
        import behav as B
        notes, t_end = TU.to_notes(tune, t0=0.0)
        y, _ = B.render(notes, TU.PRESETS[tune["preset"]], t_end, automation=TU.automation(tune))
        np.save(cache, y.astype(np.float32))
    y = np.load(cache).astype(np.float64)
    pre = 0                                                      # no sync pulse: skip the lead-in in time steps
    for n, ln, fl in tune["steps"]:
        if n >= TU.CTRL:
            continue
        pre += ln
        if "Y" in fl:
            break
    pre += P["lead"] - 1
    return y[int(round(pre * P["step"] * FS)):]


def gate(y, thr):
    """Smooth gate: 2 ms attack, 120 ms release, -30 dB floor."""
    env = np.abs(y)
    a, r = np.exp(-1 / (0.002 * FS)), np.exp(-1 / (0.12 * FS))
    e = np.empty_like(env); s = 0.0
    for i in range(0, len(env), 48):                             # 1 ms blocks: fast enough, still smooth
        m = env[i:i + 48].max()
        s = m + (s - m) * (a if m > s else r) ** 48
        e[i:i + 48] = s
    g = np.clip((e / thr - 0.5) / 0.5, 0.0, 1.0) * (1 - 0.0316) + 0.0316
    return y * g


def pingpong(y, delay, fb=0.35, wet=0.22):
    n = int(delay * FS)
    L, R = np.zeros(len(y) + 8 * n), np.zeros(len(y) + 8 * n)
    x = y * wet
    for k in range(1, 8):
        seg = x * fb ** (k - 1)
        (L if k % 2 else R)[k * n:k * n + len(y)] += seg
    return L[: len(y)], R[: len(y)]


def reverb_ir(rt60=2.3, pre=0.02, seed=0):
    """Hall impulse response: exponentially decaying noise (4 kHz one-pole low-pass), stereo via seeds."""
    rng = np.random.default_rng(seed)
    n = int(rt60 * 1.2 * FS)
    ir = rng.standard_normal(n) * 10 ** (-3 * (np.arange(n) / FS) / rt60)
    k = 1 - np.exp(-2 * np.pi * 4000 / FS)
    ir = lfilter([k], [1, -(1 - k)], ir)
    ir = np.concatenate([np.zeros(int(pre * FS)), ir])
    return ir / np.sqrt(np.sum(ir ** 2))


def render(src, d, name="demo", only=None, end_s=None, fade_s=0.0):
    """Stereo mix (n x 2, not normalised) of a piece, optionally of a subset of its parts and cut at end_s
    (nominal s from the music start, faded out over fade_s before it; the reverb tail stays). Returns
    (stereo, clock): clock = the reference take's clock ratio (1.0 for the model)."""
    P = piece(name)
    load = load_hw if src == "hw" else load_model
    tracks = {}
    for part in (p for p in P["mix"] if only is None or p in only):
        print("loading", part)
        tracks[part] = load(d, name, part, P)
    if src == "hw":                                              # per-take clock drift: warp every take onto a
        fits = {p: fit_clock(y, onsets_s(P, p)) for p, y in tracks.items()}   # reference take's clock
        ok = {p: f for p, f in fits.items() if f is not None and f[4] < 0.010}   # slow attacks: vague
        if ok:
            ref = P["ref"] if P["ref"] in ok else max(ok, key=lambda p: ok[p][3])
            k_ref = ok[ref][0]
        else:                                                    # e.g. pads only: the board's nominal clock
            k_ref = CLOCK
        for p, y in tracks.items():
            if p in ok:
                k = ok[p][0]
                print(f"  {p:6s}: clock {(k - 1) * 100:+.3f} % ({ok[p][3]} onsets, {ok[p][4] * 1e3:.1f} ms rms),"
                      f" warped by {(k_ref / k - 1) * 100:+.3f} %")
            else:
                k = float(np.median([f[0] for f in ok.values()])) if ok else CLOCK
                why = "too few attacks to fit" if fits[p] is None else f"unreliable fit ({fits[p][4] * 1e3:.0f} ms rms)"
                print(f"  {p:6s}: {why}, median clock {(k - 1) * 100:+.3f} % of the other takes")
            tracks[p] = warp(y, k, k_ref)
        clock = k_ref
    else:
        clock = 1.0
    n = min(max(len(t) for t in tracks.values()), int((P["total"] * P["step"] * clock + 4.0) * FS))
    L, R = np.zeros(n), np.zeros(n)
    for part, y in tracks.items():
        y = np.pad(y[:n], (0, max(0, n - len(y))))
        thr = 0.02 * np.abs(y).max()
        y = gate(y, thr) * 10 ** (P["mix"][part][0] / 20)
        pan = P["mix"][part][1]
        gl, gr = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        if part in P["haas"]:                                    # Haas: 14 ms later on the right
            dly = np.concatenate([np.zeros(int(0.014 * FS)), y])[:n]
            L += gl * y; R += gr * dly
        else:
            L += gl * y; R += gr * y
        if part == P["delay"]:
            dl, dr = pingpong(y, 3 * P["step"] if name == "demo" else 0.375)
            L += dl; R += dr
    if end_s is not None:
        e, f = int(end_s * clock * FS), int(fade_s * clock * FS)
        env = np.clip((e - np.arange(n)) / max(f, 1), 0.0, 1.0)
        L, R = L * env, R * env
    if P["reverb"]:
        wl, wr = fftconvolve(L, reverb_ir(seed=1))[:n], fftconvolve(R, reverb_ir(seed=2))[:n]
        g = P["reverb"] * np.sqrt(np.mean(L ** 2) / max(np.mean(wl ** 2), 1e-12))
        L, R = L + g * wl, R + g * wr
    end = int(len(L) - np.argmax((np.abs(L) + np.abs(R))[::-1] > 1e-3 * np.abs(L).max())) + int(1.0 * FS)
    return np.stack([L[:end], R[:end]], 1), clock


def write(st, base):
    """Normalise to -1 dBFS, fade out the last 0.5 s, write base.wav and base.mp3."""
    st = st * 10 ** (-1 / 20) / np.abs(st).max()
    fade = int(0.5 * FS)
    st[-fade:] *= np.linspace(1, 0, fade)[:, None]
    pcm = np.clip(np.round(st * 32767), -32768, 32767).astype(np.int16)
    with wave.open(base + ".wav", "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", base + ".wav", "-codec:a", "libmp3lame", "-q:a", "2",
                    base + ".mp3"], check=True)
    print(f"{base}.wav / .mp3: {len(st) / FS:.1f} s")


def main(src, d, name="demo"):
    st, _ = render(src, d, name)
    write(st, os.path.join(d, f"{name}_{src}" if name != "demo" else f"touchsynth_demo_{src}"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "demo")
