"""Demo tunes in the firmware step format (also exported to C for the MCU later).

Step = (note, length_16ths, flags): note = MIDI number (0 = rest), flags: 'S' slide (glide into the note,
no envelope retrigger feel), 'A' accent (more filter envelope + level). 3 bytes per step in flash.
Each tune also names a preset (patch) from PRESETS.
"""

PRESETS = {
    "acid": dict(saw=1.0, cutoff=170.0, env_amt=3.2, res=0.8, keytrack=0.3, vol=0.8,
                 fenv=("adsr", 0.002, 0.09, 0.0, 0.04), aenv=("adsr", 0.002, 0.2, 0.7, 0.02),
                 accent=dict(env_amt=4.8, vol=1.0), slide=dict(glide=0.045)),
    "arp": dict(saw=1.0, pulse=1, pw=0.3, cutoff=700.0, env_amt=3.0, res=0.55, keytrack=0.5, vol=0.8,
                fenv=("adsr", 0.001, 0.12, 0.1, 0.1), aenv=("adsr", 0.002, 0.18, 0.4, 0.12),
                lfo_rate=0.15, lfo_pw=0.2),
    "lead": dict(saw=1.0, sub=1, cutoff=1400.0, env_amt=1.5, res=0.35, keytrack=0.6, vol=0.9,
                 fenv=("adsr", 0.01, 0.5, 0.4, 0.3), aenv=("adsr", 0.01, 0.4, 0.85, 0.25),
                 glide=0.05, lfo_rate=5.2, lfo_pitch=18.0),
    # ---- percussion (v4, 2026-10-18). The DCO is a timer, so the firmware sweeps its pitch per ms (penv: offset in
    # semitones at the attack, decaying with time constant penv_t) and switches the waveform mask wave_t after the
    # attack (wave2): tone and noise share one filter and VCA, so a drum's tone and noise parts are separated in time.
    # v1-v3 (no pitch envelope) were a pinged filter (tom-like at ~250 Hz), a sub square (41 Hz boom, no punch),
    # and a 146 Hz pulse ringing under the snare noise.
    # Kick: sub square (A2 -> 55 Hz) swept down two octaves from 220 Hz, the filter follows (key tracking 1), a
    # 3 ms noise click.
    "kick": dict(saw=0.0, sub=1, noise=1, wave2=dict(sub=1), wave_t=0.003, penv=24, penv_t=0.022,
                 cutoff=300.0, keytrack=1.0, env_amt=2.0, res=0.15, vol=1.0,
                 fenv=("adsr", 0.001, 0.012, 0.0, 0.03), aenv=("adsr", 0.001, 0.2, 0.0, 0.06),
                 accent=dict(env_amt=2.6, vol=1.0)),
    # Snare: a pulse body (D3, dropping a fifth) with noise for 25 ms, then noise only through a bright filter
    "snare": dict(saw=0.0, pulse=1, pw=0.5, noise=1, wave2=dict(noise=1), wave_t=0.020, penv=7, penv_t=0.015,
                  cutoff=2600.0, env_amt=1.3, res=0.15, keytrack=0.0, vol=1.0,
                  fenv=("adsr", 0.001, 0.06, 0.0, 0.04), aenv=("adsr", 0.001, 0.12, 0.0, 0.05)),
    # Hat: noise, high resonant cutoff (a metallic peak), short decay
    "hat": dict(saw=0.0, noise=1, cutoff=8500.0, env_amt=0.5, res=0.55, keytrack=0.0, vol=0.65,
                fenv=("adsr", 0.001, 0.015, 0.0, 0.02), aenv=("adsr", 0.001, 0.018, 0.0, 0.02),
                accent=dict(env_amt=0.8, vol=0.8)),
    "sweep": dict(saw=1.0, sub=1, cutoff=180.0, env_amt=4.2, res=0.7, keytrack=0.3, vol=0.75,
                  fenv=("adsr", 1.6, 2.5, 0.25, 1.2), aenv=("adsr", 0.25, 1.0, 0.9, 1.5)),
    # ---- classical / space-synth pieces (sim/behav/pieces.py); cutoff and resonance are swept by control steps
    "brass": dict(saw=1.0, pulse=1, pw=0.4, cutoff=500.0, env_amt=2.8, res=0.3, keytrack=0.6, vol=0.85,
                  fenv=("adsr", 0.06, 0.8, 0.35, 0.5), aenv=("adsr", 0.035, 0.4, 0.85, 0.5)),
    # Timpani (March, kettledrums on C and G), matched to a recorded timpani (C3 stroke): a kettledrum has little
    # energy at its nominal pitch f; its partials sit at 1.5, 2, 2.5 (and ~3.25) x f, 2f the strongest, the
    # 1.5f one leading in the first 30 ms; decay time constant ~0.4 s. Synth: the resonance peak locked onto
    # 2f by key tracking (peak = 2.1 x cutoff); the pulse partly cancels the saw fundamental. For the first 40 ms
    # the sub (f/2 square: 0.5, 1.5, 2.5 f) and noise add the 1.5f / 2.5f partials and the mallet thud, then
    # saw + pulse ring on 2f. Missing: the inharmonic partials (one periodic oscillator) and f at -11 dB.
    "timpani": dict(saw=1.0, pulse=1, pw=0.5, sub=1, noise=1, wave2=dict(saw=1.0, pulse=1), wave_t=0.040,
                    cutoff=262.0, keytrack=1.0, env_amt=0.0, res=0.88, vol=0.8,
                    fenv=("adsr", 0.001, 0.05, 0.0, 0.1), aenv=("adsr", 0.004, 0.45, 0.0, 0.4),
                    accent=dict(vol=1.0)),
    "organ": dict(saw=1.0, pulse=1, sub=1, pw=0.5, cutoff=1800.0, env_amt=1.0, res=0.25, keytrack=0.7, vol=0.85,
                  fenv=("adsr", 0.005, 0.3, 0.6, 0.2), aenv=("adsr", 0.005, 0.2, 1.0, 0.15)),
    "pedal": dict(saw=1.0, cutoff=300.0, env_amt=1.5, res=0.3, keytrack=0.3, vol=0.9,
                  fenv=("adsr", 0.01, 0.5, 0.4, 0.6), aenv=("adsr", 0.01, 0.3, 1.0, 0.6)),
    "strings": dict(saw=1.0, pulse=1, pw=0.5, lfo_pw=0.3, lfo_rate=0.4, cutoff=900.0, env_amt=1.0, res=0.2,
                    keytrack=0.5, vol=0.8, fenv=("adsr", 0.8, 1.5, 0.6, 1.5), aenv=("adsr", 0.6, 1.0, 0.9, 1.5)),
    "wind": dict(saw=0.0, noise=1, cutoff=300.0, env_amt=0.0, res=0.9, keytrack=0.0, vol=0.8,
                 fenv=("adsr", 0.01, 0.1, 1.0, 0.1), aenv=("adsr", 1.5, 1.0, 1.0, 3.0)),
    "seq": dict(saw=1.0, pulse=1, pw=0.35, cutoff=400.0, env_amt=3.0, res=0.6, keytrack=0.5, vol=0.8,
                fenv=("adsr", 0.001, 0.12, 0.0, 0.1), aenv=("adsr", 0.001, 0.2, 0.3, 0.12)),
    "theremin": dict(saw=0.0, pulse=1, pw=0.5, cutoff=1200.0, env_amt=0.5, res=0.2, keytrack=0.6, vol=0.85,
                     glide=0.12, lfo_rate=5.5, lfo_pitch=25.0,
                     fenv=("adsr", 0.2, 0.5, 0.8, 0.6), aenv=("adsr", 0.15, 0.5, 0.9, 0.6)),
}

