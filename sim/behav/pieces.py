"""Multitrack pieces for the TouchSynth (recorded part by part from the line out, mixed by tools/mix_parts.py).

Each part is written as notes (start, duration, midi, flags) and control events (time, control steps from
tunes.cut / res / ctrl) on a grid of `steps`; build() turns that into firmware tune steps: a lead-in (empty, then
the sync step 'Y', then the count-in), control steps at their times, notes split at control points into tied
chunks ('H' hold + 'T' tie) and into chunks of <= 255 steps.

  march     H. Purcell, March from the Music for the Funeral of Queen Mary (1695, public domain), from the WIMA
            edition by M. Straeten (IMSLP #198768); arrangement for TouchSynth 2026 (own, not W. Carlos's)
"""
import math
from tunes import cut, res, ctrl, CTRL

LEAD_MS = 2000                                   # empty lead-in and count-in, each


def build(notes, ctrls, total, step_ms):
    """notes: (start, dur, midi, flags) in steps, mono (non-overlapping); ctrls: (time, [control steps]).
    Returns the firmware step list incl. lead-in, and the number of lead-in steps after the sync step."""
    lead = int(math.ceil(LEAD_MS / step_ms))
    out = []

    def rest(n):
        while n > 0:
            out.append((0, min(255, n), ""))
            n -= 255

    def note(m, n, fl, first, last):
        chunks = []
        while n > 0:
            chunks.append(min(255, n))
            n -= 255
        for i, c in enumerate(chunks):
            is_first, is_last = first and i == 0, last and i == len(chunks) - 1
            base = fl.replace("H", "") if is_first else "T"      # later chunks continue the note (tie)
            hold = ("H" in fl) if is_last else True              # every chunk but the real end holds
            out.append((m, c, base + ("H" if hold else "")))

    rest(lead)
    out.append((0, 1, "Y"))
    rest(lead - 1)
    notes = sorted(notes)
    cmap = {}
    for t, c in ctrls:
        cmap.setdefault(t, []).extend(c)
    bounds = sorted(set([0, total] + [n[0] for n in notes] + [n[0] + n[1] for n in notes] + list(cmap)))
    ni = 0
    for a, b in zip(bounds, bounds[1:]):
        out.extend(cmap.get(a, []))
        while ni < len(notes) and notes[ni][0] + notes[ni][1] <= a:
            ni += 1
        if ni < len(notes) and notes[ni][0] <= a < notes[ni][0] + notes[ni][1]:
            s, d, m, fl = notes[ni]
            note(m, b - a, fl, a == s, b == s + d)
        else:
            rest(b - a)
    out.extend(cmap.get(total, []))
    return out, lead


def onsets(steps):
    """Attack times (in steps from the end of the lead-in) of a built part: notes that are not ties/slides."""
    t, out = 0, []
    for n, ln, fl in steps:
        if n >= CTRL:
            continue
        if n and "T" not in fl and "S" not in fl:
            out.append(t)
        t += ln
    return out


# ================================================================================================= March
# Four trumpets (I top ... IV bass) per bar: (I, II, III, IV), each a list of (midi, beats); 'F' = fermata bar.
_M = [
    ([(67, 4)], [(64, 4)], [(60, 4)], [(48, 4)], ""),                       # 1  C
    ([(68, 2), (68, 2)], [(65, 2), (65, 2)], [(60, 2), (60, 2)], [(53, 2), (53, 2)], ""),   # 2  Fm
    ([(67, 4)], [(64, 4)], [(60, 4)], [(48, 4)], "F"),                      # 3  C
    ([(67, 4)], [(63, 4)], [(60, 4)], [(48, 4)], ""),                       # 4  Cm
    ([(72, 2), (72, 2)], [(63, 2), (65, 2)], [(60, 2), (60, 2)], [(56, 2), (56, 2)], ""),   # 5  Ab Fm
    ([(71, 4)], [(67, 4)], [(62, 4)], [(55, 4)], "F"),                      # 6  G
    ([(74, 4)], [(70, 4)], [(67, 4)], [(55, 4)], ""),                       # 7  Gm
    ([(72, 2), (69, 2)], [(69, 2), (66, 2)], [(63, 2), (62, 2)], [(60, 2), (62, 2)], ""),   # 8  Cm6 D
    ([(70, 4)], [(67, 4)], [(62, 4)], [(55, 4)], "F"),                      # 9  Gm
    ([(70, 4)], [(67, 4)], [(63, 4)], [(51, 4)], ""),                       # 10 Eb
    ([(68, 2), (65, 2)], [(65, 2), (62, 2)], [(60, 2), (58, 2)], [(56, 2), (58, 2)], ""),   # 11 Fm Bb
    ([(67, 4)], [(63, 4)], [(58, 4)], [(51, 4)], "F"),                      # 12 Eb
    ([(72, 4)], [(67, 4)], [(63, 4)], [(48, 4)], ""),                       # 13 Cm
    ([(72, 2), (71, 2)], [(68, 2), (67, 2)], [(62, 2), (62, 2)], [(53, 2), (55, 2)], ""),   # 14 Fm/D G
    ([(72, 4)], [(64, 4)], [(60, 4)], [(48, 4)], "F"),                      # 15 C
]
MARCH_BPM = 60                                   # quarter = 60, one step = a 16th = 250 ms
_Q = 4                                           # steps per beat


