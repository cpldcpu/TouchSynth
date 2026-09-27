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


def to_notes(tune, gate=0.8, t0=0.05):
    """Expand a tune into (t_on, dur, midi, overrides) events for behav.firmware()."""
    p = PRESETS[tune["preset"]]
    s16 = 60.0 / tune["bpm"] / 4
    t, out = t0, []
    for note, ln, fl in tune["steps"]:
        dur = ln * s16
        if note:
            ov = {}
            if "A" in fl:
                ov.update(p.get("accent", {}))
            if "S" in fl:
                ov.update(p.get("slide", dict(glide=0.06)))
            else:
                ov.setdefault("glide", p.get("glide", 0.0) if "S" in fl else 0.0)
            g = 1.0 if "S" in fl else gate
            out.append((t, dur * g, note, ov))
        t += dur
    return out, t + 0.6


def to_c(name, tune):
    """C array for the firmware (note, len, flags)."""
    fl = lambda f: ("1" if "S" in f else "0") + "|" + ("2" if "A" in f else "0")
    body = ",\n    ".join(f"{{{n:3d}, {l:2d}, {fl(f)}}}" for n, l, f in tune["steps"])
    return (f"static const tune_step_t tune_{name}[] = {{\n    {body}\n}};  /* {tune['bpm']} bpm, "
            f"preset {tune['preset']} */\n")