def _transpose(steps, d):
    return [(n + d if n else 0, ln, fl) for n, ln, fl in steps]


_ACID_A = [  # original acid line in A minor, 2 bars
    (45, 1, ""), (45, 1, "A"), (57, 1, "S"), (45, 1, ""), (0, 1, ""), (48, 1, "A"), (45, 1, ""), (55, 1, "S"),
    (45, 1, ""), (43, 1, ""), (45, 1, "A"), (0, 1, ""), (52, 1, "S"), (45, 1, ""), (57, 1, "A"), (55, 1, "S"),
    (45, 1, ""), (45, 1, "A"), (57, 1, "S"), (45, 1, ""), (0, 1, ""), (48, 1, "A"), (50, 1, "S"), (52, 1, ""),
    (45, 1, ""), (43, 1, "A"), (40, 1, "S"), (0, 1, ""), (45, 1, ""), (48, 1, "A"), (52, 1, "S"), (57, 1, ""),
]
_ACID_TURN = [  # 2-bar turnaround back to A minor
    (45, 1, "A"), (57, 1, "S"), (45, 1, ""), (57, 1, "A"), (45, 1, ""), (55, 1, "S"), (45, 1, ""), (53, 1, "A"),
    (52, 1, "S"), (45, 1, ""), (50, 1, "A"), (48, 1, "S"), (45, 1, ""), (47, 1, "S"), (48, 1, "A"), (52, 1, "S"),
    (40, 1, "A"), (52, 1, "S"), (40, 1, ""), (52, 1, "A"), (0, 1, ""), (44, 1, "S"), (47, 1, ""), (52, 1, "A"),
    (56, 1, "S"), (52, 1, ""), (47, 1, "A"), (44, 1, "S"), (40, 1, ""), (0, 1, ""), (44, 1, "A"), (47, 1, "S"),
]