_TIMP_C, _TIMP_G = 48, 43                       # the kettledrums: C3 and G2 (tonic and dominant, C minor)


def _timp_note(v):
    """Timpani note for a bar: G if the bar's first chord contains G (G, Gm, Eb, Cm, C), else C (Fm, Ab)."""
    pcs = {vv[0][0] % 12 for vv in v}
    root = v[3][0][0] % 12
    return _TIMP_G if root == 7 or (7 in pcs and root != 0) else _TIMP_C


def _march():
    """Timeline: drum-roll intro bar | pass 1 (brass, gentle sweeps, drum from bar 7) | one bar breath |
    pass 2 (brighter, resonant sweeps on the fermatas, 16' bass, drum) with a 10 s closing sweep on the last chord."""
    parts = {k: ([], []) for k in ("tpt1", "tpt2", "tpt3", "tpt4", "bass", "timp")}
    t = 0
    # intro: muffled timpani strokes on the tonic, 16ths, accent on the first and the last
    parts["timp"][0].extend((t + i, 1, _TIMP_C, "A" if i in (0, 15) else "") for i in range(16))
    t += 16
    for pas in (1, 2):
        base = 450 if pas == 1 else 800
        for k in ("tpt1", "tpt2", "tpt3", "tpt4"):
            parts[k][1].append((t, cut(base) + res(0.25 if pas == 1 else 0.35)))
        for bi, (*v, fl) in enumerate(_M):
            bar = bi + 1
            last = pas == 2 and bar == 15
            blen = 16 if not fl else (40 if last else 24)
            for k, vv in zip(("tpt1", "tpt2", "tpt3", "tpt4"), v):
                pos = t
                for j, (m, beats) in enumerate(vv):
                    d = beats * _Q
                    if fl:                                   # fermata: hold, then a breath
                        d = blen - (0 if last else 4)
                    parts[k][0].append((pos, d, m, "H" if not fl else ""))
                    pos += d
            if pas == 2:                                     # 16' bass: trumpet IV an octave down
                pos = t
                for m, beats in v[3]:
                    d = blen - (0 if last else 4) if fl else beats * _Q
                    parts["bass"][0].append((pos, d, m - 12, "H" if not fl else ""))
                    pos += d
            # timpani: march pattern (half, dotted quarter, eighth); strokes into each fermata
            if pas == 2 or bar >= 7:
                tn = _timp_note(v)
                if fl:
                    parts["timp"][0].append((t, 6, tn, "A"))
                    if not last:
                        parts["timp"][0].extend((t + blen - 8 + i, 1, tn, "A" if i == 7 else "") for i in range(8))
                else:
                    parts["timp"][0].extend([(t, 8, tn, "A"), (t + 8, 6, tn, ""), (t + 14, 2, tn, "")])
            # sweeps on all four trumpets: each phrase opens from dark; fermatas swell up and back
            for k in ("tpt1", "tpt2", "tpt3", "tpt4"):
                c = parts[k][1]
                if bar in (1, 4, 7, 10, 13):
                    c.append((t, cut(base * 0.7) + cut(base * 2.2, ramp=32)))
                if fl and not last:
                    top = 2500 if pas == 1 else 5000
                    c.append((t, cut(top, ramp=10) + (res(0.7, ramp=10) if pas == 2 else [])))
                    c.append((t + 12, cut(base, ramp=10) + (res(0.35, ramp=10) if pas == 2 else [])))
                if last:
                    c.append((t, cut(5000, ramp=8) + res(0.6, ramp=8)))
                    c.append((t + 10, cut(120, ramp=30) + res(0.95, ramp=30)))
            t += blen
        if pas == 1:
            t += 16                                          # one bar breath between the passes
    return parts, t + 16                                     # + release tail