# J.S. Bach, Prelude in C major BWV 846, bars 1-19 (public domain), one octave down, 16th-note arpeggio:
# each bar = two times (n1 n2 n3 n4 n5 n3 n4 n5)
_PRELUDE_BARS = [
    [48, 52, 55, 60, 64], [48, 50, 57, 62, 65], [47, 50, 55, 62, 65], [48, 52, 55, 60, 64],
    [48, 52, 57, 64, 69], [48, 50, 54, 57, 62], [47, 50, 55, 62, 67], [47, 48, 52, 55, 60],
    [45, 48, 52, 55, 60], [38, 45, 50, 54, 60], [43, 47, 50, 55, 59], [43, 46, 52, 55, 61],
    [41, 45, 50, 57, 62], [41, 44, 50, 53, 59], [40, 43, 48, 55, 60], [40, 41, 45, 48, 53],
    [38, 41, 45, 48, 53], [31, 38, 43, 47, 53], [36, 40, 43, 48, 52],
]

# L. v. Beethoven, "Ode to Joy" theme (public domain): A A' B A', quarter note = 4 sixteenths
_ODE_A = [(64, 4, ""), (64, 4, ""), (65, 4, "S"), (67, 4, "S"), (67, 4, ""), (65, 4, "S"), (64, 4, "S"), (62, 4, "S"),
          (60, 4, ""), (60, 4, ""), (62, 4, "S"), (64, 4, "S")]
_ODE_B = [(62, 4, ""), (62, 4, ""), (64, 4, "S"), (60, 4, "S"), (62, 4, ""), (64, 2, "S"), (65, 2, "S"), (64, 4, "S"),
          (60, 4, "S"), (62, 4, ""), (64, 2, "S"), (65, 2, "S"), (64, 4, "S"), (62, 4, "S"), (60, 4, "S"),
          (62, 4, "S"), (55, 8, "")]

TUNES = {
    # original acid line: A A B(a fourth up) A, turnaround
    "acid": dict(bpm=128, preset="acid", steps=_ACID_A * 2 + _transpose(_ACID_A, 5) + _ACID_A + _ACID_TURN),
    "prelude": dict(bpm=100, preset="arp", steps=[
        (n, 1, "") for bar in _PRELUDE_BARS
        for _ in range(2) for n in (bar[0], bar[1], bar[2], bar[3], bar[4], bar[2], bar[3], bar[4])
    ] + [(36, 16, "")]),
    "ode": dict(bpm=110, preset="lead", steps=(
        _ODE_A + [(64, 6, ""), (62, 2, "S"), (62, 8, "")] + _ODE_A + [(62, 6, ""), (60, 2, "S"), (60, 8, "")]
        + _ODE_B + _ODE_A + [(62, 6, ""), (60, 2, "S"), (60, 8, "")])),
}


# ---- control steps (firmware synth.h CTRL_*): note >= 128, len = value, take no time
CTRL, C_CUT, C_RAMP, C_RES, C_ENV, C_WAVE, C_VOL = 128, 128, 129, 130, 131, 132, 133


def cut(hz, ramp=None):
    """Cutoff target (Hz); with ramp (16ths) it glides there, as do later RES targets until the next RAMP."""
    import math
    v = max(0, min(255, round(16 * math.log2(hz / 16.0))))
    return [(C_RAMP, min(255, ramp or 0), ""), (C_CUT, v, "")]       # ramp always explicit (0 = jump)


def res(r, ramp=None):
    """Resonance target (1.0 = self-oscillation threshold)."""
    return [(C_RAMP, min(255, ramp or 0), ""), (C_RES, max(0, min(255, round(r * 200))), "")]


def ctrl(**kw):
    """Immediate settings: env (octaves), wave (mask 1 saw 2 pulse 4 sub 8 noise), vol (0...1)."""
    out = []
    if "env" in kw:
        out.append((C_ENV, max(0, min(255, round(kw["env"] * 16))), ""))
    if "wave" in kw:
        out.append((C_WAVE, kw["wave"], ""))
    if "vol" in kw:
        out.append((C_VOL, max(0, min(255, round(kw["vol"] * 255))), ""))
    return out


def automation(tune, t0=0.0):
    """The control steps of a tune as a behavioural-model automation function f(t, p) -> overrides."""
    import math
    s16 = tune["step_ms"] / 1000 if "step_ms" in tune else 60.0 / tune["bpm"] / 4
    p0 = PRESETS[tune["preset"]]
    cur = dict(lc=math.log2(p0.get("cutoff", 8000.0)), r=p0.get("res", 0.0))
    t, ramp, segs, steps = t0, 0, {"lc": [], "r": []}, []
    for n, ln, fl in tune["steps"]:
        if n >= CTRL:
            if n == C_RAMP:
                ramp = ln
            elif n in (C_CUT, C_RES):
                key = "lc" if n == C_CUT else "r"
                tgt = math.log2(16.0) + ln / 16 if n == C_CUT else ln / 200
                segs[key].append((t, t + ramp * s16, tgt))
            elif n == C_ENV:
                steps.append((t, dict(env_amt=ln / 16)))
            elif n == C_WAVE:
                steps.append((t, dict(saw=1.0 if ln & 1 else 0.0, pulse=1 if ln & 2 else 0, sub=1 if ln & 4 else 0,
                                      noise=1 if ln & 8 else 0)))
            elif n == C_VOL:
                steps.append((t, dict(vol=ln / 255)))
            continue
        t += ln * s16

    def value(key, t):
        v = cur[key]
        for a, b, tgt in segs[key]:                        # each segment starts from the value reached so far
            if t < a:
                break
            v = tgt if t >= b or b <= a else v + (tgt - v) * (t - a) / (b - a)
        return v

    def f(t, p):
        o = {"cutoff": 2 ** value("lc", t), "res": value("r", t)}
        for ts, d in steps:
            if ts <= t:
                o.update(d)
        return o
    return f


def _sync():
    """Lead-in of every multitrack part: one empty bar (the VCA is held closed for 0.5 s after a reset), then a
    sync step ('Y': the firmware opens the VCA fully for 4 ms, a sharp marker whatever the preset) at the
    downbeat of the count-in bar. The mix aligns the separate recordings on it and cuts both bars."""
    return [(0, 16, ""), (0, 1, "Y"), (0, 15, "")]


# ---------------------------------------------------------------------------------------------------------------
# "TouchSynth Demo" (2026, original): A minor, 118 bpm, 69 bars, seven parts recorded one at a time and mixed.
#   1-8 intro (pad, hats from 5) | 9-24 groove (acid bass, drums) | 25-40 arp (PWM) | 41-56 lead (glide, vibrato)
#   57-60 breakdown (pad, arp, hats, snare roll) | 61-68 finale (all, melody reprise) | 69 ending
DEMO_BPM = 118
_CH = {  # chord: bass root, arpeggio voicing, pad note
    "Am": (45, [57, 60, 64, 69], 64), "F": (41, [53, 57, 60, 65], 65),
    "C": (48, [55, 60, 64, 67], 64), "G": (43, [55, 59, 62, 67], 62),
}
_PROG = ["Am", "F", "C", "G"]
_CHORDS = (["Am", "Am", "F", "F", "C", "C", "G", "G"]          # 1-8 (two bars per chord)
           + _PROG * 11 + ["Am", "F", "G", "Am"]                # 9-56, cadence of the melody at 53-56
           + _PROG                                             # 57-60
           + _PROG + ["Am", "F", "G", "Am"]                    # 61-68
           + ["Am"])                                           # 69