# ================================================================================================= Toccata
# J. S. Bach, Toccata in D minor BWV 565 (public domain), measures 1-30 (to the Fugue), from the MusicXML score
# (extracted to bwv565_toccata.py). Ornaments written out, fermatas stretched in all voices, the organ texture
# (up to 9 voices) split into monophonic tracks; 20 ms grid with the tempo map built into the step counts.
TOCCATA_STEP_MS = 20
_TOC_TEMPO = [(0.0, 36), (12.0, 96), (36.0, 46), (44.0, 84), (84.0, 96), (104.0, 40)]   # (quarter, bpm)
_DM = [2, 4, 5, 7, 9, 10, 13]                    # D harmonic minor pitch classes (C# as 13 = 1 + 12)


def _neighbour(m, up):
    pcs = sorted(p % 12 for p in _DM)
    pc = m % 12
    if up:
        nxt = [p for p in pcs if p > pc]
        return m + ((nxt[0] - pc) if nxt else (pcs[0] + 12 - pc))
    prv = [p for p in pcs if p < pc]
    return m - ((pc - prv[-1]) if prv else (pc + 12 - pcs[-1]))


def _toc_timemap(fermatas, end):
    """Quarter position -> ms: tempo map, fermatas stretched to double length, the final chord x3."""
    grid = 96
    stretch = [(s, d, 1.0 * d) for s, d in fermatas if d > 0] + [(end - 2.0, 2.0, 4.0)]
    n = int(end * grid) + 1
    ms = [0.0] * (n + 1)
    for i in range(n):
        q = i / grid
        bpm = [b for qq, b in _TOC_TEMPO if qq <= q][-1]
        f = 1.0 + sum(x / d for s, d, x in stretch if s <= q < s + d)
        ms[i + 1] = ms[i] + 60000.0 / bpm / grid * f
    return lambda q: ms[min(n, int(round(q * grid)))]


def _toccata():
    import bwv565_toccata as T
    end = max(s + d for s, d, *_ in T.NOTES)
    tm = _toc_timemap(T.FERMATAS, end)
    st = lambda q: int(round(tm(q) / TOCCATA_STEP_MS))
    # ornaments written out (in quarters)
    ev = []
    for s, d, m, part, orn in T.NOTES:
        if "mordent" in orn and d >= 0.25:
            ev += [(s, 1 / 16, m, part), (s + 1 / 16, 1 / 16, _neighbour(m, False), part), (s + 1 / 8, d - 1 / 8, m, part)]
        elif "trill-mark" in orn:
            k, x = 0, s
            while x + 1 / 16 < s + d - 1e-6:
                ev.append((x, 1 / 16, m if k % 2 else _neighbour(m, True), part))
                x += 1 / 16; k += 1
            ev.append((x, s + d - x, m, part))
        else:
            ev.append((s, d, m, part))
    # monophonic tracks: pedal on its own; manual notes deduplicated, each to the free track with the nearest pitch
    notes = {f"m{i}": [] for i in range(1, 9)}
    notes["pedal"] = []
    busy = {k: (-1, None) for k in notes}
    seen, dropped = set(), 0
    for s, d, m, part in sorted(ev, key=lambda e: (e[0], e[3] == 2, -e[2])):
        a, b = st(s), max(st(s) + 1, st(s + d) - 1)              # 20 ms gap so repeated notes re-attack
        if (a, m) in seen:
            continue
        seen.add((a, m))
        cands = ["pedal"] if part == 2 else [k for k in notes if k != "pedal"]
        free = [k for k in cands if busy[k][0] <= a]
        if not free:
            dropped += 1
            continue
        k = min(free, key=lambda k: (abs((busy[k][1] or m) - m) + 0.5 * int(k[1:]) if k != "pedal" else 0))
        notes[k].append((a, b - a, m, ""))
        busy[k] = (b, m)
    used = [k for k in notes if notes[k]]
    total = st(end) + int(3000 / TOCCATA_STEP_MS)
    parts = {k: (notes[k], []) for k in used}
    # sweeps on the manual tracks: chord swells (m2-3, m10-11), Maestoso swell, closing sweep on the last chord
    for k in used:
        if k == "pedal":
            continue
        c = parts[k][1]
        c += [(0, cut(1400) + res(0.3)),
              (st(4.0), cut(600, ramp=20) + res(0.5, ramp=20)), (st(5.0), cut(4500, ramp=200) + res(0.8, ramp=200)),
              (st(10.0), cut(1400, ramp=100) + res(0.3, ramp=100)),
              (st(36.0), cut(700, ramp=20)), (st(37.0), cut(5000, ramp=255) + res(0.75, ramp=255)),
              (st(44.0), cut(1600, ramp=50) + res(0.3, ramp=50)),
              (st(104.0), cut(800, ramp=50) + res(0.5, ramp=50)), (st(106.0), cut(6000, ramp=255) + res(0.8, ramp=255)),
              (st(end - 2.0), cut(5000, ramp=25)), (st(end - 1.0), cut(200, ramp=255) + res(0.95, ramp=255))]
    print(f"toccata: tracks {used}, {dropped} notes dropped (no free track), {total * TOCCATA_STEP_MS / 1000:.1f} s")
    return parts, total