_N_BARS = len(_CHORDS)
_REST = [(0, 16, "")]


def _bars(lo, hi):
    return range(lo, hi + 1)


def _hits(on, note, acc=()):
    """One bar of percussion: hits at the 16th positions `on`, each lasting until the next hit."""
    on = sorted(on)
    ev = [(0, on[0], "")] if on and on[0] else []
    for i, s in enumerate(on):
        ev.append((note, (on[i + 1] if i + 1 < len(on) else 16) - s, "A" if s in acc else ""))
    return ev or _REST


def _part(bar_fn):
    steps = _sync()
    for b in _bars(1, _N_BARS):
        ev = bar_fn(b, _CHORDS[b - 1])
        assert sum(ln for n, ln, _ in ev if n < CTRL) == 16, (bar_fn.__name__, b)
        steps += ev
    out = []                                                    # merge consecutive rests
    for n, ln, fl in steps:
        if out and n == 0 and out[-1][0] == 0 and not fl and not out[-1][2] and out[-1][1] + ln <= 255:
            out[-1] = (0, out[-1][1] + ln, "")
        else:
            out.append((n, ln, fl))
    return out


_PHRASE_END = {16, 24, 32, 40, 48, 56, 64}


def _kick(b, ch):
    if b in _bars(9, 56) or b in _bars(61, 68):
        return _hits([0, 4, 8, 12, 14] if b in _PHRASE_END else [0, 4, 8, 12], 45, acc=(0,))
    if b == 69:
        return _hits([0], 45, acc=(0,))
    return _REST


def _snare(b, ch):
    if b in (24, 40, 56):
        return _hits([4, 12, 13, 14, 15], 50, acc=(15,))
    if b == 60:
        return _hits([0, 2, 4, 6, 8, 9, 10, 11, 12, 13, 14, 15], 50, acc=(12, 13, 14, 15))
    if b in _bars(13, 56) or b in _bars(61, 68):
        return _hits([4, 12], 50)
    return _REST


def _hat(b, ch):
    off8, all8, all16 = [2, 6, 10, 14], list(range(0, 16, 2)), list(range(16))
    if b in _bars(5, 8) or b in _bars(57, 60):
        return _hits(off8, 60)
    if b in _bars(9, 24):
        return _hits(all8, 60, acc=off8)
    if b in _bars(25, 56) or b in _bars(61, 68):
        return _hits(all16, 60, acc=off8)
    return _REST


_BASS = [(0, ""), (0, "A"), (12, "S"), (0, ""), (None, ""), (0, "A"), (7, "S"), (0, ""),
         (0, ""), (None, ""), (12, "A"), (0, ""), (7, "S"), (0, ""), (12, "A"), (0, "S")]
_BASS_TURN = [(12, "A"), (10, "S"), (7, ""), (2, "S")]           # last four 16ths before the next phrase


def _bass(b, ch):
    root = _CH[ch][0]
    if b == 69:
        return [(root, 8, "A"), (0, 8, "")]
    if not (b in _bars(9, 56) or b in _bars(61, 68)):
        return _REST
    pat = _BASS[:12] + _BASS_TURN if (b % 4 == 0 and ch == "G") else _BASS
    return [(0, 1, "") if o is None else (root + o, 1, f) for o, f in pat]


def _arp(b, ch):
    if not (b in _bars(25, 68)):
        return _REST
    v = _CH[ch][1]
    notes = v + [v[1] + 12]
    return [(notes[i], 1, "") for i in [0, 1, 2, 3, 4, 3, 2, 1] * 2]


_MELODY = [  # 16 bars over Am F C G | Am F C G | Am F C G | Am F G Am
    [(76, 4, ""), (74, 2, "S"), (72, 2, "S"), (71, 4, "S"), (72, 4, "")],
    [(69, 8, ""), (72, 4, "S"), (77, 4, "")],
    [(76, 6, ""), (74, 2, "S"), (72, 4, "S"), (76, 4, "")],
    [(74, 8, ""), (71, 4, "S"), (67, 4, "")],
    [(76, 4, ""), (74, 2, "S"), (72, 2, "S"), (71, 4, "S"), (69, 4, "")],
    [(72, 6, ""), (69, 2, "S"), (65, 4, ""), (69, 4, "S")],
    [(67, 4, ""), (72, 4, ""), (76, 4, ""), (79, 4, "")],
    [(79, 8, ""), (77, 4, "S"), (74, 4, "S")],
    [(81, 8, "A"), (79, 4, "S"), (76, 4, "")],
    [(77, 6, ""), (76, 2, "S"), (72, 8, "")],
    [(76, 4, ""), (79, 4, ""), (84, 8, "A")],
    [(83, 8, ""), (79, 8, "S")],
    [(81, 6, ""), (79, 2, "S"), (76, 4, ""), (74, 4, "S")],
    [(72, 4, ""), (74, 4, "S"), (76, 4, "S"), (77, 4, "")],
    [(74, 8, ""), (71, 8, "S")],
    [(69, 16, "")],
]


def _lead(b, ch):
    if b in _bars(41, 56):
        return _MELODY[b - 41]
    if b in _bars(61, 68):
        return _MELODY[b - 61 + 8]                              # reprise: the last eight bars
    if b == 69:
        return [(69, 12, ""), (0, 4, "")]
    return _REST


def _pad(b, ch):
    note = _CH[ch][2]
    if b in _bars(1, 8):
        return [(note, 16, "S")] if b % 2 else [(note, 16, "")]  # one 2-bar note: legato into the second bar
    if b in _bars(9, 16) or b in _bars(57, 68):
        return [(note, 16, "")]
    if b == 69:
        return [(note, 12, ""), (0, 4, "")]
    return _REST


# Multitrack parts: recorded one at a time from the line out and mixed (tools/mix_parts.py). Firmware: CH32V006
# only (flash), not in the SHIFT + C' demo cycle; play with the console command 'tune <index>'.
PARTS = {
    "demo_kick": dict(bpm=DEMO_BPM, preset="kick", steps=_part(_kick)),
    "demo_snare": dict(bpm=DEMO_BPM, preset="snare", steps=_part(_snare)),
    "demo_hat": dict(bpm=DEMO_BPM, preset="hat", steps=_part(_hat)),
    "demo_bass": dict(bpm=DEMO_BPM, preset="acid", steps=_part(_bass)),
    "demo_arp": dict(bpm=DEMO_BPM, preset="arp", steps=_part(_arp)),
    "demo_lead": dict(bpm=DEMO_BPM, preset="lead", steps=_part(_lead)),
    "demo_pad": dict(bpm=DEMO_BPM, preset="sweep", steps=_part(_pad)),
}


def to_notes(tune, gate=0.8, t0=0.05):
    """Expand a tune into (t_on, dur, midi, overrides) events for behav.firmware()."""
    p = PRESETS[tune["preset"]]
    s16 = tune["step_ms"] / 1000 if "step_ms" in tune else 60.0 / tune["bpm"] / 4
    t, out = t0, []
    for note, ln, fl in tune["steps"]:
        if note >= CTRL:                                   # control step: no time (see automation())
            continue
        dur = ln * s16
        if note:
            ov = {}
            if "A" in fl:
                ov.update(p.get("accent", {}))
            if "S" in fl:
                ov.update(p.get("slide", dict(glide=0.06)))
            else:
                ov.setdefault("glide", p.get("glide", 0.0) if "S" in fl else 0.0)
            g = 1.0 if ("S" in fl or "H" in fl) else gate
            if "T" in fl and out and out[-1][2] == note:      # tie: extend the previous note, no new attack
                t_on, _, _, ov0 = out[-1]
                out[-1] = (t_on, t + dur * g - t_on, note, ov0)
            else:
                out.append((t, dur * g, note, ov))
        t += dur
    return out, t + 0.6


def to_c(name, tune):
    """C array for the firmware (note, len, flags)."""
    fl = lambda f: ("1" if "S" in f else "0") + "|" + ("2" if "A" in f else "0")
    body = ",\n    ".join(f"{{{n:3d}, {l:2d}, {fl(f)}}}" for n, l, f in tune["steps"])
    return (f"static const tune_step_t tune_{name}[] = {{\n    {body}\n}};  /* {tune['bpm']} bpm, "
            f"preset {tune['preset']} */\n")