# ================================================================================================= Aerosphere
# Original (2026) in the late-70s space-synth style: wind sweeps, PWM string pad, a sequence whose filter opens
# over whole sections, theremin-like lead with glide; E minor, 100 bpm.
AERO_BPM = 100                                   # one step = a 16th = 150 ms, bar = 16 steps
_PROGA = [("Em", 52), ("C", 48), ("G", 55), ("D", 50)]          # two bars each
_PROGB = [("Am", 45), ("Em", 52), ("C", 48), ("B", 47)]
_THIRD = {"Em": 3, "Am": 3, "C": 4, "G": 4, "D": 4, "B": 4}
_PAD = {"Em": (59, 64), "C": (55, 64), "G": (59, 62), "D": (57, 62), "Am": (60, 64), "B": (54, 63)}
_LEAD = [  # (midi, beats) per 8 bars over Em C G D
    [(71, 6), (69, 2), (67, 4), (64, 4), (62, 6), (64, 2), (66, 8)],
    [(71, 4), (74, 4), (76, 6), (74, 2), (71, 4), (67, 4), (69, 8)],
    [(76, 6), (78, 2), (79, 4), (76, 4), (74, 6), (71, 2), (78, 8)],
    [(79, 4), (78, 2), (76, 2), (76, 6), (74, 2), (71, 4), (74, 4), (76, 8)],
]


def _aero():
    names = ("wind", "pad1", "pad2", "seq", "bass", "lead", "kick", "hat")
    parts = {k: ([], []) for k in names}
    bar = 16
    sec = dict(intro=(0, 8), A=(8, 24), B=(24, 40), bridge=(40, 48), A2=(48, 64), outro=(64, 68))

    def chords(b0, b1, prog):
        out, b = [], b0
        while b < b1:
            for ch, root in prog:
                if b < b1:
                    out.append((b, ch, root))
                b += 2
        return out

    plan = (chords(0, 8, _PROGA) + chords(8, 24, _PROGA) + chords(24, 40, _PROGA) + chords(40, 48, _PROGB)
            + chords(48, 64, _PROGA) + [(64, "Em", 52), (66, "Em", 52)])
    for b, ch, root in plan:
        t = b * bar
        # pads from bar 4 (two voices, 2-bar notes)
        if b >= 4:
            lo, hi = _PAD[ch]
            parts["pad1"][0].append((t, 2 * bar, lo, "H" if b < 66 else ""))
            parts["pad2"][0].append((t, 2 * bar, hi, "H" if b < 66 else ""))
        # sequence (A, B, A2): 16ths over the chord
        if 8 <= b < 40 or 48 <= b < 64:
            th = _THIRD[ch]
            pat = [0, 7, 12, 12 + th, 7, 12, 12 + th, 19] * 2
            for bb in (0, 1):
                parts["seq"][0].extend((t + bb * bar + i, 1, root + iv, "") for i, iv in enumerate(pat))
        # bass: 8ths on the root an octave down (A, B, A2), long notes in the bridge
        if 8 <= b < 40 or 48 <= b < 64:
            parts["bass"][0].extend((t + i * 2, 2, root - 12, "A" if i % 8 == 0 else "") for i in range(16))
        elif 40 <= b < 48:
            parts["bass"][0].append((t, 2 * bar, root - 12, ""))
        # rhythm: kick on 1 and 3, hats on 8ths (offbeats accented), A, B, A2
        if 8 <= b < 40 or 48 <= b < 64:
            for bb in (0, 1):
                parts["kick"][0].extend([(t + bb * bar, 8, 45, "A"), (t + bb * bar + 8, 8, 45, "")])
                parts["hat"][0].extend((t + bb * bar + 2 * i, 2, 60, "A" if i % 2 else "") for i in range(8))
    # wind: one long note per section with sweeps
    W = parts["wind"]
    for b0, b1 in ((0, 8), (40, 48), (64, 68)):
        W[0].append((b0 * bar, (b1 - b0) * bar, 60, ""))
    W[1].extend([(0, cut(200) + res(0.95)), (2, cut(3000, ramp=60) + res(0.98, ramp=60)),
             (4 * bar, cut(250, ramp=64)), (40 * bar, cut(400) + res(0.9)), (40 * bar + 2, cut(5000, ramp=64)),
             (44 * bar, cut(300, ramp=60)), (64 * bar, cut(300) + res(0.95)), (64 * bar + 2, cut(2500, ramp=32)),
             (66 * bar, cut(150, ramp=32))])
    # sequence sweeps: opens over section A, steady in B, closes in the bridge, opens wide in A2, closes out
    S = parts["seq"][1]
    S += [(8 * bar, cut(220) + res(0.65)), (8 * bar + 1, cut(2800, ramp=255)),
          (24 * bar, cut(1800, ramp=32) + res(0.55, ramp=32)), (40 * bar, cut(250, ramp=128)),
          (48 * bar, cut(300) + res(0.8)), (48 * bar + 1, cut(5000, ramp=255) + res(0.9, ramp=255)),
          (62 * bar, cut(200, ramp=32))]
    # pad: slow resonance swell in the bridge
    for k in ("pad1", "pad2"):
        parts[k][1].extend([(40 * bar, cut(600, ramp=32) + res(0.75, ramp=32)), (48 * bar, cut(900, ramp=32) + res(0.2, ramp=32))])
    # lead: phrases 1-2 in B, long notes in the bridge, phrases 3-4 in A2
    def phrase(notes, t):                       # glide within the phrase, a fresh attack at its start
        for i, (m, beats) in enumerate(notes):
            parts["lead"][0].append((t, beats * 4, m, "S" if i else ""))
            t += beats * 4
        return t
    t = phrase(_LEAD[1], phrase(_LEAD[0], 24 * bar))
    phrase(((72, 8), (71, 8), (67, 4), (76, 4), (75, 8)), 40 * bar)
    phrase(_LEAD[3], phrase(_LEAD[2], 48 * bar))
    return parts, 68 * bar + 2 * bar


def _make(piece_parts, total, bpm, presets, step_ms=None):
    step_ms = step_ms or 15000 // bpm
    out = {}
    for name, (notes, ctrls) in piece_parts.items():
        steps, lead = build(notes, ctrls, total, step_ms)
        out[name] = dict(step_ms=step_ms, preset=presets[name], steps=steps, lead=lead)
        if bpm:
            out[name]["bpm"] = bpm
    return out


_mp, _mt = _march()
PIECES = {
    "march": dict(bpm=MARCH_BPM, total=_mt,
                  parts=_make(_mp, _mt, MARCH_BPM, dict(tpt1="brass", tpt2="brass", tpt3="brass", tpt4="brass",
                                                        bass="pedal", timp="kettle")),
                  mix=dict(tpt1=(-1.0, 0.3), tpt2=(-1.5, -0.3), tpt3=(-2.0, 0.45), tpt4=(-2.0, -0.45),
                           bass=(-3.0, 0.0), timp=(-4.0, -0.1)),
                  reverb=0.30),
}
_tp, _tt = _toccata()
_pan = {"m1": 0.55, "m2": -0.55, "m3": 0.35, "m4": -0.35, "m5": 0.15, "m6": -0.15, "m7": 0.6, "m8": -0.6,
        "pedal": 0.0}
PIECES["toccata"] = dict(step_ms=TOCCATA_STEP_MS, total=_tt,
                         parts=_make(_tp, _tt, None, {k: ("pedal" if k == "pedal" else "organ") for k in _tp},
                                     step_ms=TOCCATA_STEP_MS),
                         mix={k: (0.0 if k == "pedal" else -3.0, _pan[k]) for k in _tp}, reverb=0.45)
_ap, _at = _aero()
PIECES["aero"] = dict(bpm=AERO_BPM, total=_at,
                      parts=_make(_ap, _at, AERO_BPM, dict(wind="wind", pad1="strings", pad2="strings", seq="seq",
                                                           bass="pedal", lead="theremin", kick="kick", hat="hat")),
                      mix=dict(wind=(-4.0, 0.0), pad1=(-6.0, -0.35), pad2=(-6.0, 0.35), seq=(-4.0, -0.15),
                               bass=(-4.0, 0.0), lead=(-2.0, 0.1), kick=(-7.0, 0.0), hat=(-13.0, 0.3)),
                      reverb=0.30, delay="lead")


def all_parts():
    """{piece_part: tune dict} in a stable order, for gen_tables.py (firmware) and the recording scripts."""
    return {f"{p}_{k}": v for p, pc in PIECES.items() for k, v in pc["parts"].items()}
