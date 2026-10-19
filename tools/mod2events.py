#!/usr/bin/env python3
"""Tracker module (Amiga ProTracker family .MOD) -> timed note events / standard MIDI file for the TouchSynth Poly.

  python -I mod2events.py info    song.mod                       structure, samples (class, natural pitch), effects, polyphony
  python -I mod2events.py bus     song.mod [--cards 8] [--mode a|b|c] [--resident]    bus load per 1 ms frame against 100 bytes
  python -I mod2events.py events  song.mod -o ev.csv  [same options]                  the bus messages (bus.md types) per card
  python -I mod2events.py midi    song.mod -o song.mid [--grid ms|row] [--tune]       format 1 file, one MIDI channel per card
  python -I mod2events.py patches song.mod -o patches.json                            first-guess synth patch per sample
  python -I mod2events.py samples song.mod -d outdir                                  the samples as 8-bit WAV files

The module is parsed here (plain struct parser, no third-party code; every offset and count is bounds-checked, nothing
in the file is ever executed). `python -I` keeps the interpreter from importing anything from the directory the file
is in. Pure Python 3, no dependencies.

Replayer: tick-accurate ProTracker 2.3 semantics for the effects that matter for the sound: speed / tempo (Fxx),
arpeggio 0xy, slides 1xx 2xx E1x E2x, tone portamento 3xx 5xy, vibrato 4xy 6xy, tremolo 7xy, panning 8xx / E8x,
sample offset 9xx, volume slide Axy, position jump Bxx, set volume Cxx, pattern break Dxx, finetune E5x, pattern loop
E6x, retrigger E9x, fine volume EAx EBx, note cut ECx, note delay EDx, pattern delay EEx, vibrato / tremolo waveforms
E4x E7x. Glissando E3x and funk repeat EFx are ignored. Paula's sample clock is the PAL one (--ntsc selects NTSC); the
period range is the 12-bit field, not Amiga hardware's 113...856, because trackers write periods outside it.

Pipeline (each step is a function that can be used on its own):
  play            module -> Note objects (one per sample start on a Paula channel, with the period and volume it follows
                  tick by tick), and the tick list (speed / tempo)
  allocate        notes -> voice cards. Policies: oldest (the controller's allocator), channel (card groups per MOD channel
                  in pan order: 4 channels on 8 cards = 2 cards per channel, alternating, tails ring on), energy (offline
                  voice reduction by loudness for songs with more channels than cards). plan_residency fixes which
                  patches / stored samples live on which card (4 patch slots, flash per card)
  bus_events      allocated notes -> bus.md messages: PATCH_SELECT / NOTE_ON (pitch in 1/256 semitone) / NOTE_OFF, and the
                  volume and pitch curves as steps (CTRL, PITCH) or as straight segments (CTRL_RAMP, PITCH_RAMP:
                  proposed messages, the card interpolates); mode b / c: NOTE_ON_S plays a sample stored on the card
  schedule        sends them over the 100 bytes per frame bus (earliest deadline first): how late is what, for a look-ahead
  write_midi      the same notes as a standard MIDI file (note + pitch bend + CC 11 + program change per sample)
"""
import argparse, json, math, os, struct, sys, wave
from collections import namedtuple, Counter, defaultdict

PAL_CLOCK = 3546894.6                   # Paula sample clock, Hz (PAL: 7093789.2 / 2)
NTSC_CLOCK = 3579545.0
C2_PERIOD = 428                         # finetune 0 period of "C-2", the reference pitch
PERIODS = [856, 808, 762, 720, 678, 640, 604, 570, 538, 508, 480, 453, 428, 404, 381, 360, 339, 320, 302, 285,
           269, 254, 240, 226, 214, 202, 190, 180, 170, 160, 151, 143, 135, 127, 120, 113]
PMIN, PMAX = 1, 4095                    # the 12-bit period field; Amiga hardware: 113...856, this limit is for trackers that go beyond
FX_NAMES = {0x0: "0 arpeggio", 0x1: "1 slide up", 0x2: "2 slide down", 0x3: "3 tone portamento", 0x4: "4 vibrato",
            0x5: "5 porta+volslide", 0x6: "6 vibrato+volslide", 0x7: "7 tremolo", 0x8: "8 pan", 0x9: "9 sample offset",
            0xA: "A volume slide", 0xB: "B position jump", 0xC: "C set volume", 0xD: "D pattern break",
            0xE: "E extended", 0xF: "F speed/tempo"}
EX_NAMES = {0x0: "E0 filter", 0x1: "E1 fine slide up", 0x2: "E2 fine slide down", 0x3: "E3 glissando",
            0x4: "E4 vib waveform", 0x5: "E5 finetune", 0x6: "E6 pattern loop", 0x7: "E7 trem waveform", 0x8: "E8 pan",
            0x9: "E9 retrigger", 0xA: "EA fine vol up", 0xB: "EB fine vol down", 0xC: "EC note cut", 0xD: "ED note delay",
            0xE: "EE pattern delay", 0xF: "EF funk repeat"}
VIB_SINE = [0, 24, 49, 74, 97, 120, 141, 161, 180, 197, 212, 224, 235, 244, 250, 253,
            255, 253, 250, 244, 235, 224, 212, 197, 180, 161, 141, 120, 97, 74, 49, 24]


class ModError(Exception):
    pass


Sample = namedtuple("Sample", "name length finetune volume loop_start loop_len data")
Mod = namedtuple("Mod", "title tag channels song_length restart orders patterns samples warnings")


def tag_channels(tag):
    """Channel count from the format tag at offset 1080, or None if it is not a known 31-sample tag."""
    if tag in (b"M.K.", b"M!K!", b"FLT4", b"4CHN", b"N.T."):
        return 4
    if tag in (b"OCTA", b"CD81", b"OKTA", b"FLT8"):
        return 8
    if tag[1:4] == b"CHN" and tag[:1].isdigit():
        return int(tag[:1])
    if tag[2:4] in (b"CH", b"CN") and tag[:2].isdigit():
        return int(tag[:2])
    if tag[:3] == b"TDZ" and tag[3:4].isdigit():
        return int(tag[3:4])
    if tag[:2] == b"FA" and tag[2:4].isdigit():
        return int(tag[2:4])
    return None


def parse_mod(data):
    """Parse a 31-sample module. Raises ModError on anything inconsistent; truncated sample data is padded and noted."""
    if len(data) < 1084:
        raise ModError("file shorter than the 1084-byte header")
    tag = bytes(data[1080:1084])
    nch = tag_channels(tag)
    if nch is None or not 1 <= nch <= 32:
        raise ModError("unknown format tag %r (only 31-sample modules are supported)" % tag)
    warnings = []
    title = bytes(data[0:20]).split(b"\0")[0].decode("latin-1")
    song_length = data[950]
    restart = data[951]
    orders = list(data[952:1080])
    if not 1 <= song_length <= 128:
        warnings.append("song length byte %d, using %d" % (song_length, min(max(song_length, 1), 128)))
        song_length = min(max(song_length, 1), 128)
    flt8 = tag == b"FLT8"
    blocks_per_pat = 2 if flt8 else 1
    npat = max(orders) + 1                              # ProTracker counts every order entry, also past the song length
    ncell_blocks = npat * blocks_per_pat
    row_bytes = (4 if flt8 else nch) * 4
    block_size = 64 * row_bytes
    pat_off = 1084
    smp_off = pat_off + ncell_blocks * block_size
    if smp_off > len(data):
        raise ModError("pattern data (%d patterns) runs past the end of the file" % npat)
    patterns = []
    for p in range(npat):
        rows = []
        for r in range(64):
            cells = []
            blocks = (0, 1) if flt8 else (0,)
            for b in blocks:
                base = pat_off + ((p * blocks_per_pat + b) * 64 + r) * row_bytes
                for c in range(row_bytes // 4):
                    b0, b1, b2, b3 = data[base + 4 * c: base + 4 * c + 4]
                    per = ((b0 & 15) << 8) | b1
                    smp = (b0 & 0xF0) | (b2 >> 4)
                    cells.append((per, smp, b2 & 15, b3))
            rows.append(cells)
        patterns.append(rows)
    samples = []
    pos = smp_off
    for i in range(31):
        o = 20 + 30 * i
        name = bytes(data[o:o + 22]).split(b"\0")[0].decode("latin-1")
        ln, ft, vol, ls, ll = struct.unpack(">HBBHH", data[o + 22:o + 30])
        ln *= 2
        ls *= 2
        ll *= 2
        ft = (ft & 15) - 16 if (ft & 15) > 7 else (ft & 15)
        vol = min(vol, 64)
        raw = bytes(data[pos:pos + ln])
        if len(raw) < ln:
            warnings.append("sample %d truncated: %d of %d bytes" % (i + 1, len(raw), ln))
            raw += bytes(ln - len(raw))
        pos += ln
        if ls > ln or ls + ll > ln:                     # inconsistent loop: clamp like the common players
            warnings.append("sample %d loop %d+%d outside length %d, clamped" % (i + 1, ls, ll, ln))
            ls = min(ls, ln)
            ll = max(0, min(ll, ln - ls))
        samples.append(Sample(name, ln, ft, vol, ls, ll, raw))
    if pos < len(data):
        warnings.append("%d trailing bytes after the sample data" % (len(data) - pos))
    return Mod(title, tag.decode("latin-1"), nch if not flt8 else 8, song_length, restart, orders, patterns, samples, warnings)


def load_mod(path):
    with open(path, "rb") as f:
        return parse_mod(f.read(64 * 1024 * 1024))


def sample_loops(s):
    return s.loop_len > 2


# ----------------------------------------------------------------------------------------------- pitch helpers
def period_to_semis(period, base_note=60):
    """Pitch in semitones: C-2 (period 428) = base_note, higher pitch for shorter periods."""
    return base_note + 12.0 * math.log2(C2_PERIOD / max(period, 1.0))


def period_to_pitch256(period, base_note=60):
    return int(round(period_to_semis(period, base_note) * 256))


def finetune_period(period, ft):
    """Period of the same note at finetune ft (-8...7): one finetune step is 1/8 semitone (ProTracker's table to +-1)."""
    if ft == 0:
        return period
    return int(round(period * 2.0 ** (-ft / 96.0)))


def clampp(p):
    return PMIN if p < PMIN else PMAX if p > PMAX else p


# ----------------------------------------------------------------------------------------------- replayer
class Note:
    """One sample start on a Paula channel, followed tick by tick until it is cut, replaced, finished or silent."""
    __slots__ = ("ch", "sample", "t_on", "t_end", "reason", "period0", "vol0", "offset", "series", "pan0", "t_quiet",
                 "order", "row", "looped", "pos_end", "t_natural")

    def __init__(self, ch, sample, t, period, vol, offset, pan, order, row):
        self.ch, self.sample, self.t_on, self.period0, self.vol0, self.offset, self.pan0 = ch, sample, t, period, vol, offset, pan
        self.t_end = None
        self.t_quiet = None                              # one-shot: time its data falls below the audibility threshold
        self.reason = ""
        self.series = []                                 # (t, period, volume, pan) whenever one of them changes
        self.order, self.row = order, row
        self.looped = False
        self.pos_end = 0.0                                # sample position (bytes) when the note ended
        self.t_natural = None                             # one-shot cut by a retrigger: when it would have finished or faded out


class Chan:
    def __init__(self, pan):
        self.sample = 0; self.vol = 0; self.ft = 0; self.period = 0; self.target = 0
        self.porta = 0; self.vspeed = 0; self.vdepth = 0; self.vpos = 0; self.tspeed = 0; self.tdepth = 0; self.tpos = 0
        self.vwave = 0; self.twave = 0; self.offmem = 0; self.loop_row = 0; self.loop_cnt = 0
        self.pan = pan; self.note = None; self.pos = 0.0; self.arp = (0, 0); self.eff = 0; self.par = 0
        self.dper = 0; self.dsample = 0; self.last = None; self.fine_vol = 0


def _wave(kind, pos):
    """Vibrato / tremolo waveform value (-255...255): sine, ramp down, square."""
    p = pos & 31
    k = kind & 3
    if k == 0:
        v = VIB_SINE[p]
    elif k == 1:
        v = 255 - p * 8 if pos & 32 == 0 else p * 8
    else:
        v = 255
    return -v if pos & 32 else v


def quiet_length(s, thr_db=-48.0, win=64):
    """Bytes of a sample until its windowed peak falls below thr_db re its maximum (audible length of a one-shot)."""
    d = s.data
    if not d:
        return 0
    mag = [abs(b - 256 if b > 127 else b) for b in d]
    peak = max(mag)
    if peak == 0:
        return 0
    thr = peak * 10 ** (thr_db / 20.0)
    last = 0
    for i in range(0, len(mag), win):
        if max(mag[i:i + win]) >= thr:
            last = min(len(mag), i + win)
    return last


def play(mod, clock=PAL_CLOCK, max_seconds=1800.0, quiet_db=-48.0, start_order=0):
    """Run the replayer. Returns (notes, ticks, stats). ticks: list of (t, order, row, tick, speed, tempo, row_index)."""
    n = mod.channels
    chs = [Chan(0 if (i % 4) in (0, 3) else 255) for i in range(n)]    # Amiga L R R L, overridden by 8xx / E8x
    quiet = [quiet_length(s, quiet_db) for s in mod.samples]
    notes, ticks = [], []
    stats = {"speed": Counter(), "tempo": Counter(), "rows": 0, "stop": "", "tempo_changes": 0, "speed_changes": 0,
             "loops": 0, "breaks": 0, "jumps": 0, "pattern_delay": 0}
    speed, tempo = 6, 125
    order, row, t, row_idx = start_order, 0, 0.0, 0
    visited = set()

    def smp_of(i):
        return mod.samples[i - 1] if 1 <= i <= 31 else None

    def close(ch, t_end, reason):
        nt = ch.note
        if nt is not None:
            nt.t_end, nt.reason = t_end, reason
            nt.pos_end = ch.pos
            smp = mod.samples[nt.sample - 1]
            if reason == "retrig" and not sample_loops(smp) and ch.period:
                q = quiet[nt.sample - 1]
                nt.t_natural = t_end + max(0.0, (min(q, smp.length) - ch.pos) / (clock / ch.period))
            ch.note = None

    def trigger(ch, ci, t0, per):
        s = smp_of(ch.sample)
        close(ch, t0, "retrig")
        if s is None or s.length == 0:
            return
        ch.period = per
        ch.pos = 0.0
        if ch.vwave & 4 == 0:
            ch.vpos = 0
        if ch.twave & 4 == 0:
            ch.tpos = 0
        nt = Note(ci, ch.sample, t0, per, ch.vol, 0, ch.pan, order, row)
        nt.looped = sample_loops(s)
        ch.note = nt
        notes.append(nt)

    def eff_values(ch, tick):
        """Effective period and volume of this tick (arpeggio, vibrato, tremolo applied)."""
        p = ch.period
        e, par = ch.eff, ch.par
        if e == 0 and par:
            k = tick % 3
            semi = 0 if k == 0 else (par >> 4 if k == 1 else par & 15)
            if semi:
                p = p * 2.0 ** (-semi / 12.0)
        v = ch.vol
        if e in (4, 6):
            d = (_wave(ch.vwave, ch.vpos) * ch.vdepth) >> 7
            p = p + d
        if e == 7:
            v = v + ((_wave(ch.twave, ch.tpos) * ch.tdepth) >> 6)
        return max(1.0, p), max(0, min(64, v))

    while True:
        if order >= mod.song_length or order >= len(mod.orders):
            stats["stop"] = "end of order list"
            break
        pidx = mod.orders[order]
        if pidx >= len(mod.patterns):
            stats["stop"] = "order refers to a missing pattern"
            break
        pat = mod.patterns[pidx]
        key = (order, row)
        if key in visited and not any(c.loop_cnt > 0 for c in chs):
            stats["stop"] = "song loops back to order %d row %d" % key
            break
        visited.add(key)
        cells = pat[row]
        jump_order = None
        break_row = None
        loop_to = None
        pdelay = 0
        # ---- tick 0: notes and effects
        for ci, ch in enumerate(chs):
            per, smp, eff, par = cells[ci]
            x, y = par >> 4, par & 15
            s_new = smp_of(smp) if smp else None
            if smp and s_new is not None:
                ch.sample = smp
                ch.vol = s_new.volume
            ch.eff, ch.par = eff, par
            delayed = eff == 0xE and x == 0xD and y > 0
            if per:
                per_a = clampp(finetune_period(per, ch.ft if ch.ft else (smp_of(ch.sample).finetune if smp_of(ch.sample) else 0)))
                if eff in (3, 5):
                    ch.target = per_a
                    if ch.note is None and ch.period == 0:
                        ch.period = per_a
                elif delayed:
                    ch.dper, ch.dsample = per_a, ch.sample
                else:
                    trigger(ch, ci, t, per_a)
            if eff == 3 and par:
                ch.porta = par
            elif eff in (4, 6) or eff == 7:
                if eff == 4:
                    if x: ch.vspeed = x
                    if y: ch.vdepth = y
                elif eff == 7:
                    if x: ch.tspeed = x
                    if y: ch.tdepth = y
            elif eff == 8:
                ch.pan = par
            elif eff == 9:
                if par: ch.offmem = par
                off = ch.offmem * 256
                s = smp_of(ch.sample)
                if ch.note is not None and s is not None:
                    if off >= s.length:
                        off = s.loop_start if sample_loops(s) else s.length
                    ch.pos = float(off)
                    ch.note.offset = off
            elif eff == 0xB:
                jump_order = par
            elif eff == 0xC:
                ch.vol = min(par, 64)
                if ch.note is not None and not ch.note.series:
                    ch.note.vol0 = ch.vol
            elif eff == 0xD:
                break_row = x * 10 + y
            elif eff == 0xF:
                if par == 0:
                    stats["stop"] = "F00 stop"
                elif par < 32:
                    speed = par; stats["speed_changes"] += 1
                else:
                    tempo = par; stats["tempo_changes"] += 1
            elif eff == 0xE:
                if x == 1: ch.period = clampp(ch.period - y)
                elif x == 2: ch.period = clampp(ch.period + y)
                elif x == 4: ch.vwave = y
                elif x == 5: ch.ft = y - 16 if y > 7 else y
                elif x == 6:
                    if y == 0:
                        ch.loop_row = row
                    else:
                        if ch.loop_cnt == 0:
                            ch.loop_cnt = y
                        else:
                            ch.loop_cnt -= 1
                        if ch.loop_cnt > 0:
                            loop_to = ch.loop_row
                            stats["loops"] += 1
                elif x == 7: ch.twave = y
                elif x == 8: ch.pan = y * 17
                elif x == 0xA: ch.vol = min(64, ch.vol + y)
                elif x == 0xB: ch.vol = max(0, ch.vol - y)
                elif x == 0xC and y == 0: ch.vol = 0
                elif x == 0xE: pdelay = y
        if stats["stop"]:
            break
        nticks = speed * (1 + pdelay)
        if pdelay:
            stats["pattern_delay"] += 1
        stats["speed"][speed] += 1
        stats["tempo"][tempo] += 1
        for tick in range(nticks):
            tdur = 2.5 / tempo
            if tick > 0:
                for ci, ch in enumerate(chs):
                    e, par = ch.eff, ch.par
                    x, y = par >> 4, par & 15
                    if e == 1: ch.period = clampp(ch.period - par)
                    elif e == 2: ch.period = clampp(ch.period + par)
                    elif e in (3, 5):
                        if ch.target and ch.period:
                            if ch.period > ch.target:
                                ch.period = max(ch.target, ch.period - ch.porta)
                            elif ch.period < ch.target:
                                ch.period = min(ch.target, ch.period + ch.porta)
                    if e in (4, 6): ch.vpos = (ch.vpos + ch.vspeed) & 63
                    if e == 7: ch.tpos = (ch.tpos + ch.tspeed) & 63
                    if e in (5, 6, 0xA):
                        if x: ch.vol = min(64, ch.vol + x)
                        elif y: ch.vol = max(0, ch.vol - y)
                    if e == 0xE:
                        if x == 9 and y and tick % y == 0 and ch.sample:
                            trigger(ch, ci, t, ch.period)
                        elif x == 0xC and tick == y:
                            ch.vol = 0
                        elif x == 0xD and tick == y and ch.dper:
                            ch.sample = ch.dsample
                            s = smp_of(ch.sample)
                            if s is not None:
                                ch.vol = s.volume
                            trigger(ch, ci, t, ch.dper)
                            ch.dper = 0
            ticks.append((t, order, row, tick, speed, tempo, row_idx))
            for ci, ch in enumerate(chs):
                nt = ch.note
                if nt is None:
                    continue
                per_e, vol_e = eff_values(ch, tick)
                state = (round(per_e, 2), vol_e, ch.pan)
                if state != ch.last or not nt.series:
                    if nt.series == [] or nt.series[-1][1:] != state:
                        nt.series.append((t,) + state)
                    ch.last = state
                # advance the sample position over this tick
                s = mod.samples[nt.sample - 1]
                rate = clock / per_e
                adv = rate * tdur
                if sample_loops(s):
                    ch.pos += adv
                    end = s.loop_start + s.loop_len
                    if ch.pos >= end:
                        ch.pos = s.loop_start + (ch.pos - s.loop_start) % s.loop_len
                else:
                    if nt.t_quiet is None and ch.pos + adv >= quiet[nt.sample - 1] and quiet[nt.sample - 1] < s.length:
                        nt.t_quiet = t + max(0.0, (quiet[nt.sample - 1] - ch.pos) / rate)
                    if ch.pos + adv >= s.length:
                        t_e = t + max(0.0, (s.length - ch.pos) / rate)
                        ch.pos = float(s.length)
                        close(ch, t_e, "end")
                        ch.last = None
                        continue
                    ch.pos += adv
            t += tdur
            if t > max_seconds:
                stats["stop"] = "time limit"
                break
        if stats["stop"]:
            break
        stats["rows"] += 1
        row_idx += 1
        # ---- next position
        if jump_order is not None or break_row is not None:
            if jump_order is not None:
                stats["jumps"] += 1
            if break_row is not None:
                stats["breaks"] += 1
            order = jump_order if jump_order is not None else order + 1
            row = break_row if break_row is not None else 0
            if row > 63:
                row = 0
        elif loop_to is not None:
            row = loop_to
        else:
            row += 1
            if row >= 64:
                row = 0
                order += 1
    for ch in chs:
        close(ch, t, "song end")
    return notes, ticks, stats


# ----------------------------------------------------------------------------------------------- analysis helpers
def effect_histogram(mod):
    """Per channel Counter of effect names over the cells of the patterns that the order list plays."""
    hist = [Counter() for _ in range(mod.channels)]
    notes = [0] * mod.channels
    lo = [None] * mod.channels
    hi = [None] * mod.channels
    for o in range(mod.song_length):
        p = mod.orders[o]
        if p >= len(mod.patterns):
            continue
        for rowc in mod.patterns[p]:
            for ci, (per, smp, eff, par) in enumerate(rowc):
                if per:
                    notes[ci] += 1
                    lo[ci] = per if lo[ci] is None else min(lo[ci], per)
                    hi[ci] = per if hi[ci] is None else max(hi[ci], per)
                if eff or par:
                    name = EX_NAMES[par >> 4] if eff == 0xE else FX_NAMES[eff]
                    if eff == 0xF:
                        name = "F speed" if par < 32 else "F tempo"
                    hist[ci][name] += 1
    return hist, notes, lo, hi


def polyphony(notes, use_quiet=False, min_vol=1):
    """Maximum number of notes sounding at once, and the time spent at each count. A note counts while its volume > 0."""
    ev = []
    for nt in notes:
        t_end = nt.t_end
        if use_quiet and nt.t_quiet is not None:
            t_end = min(t_end, nt.t_quiet)
        if not nt.series:
            continue
        # intervals with volume >= min_vol
        cur = None
        for (t, p, v, pan) in nt.series:
            if v >= min_vol and cur is None:
                cur = t
            elif v < min_vol and cur is not None:
                ev.append((cur, 1)); ev.append((t, -1)); cur = None
        if cur is not None and t_end > cur:
            ev.append((cur, 1)); ev.append((t_end, -1))
    ev.sort(key=lambda e: (e[0], e[1]))
    cnt, mx, last, hist = 0, 0, 0.0, Counter()
    for t, d in ev:
        hist[cnt] += t - last
        cnt += d
        mx = max(mx, cnt)
        last = t
    return mx, hist


def note_end_time(nt, use_quiet=True, ringout=False, min_vol=1):
    """Time the synth voice for this note is finished: data end, retrigger, the audibility threshold of the data, or the
    first moment its volume falls below min_vol (volume 0 silences the Amiga voice; min_vol 2 or more also frees the
    card for notes that are only a whisper). ringout: a one-shot that the tracker cut by a retrigger on its channel
    rings on to its natural end instead."""
    t_end = nt.t_end
    if ringout and nt.t_natural is not None:
        t_end = max(t_end, nt.t_natural)
    if use_quiet and nt.t_quiet is not None:
        t_end = min(t_end, nt.t_quiet)
    for (t, p, v, pan) in nt.series:
        if v < min_vol and t > nt.t_on:
            return min(t_end, t)
    return t_end


def sample_envelopes(mod, win=256):
    """RMS envelope of every sample in windows of `win` bytes, 1.0 = full scale."""
    envs = {}
    for i, s in enumerate(mod.samples, 1):
        if not s.length:
            continue
        d = [(b - 256 if b > 127 else b) for b in s.data]
        e = []
        for a in range(0, len(d), win):
            seg = d[a:a + win]
            e.append(math.sqrt(sum(x * x for x in seg) / len(seg)) / 128.0)
        envs[i] = e
    return envs


def note_loudness(mod, nt, envs, dt=0.01, win=256, clock=PAL_CLOCK):
    """Loudness of a note on a grid of dt seconds: volume / 64 x the sample's RMS envelope at the playing position.
    Returns (first grid index, list)."""
    s = mod.samples[nt.sample - 1]
    e = envs[nt.sample]
    k0 = int(nt.t_on / dt)
    k1 = int(nt.t_end / dt) + 1
    ser = nt.series
    out = []
    pos = float(nt.offset)
    si = 0
    loops = sample_loops(s)
    for k in range(k0, k1):
        t = (k + 0.5) * dt
        if t >= nt.t_end:
            out.append(0.0)
            continue
        while si + 1 < len(ser) and ser[si + 1][0] <= t:
            si += 1
        per, vol = ser[si][1], ser[si][2]
        pos += clock / per * dt
        if loops and pos >= s.loop_start + s.loop_len:
            pos = s.loop_start + (pos - s.loop_start) % s.loop_len
        wi = int(pos) // win
        out.append(vol / 64.0 * (e[wi] if wi < len(e) else 0.0))
    return k0, out


def allocate(notes, ncards, mod=None, policy="oldest", release=0.05, use_quiet=True, ringout=False, min_vol=1,
             occ_db=-45.0, channels=None, dt=0.01, eligible=None, affinity=True, chan_pan=None, boost=None):
    """Place notes on voice cards. Returns (assignments, stats); assignments: list of (note, card, t_off).

    A card is busy from the note's start until its end plus `release` seconds (the patch's release: a tail rings on
    while the next note takes another card). Policies:
      oldest   the controller's allocator: a free card (the one free longest), else steal the oldest sounding note
      channel  fixed groups: each MOD channel gets cards / channels adjacent slots, channels ranked by their pan (Amiga
               L R R L, or chan_pan 0...255): a 4-channel MOD on 8 cards has two cards per channel at the same stereo
               position, used alternately, so the previous note's tail rings out; with more channels than cards the
               channel number modulo the card count
      energy   offline voice reduction for songs with more voices than cards: a note is kept if the card it takes
               sounds less (remaining loudness energy) than the new note; needs `mod` for the sample envelopes
    eligible(note) -> list of cards the note may use (cards that hold its sample, or a pool of cards for percussion /
    melodic parts); affinity: among free cards prefer one that played the same sample last (its patch is still loaded).
    boost: sample -> priority factor on the loudness (energy policy only) when notes compete for a card: a quiet but
    rhythmically important sample (snare, hat) keeps its card against louder sustained notes (default: none).
    """
    out, st = [], {"notes": 0, "steals": 0, "cut_ms": 0.0, "max_cut_ms": 0.0, "dropped": 0}
    busy = [-1.0] * ncards
    held = [None] * ncards
    last_smp = [0] * ncards
    notes = sorted(notes, key=lambda n: n.t_on)
    nch = channels or (max(n.ch for n in notes) + 1 if notes else 1)
    # channel policy: card slots run left to right (backplane pan), so channels are ranked by their Amiga pan (L R R L ...)
    # and take adjacent slots: a 4-channel MOD on 8 cards gets channel pairs of cards at the same stereo position
    pan_of = chan_pan or [0 if i % 4 in (0, 3) else 255 for i in range(nch)]
    order_by_pan = sorted(range(nch), key=lambda c: (pan_of[c], c))
    rank = {c: i for i, c in enumerate(order_by_pan)}
    if policy == "energy":
        envs = sample_envelopes(mod)
        thr = 10 ** (occ_db / 20.0)

    def pick(free, nt):
        same = [c for c in free if last_smp[c] == nt.sample] if affinity else []
        return min(same or free, key=lambda c: busy[c])

    def place(nt, card, t_off, loud=None):
        last_smp[card] = nt.sample
        busy[card] = t_off + release
        held[card] = (nt, t_off, loud)
        out.append([nt, card, t_off])
        st["notes"] += 1

    def steal(card, t_now):
        old, old_off, _ = held[card]
        cut = max(0.0, old_off - t_now)
        st["steals"] += 1
        st["cut_ms"] += cut * 1000
        st["max_cut_ms"] = max(st["max_cut_ms"], cut * 1000)
        for i in range(len(out) - 1, -1, -1):
            if out[i][0] is old:
                out[i][2] = min(out[i][2], t_now)
                break

    for nt in notes:
        t_off = note_end_time(nt, use_quiet, ringout, min_vol)
        if t_off <= nt.t_on:
            continue
        if eligible is not None:
            cands = eligible(nt)
        elif policy == "channel":
            if ncards >= nch:
                g = ncards // nch
                r = rank[nt.ch % nch]
                cands = list(range(r * g, r * g + g)) + ([c for c in range(nch * g, ncards) if c % nch == nt.ch % nch])
            else:
                cands = [nt.ch % ncards]
        else:
            cands = list(range(ncards))
        if not cands:
            st["dropped"] += 1
            continue
        free = [c for c in cands if busy[c] <= nt.t_on]
        if policy == "energy":
            k0, loud = note_loudness(mod, nt, envs, dt)
            above = [i for i, v in enumerate(loud) if v > thr]
            if not above:
                st["dropped"] += 1
                continue
            t_occ = (k0 + above[-1] + 1) * dt
            t_off = min(t_off, max(t_occ, nt.t_on + dt))
            bs = boost or {}
            e_new = sum(v * v for v in loud) * bs.get(nt.sample, 1.0) ** 2
            free = [c for c in cands if busy[c] <= nt.t_on]
            if free:
                place(nt, pick(free, nt), t_off, (k0, loud))
            else:
                best, best_rem = None, None
                for c in cands:
                    onote, ooff, (ok0, oloud) = held[c]
                    start = max(0, int(nt.t_on / dt) - ok0)
                    rem = sum(v * v for v in oloud[start:]) * bs.get(onote.sample, 1.0) ** 2
                    if best is None or rem < best_rem:
                        best, best_rem = c, rem
                if best_rem >= e_new:
                    st["dropped"] += 1
                    continue
                steal(best, nt.t_on)
                place(nt, best, t_off, (k0, loud))
            continue
        if free:
            card = pick(free, nt)
        else:
            card = min(cands, key=lambda c: held[c][0].t_on)
            steal(card, nt.t_on)
        place(nt, card, t_off)
    kept = [tuple(o) for o in out if o[2] > o[0].t_on + 0.0005]       # a note stolen in the tick it starts never sounds
    st["never_sounded"] = len(out) - len(kept)
    st["notes"] = len(kept)
    return kept, st


def parse_groups(spec):
    """'9,14=3;4,5=4;12=0,1' -> {sample: [cards]}: the samples before '=' may be played by the cards after it."""
    out = {}
    for part in (spec or "").split(";"):
        if not part.strip():
            continue
        smp, cards = part.split("=")
        for x in parse_set(smp):
            out[x] = sorted(parse_set(cards))
    return out


def allocate_paraphonic(notes, ncards, per_card, groups, mod, release=0.05, use_quiet=True, ringout=False, min_vol=1,
                        dt=0.01, boost=None, occ_db=-45.0):
    """Paraphonic cards: every card has `per_card` oscillators (3 on the TouchSynth Poly voice), each plays its own note
    (own pitch, waveform and level envelope; they share the card's filter, VCA and pan). The cards of a group play the
    samples assigned to it, `groups` = {sample: [cards]} (parse_groups); a sample without a group is not played.
    Placement is the `energy` policy over the ncards x per_card oscillator slots, each note limited to the slots of its
    group's cards: a free slot (the one free longest, the one that played the same sample last), else the slot whose
    remaining loudness energy is the smallest (x boost^2) if that is less than the new note's, so notes steal inside the
    group first. Returns (assignments, stats) like `allocate`: assignments are (note, card, t_off); stats['osc'] is the
    oscillator index of each assignment (same order), stats['max_per_card'] the most notes that sound on one card at once."""
    slots = ncards * per_card
    elig = lambda nt: [c * per_card + o for c in groups.get(nt.sample, []) for o in range(per_card)]
    assign, st = allocate(notes, slots, mod, "energy", release, use_quiet, ringout, min_vol, occ_db=occ_db, dt=dt,
                          eligible=elig, boost=boost)
    out, osc = [], []
    for nt, slot, t_off in assign:
        out.append((nt, slot // per_card, t_off))
        osc.append(slot % per_card)
    ev = []
    for (nt, card, t_off) in out:
        ev.append((nt.t_on, 1, card))
        ev.append((t_off, -1, card))
    ev.sort(key=lambda e: (e[0], e[1]))
    cnt, mx = [0] * ncards, [0] * ncards
    for t, d, c in ev:
        cnt[c] += d
        mx[c] = max(mx[c], cnt[c])
    st["osc"] = osc
    st["max_per_card"] = mx
    return out, st


def plan_groups(mod, notes, ncards, per_card, weight=None, release=0.05, pitch_split=40.0):
    """A first guess of `groups` for allocate_paraphonic (--group class): samples with the same class guess
    (sample_stats: tonal looped / textured loop / phrase / percussive ...) and, for the tonal ones, the same register
    (natural pitch below / above `pitch_split`) form a group. Every group gets a card; if there are more groups than
    cards the groups of least energy are merged; left over cards go to the groups whose simultaneous notes (95th
    percentile, in oscillator slots) exceed their card slots, the loudest first. A role split (organ against pad
    against lead) needs the explicit form, the converter cannot tell them apart from the samples alone."""
    st = sample_stats(mod, notes)
    key = {}
    for i, d in st.items():
        if d["uses"] == 0:
            continue
        if d["cls"] in ("tonal looped", "tonal one-shot"):
            key[i] = (d["cls"], "low" if (d["pitch"] if d["pitch"] is not None else 60) < pitch_split else "high")
        else:
            key[i] = (d["cls"], "")
    if weight is None:
        envs = sample_envelopes(mod)
        weight = Counter()
        for nt in notes:
            if nt.series:
                weight[nt.sample] += sum(v * v for v in note_loudness(mod, nt, envs)[1])
    gw = Counter()
    for i, k in key.items():
        gw[k] += weight[i]
    members = {k: [k] for k in gw}
    while len(members) > ncards:                          # merge the two groups of least energy
        a, b = sorted(members, key=lambda k: gw[k])[:2]
        members[a] += members.pop(b)
        gw[a] += gw[b]
    owner = {k: g for g, ks in members.items() for k in ks}
    # slot demand of each group: simultaneous notes (95th percentile of the time they sound)
    need = {}
    for g in members:
        ev = []
        for nt in notes:
            if nt.sample in key and owner[key[nt.sample]] == g and nt.series:
                ev += [(nt.t_on, 1), (note_end_time(nt) + release, -1)]
        ev.sort()
        c, last, hist = 0, 0.0, Counter()
        for t, d in ev:
            hist[c] += t - last
            c += d
            last = t
        tot, acc = sum(hist.values()) or 1.0, 0.0
        need[g] = 1
        for n in sorted(hist):
            acc += hist[n]
            if acc >= 0.95 * tot:
                need[g] = max(1, n)
                break
    cards = {g: 1 for g in members}
    free = ncards - len(members)
    while free > 0:
        g = max(members, key=lambda g: gw[g] if cards[g] * per_card < need[g] else -1.0)
        if cards[g] * per_card >= need[g]:
            break
        cards[g] += 1
        free -= 1
    out, nxt = {}, 0
    for g in sorted(members, key=lambda g: -gw[g]):
        cs = list(range(nxt, nxt + cards[g]))
        nxt += cards[g]
        for k in members[g]:
            for i in key:
                if key[i] == k:
                    out[i] = cs
    return out


def loudness_energy(mod, notes, assign=None, dt=0.01, envs=None, t_from=None, t_to=None):
    """Loudness energy (sum of the squared loudness grid, note_loudness) of all `notes`, and of what the assigned notes
    play until their t_off (assign: (note, card, t_off) tuples; None: only the total). Returns (total, kept) with
    per-sample dictionaries {sample: energy}; t_from / t_to restrict the grid to a time window."""
    envs = envs or sample_envelopes(mod)
    lim = lambda k: (t_from is None or (k + 0.5) * dt >= t_from) and (t_to is None or (k + 0.5) * dt < t_to)
    tot, kept = Counter(), Counter()
    for nt in notes:
        if nt.series:
            k0, loud = note_loudness(mod, nt, envs, dt)
            tot[nt.sample] += sum(v * v for j, v in enumerate(loud) if lim(k0 + j))
    for nt, card, t_off in (assign or []):
        k0, loud = note_loudness(mod, nt, envs, dt)
        kept[nt.sample] += sum(v * v for j, v in enumerate(loud) if lim(k0 + j) and (k0 + j + 0.5) * dt < t_off)
    return tot, kept


# ----------------------------------------------------------------------------------------------- residency
def used_bytes(mod, notes):
    """Bytes of every sample that the song plays (up to the furthest position any note reaches; loops complete)."""
    ue = {}
    for nt in notes:
        ue[nt.sample] = max(ue.get(nt.sample, 0), int(nt.pos_end))
    out = {}
    for i, smp in enumerate(mod.samples, 1):
        if i in ue:
            n = ue[i]
            if sample_loops(smp):
                n = max(n, smp.loop_start + smp.loop_len)
            out[i] = min(n, smp.length)
    return out


def sample_overlap(notes, q=0.99, release=0.05, min_vol=4):
    """Number of notes of the same sample that sound at once (the q quantile of the time): how many cards need it."""
    by = defaultdict(list)
    for nt in notes:
        te = note_end_time(nt, True, False, min_vol) + release
        if te > nt.t_on:
            by[nt.sample] += [(nt.t_on, 1), (te, -1)]
    out = {}
    for smp, ev in by.items():
        ev.sort(key=lambda e: (e[0], e[1]))
        c, last, hist = 0, 0.0, Counter()
        for t, d in ev:
            hist[c] += t - last
            last = t
            c += d
        tot, acc = sum(hist.values()), 0.0
        for k in sorted(hist):
            acc += hist[k]
            if acc >= q * tot:
                out[smp] = max(1, k)
                break
    return out


def plan_residency(mod, notes, ncards, slots=4, sampled=(), bits=4, flash_cap=40 * 1024, cmax=4, weight=None):
    """Which patches (and, for the `sampled` ones, which stored samples) live on which card, so that a card never has
    to load a patch while playing: at most `slots` patches per card (the 4 patch slots), the sampled ones also within
    `flash_cap` bytes at `bits` bits per sample. A sample that often sounds several times at once gets copies on
    several cards (up to cmax), the next copy always going where it gains most. weight: sample -> loudness energy
    (default: the summed squared loudness of its notes). Returns (cards, copies, flash bytes per card, unplaced samples)."""
    ub = used_bytes(mod, notes)
    ov = sample_overlap(notes)
    if weight is None:                                  # loudness energy of every sample over the song
        envs = sample_envelopes(mod)
        weight = Counter()
        for nt in notes:
            if nt.series:
                weight[nt.sample] += sum(v * v for v in note_loudness(mod, nt, envs)[1])
    smps = sorted(ub)
    copies = {x: 1 for x in smps}
    while sum(copies.values()) < slots * ncards:
        best, bg = None, 0.0
        for x in smps:
            if copies[x] >= min(cmax, ov.get(x, 1)):
                continue
            g = weight[x] * (1.0 / copies[x] - 1.0 / (copies[x] + 1))
            if best is None or g > bg:
                best, bg = x, g
        if best is None:
            break
        copies[best] += 1
    cards = [set() for _ in range(ncards)]
    load, fl, unplaced = [0.0] * ncards, [0] * ncards, []
    for x in sorted(smps, key=lambda x: -weight[x] / copies[x]):
        sz = int(ub[x] * bits / 8) if x in sampled else 0
        for _ in range(copies[x]):
            cand = [c for c in range(ncards) if x not in cards[c] and len(cards[c]) < slots and fl[c] + sz <= flash_cap]
            if not cand:
                unplaced.append(x)
                continue
            c = min(cand, key=lambda c: load[c])
            cards[c].add(x)
            load[c] += weight[x] / copies[x]
            fl[c] += sz
    return cards, copies, fl, unplaced


# ----------------------------------------------------------------------------------------------- bus events
# Encoded sizes (bus.md 5.3): COBS adds one byte, the 0x00 delimiter another: dst type frame payload crc8 + 2.
def packet_size(payload):
    return 2 + 3 + payload + 1


MSG = {"NOTE_ON": packet_size(4), "NOTE_ON_S": packet_size(4 + 3),  # NOTE_ON + sample u8 + start offset u16 (proposal)
       "NOTE_OFF": packet_size(1), "PITCH": packet_size(2), "CTRL": packet_size(3), "PARAM": packet_size(3),
       "PATCH_SELECT": packet_size(1), "FRAME": 7,
       "CTRL_RAMP": packet_size(5),                      # proposal: CTRL id, value, ramp time u16 ms (the card interpolates)
       "PITCH_RAMP": packet_size(4)}                     # proposal: target pitch, ramp time u16 ms (linear in semitones)
PAN_PARAM = 80                                          # proposal: per-card pan (the S13 pan stage), i16 -128...127

BusEv = namedtuple("BusEv", "frame card type a b c")


def to_midi_vel(vol):
    return max(1, min(127, int(round(vol * 127 / 64))))


def simplify(points, tol):
    """Douglas-Peucker: the fewest (t, v) points whose straight lines stay within tol of every input point."""
    n = len(points)
    if n <= 2:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        t0, v0 = points[i]
        t1, v1 = points[j]
        worst, wk = -1.0, -1
        for k in range(i + 1, j):
            tk, vk = points[k]
            ve = v0 + (v1 - v0) * (tk - t0) / (t1 - t0) if t1 > t0 else v0
            d = abs(vk - ve)
            if d > worst:
                worst, wk = d, k
        if worst > tol:
            keep[wk] = True
            stack.append((i, wk))
            stack.append((wk, j))
    return [p for p, k in zip(points, keep) if k]


def bus_events(assign, base_note=60, pitch_eps=3, mode="a", ramp=True, vol_tol=1.0, pitch_tol=6.0, pan=True,
               sample_patch=None, pitch_offset=None, sampled=()):
    """Bus messages for the allocated notes. mode 'a': synth patch per sample (PATCH_SELECT + NOTE_ON), mode 'b':
    sample playback (NOTE_ON_S with sample and start offset), mode 'c': the samples in `sampled` as in 'b', the others as
    in 'a'. Volume goes to CTRL 3 (expression), pitch to PITCH.
    ramp=False: every change is a step event (CTRL / PITCH, the messages of bus.md). ramp=True: the volume and pitch
    curves are reduced to straight segments (vol_tol in volume steps of 64, pitch_tol in 1/256 semitone) and sent as
    CTRL_RAMP / PITCH_RAMP: the card interpolates (proposed messages). pitch_offset: semitone offset per sample."""
    evs = []
    off = pitch_offset or {}

    def p256(per, smp):
        return period_to_pitch256(per, base_note) + int(round(off.get(smp, 0.0) * 256))      # smp 0: no offset (sample playback)

    for nt, card, t_off in assign:
        f0 = int(round(nt.t_on * 1000))
        sr = [x for x in nt.series if x[0] < t_off] or nt.series[:1]
        as_sample = mode == "b" or (mode == "c" and nt.sample in sampled)
        if not as_sample:
            evs.append(BusEv(f0, card, "PATCH_SELECT", sample_patch.get(nt.sample, nt.sample) if sample_patch else nt.sample, 0, 0))
        per0 = sr[0][1] if sr else nt.period0
        evs.append(BusEv(f0, card, "NOTE_ON_S" if as_sample else "NOTE_ON", p256(per0, nt.sample if not as_sample else 0),
                         to_midi_vel(nt.vol0), nt.sample if as_sample else 0))
        pp = [(x[0] * 1000.0, p256(x[1], 0 if as_sample else nt.sample)) for x in sr]
        vp = [(x[0] * 1000.0, float(x[2])) for x in sr]
        if ramp:
            for pts, kind, tol in ((pp, "PITCH_RAMP", pitch_tol), (vp, "CTRL_RAMP", vol_tol)):
                pts = simplify(pts, tol)
                if len(pts) < 2:
                    continue
                if kind == "PITCH_RAMP" and max(abs(p[1] - pts[0][1]) for p in pts) < pitch_eps:
                    continue
                if kind == "CTRL_RAMP" and all(abs(p[1] - pts[0][1]) < 1e-9 for p in pts):
                    continue
                for i in range(len(pts) - 1):
                    tr = max(1, int(round(pts[i + 1][0] - pts[i][0])))
                    if kind == "PITCH_RAMP":
                        evs.append(BusEv(int(round(pts[i][0])), card, kind, int(pts[i + 1][1]), tr, 0))
                    else:
                        evs.append(BusEv(int(round(pts[i][0])), card, kind, int(round(pts[i + 1][1] * 16383 / 64)), tr, 0))
        else:
            last_p, last_v = pp[0][1], vp[0][1]
            for (t, per, vol, pn) in sr[1:]:
                f = int(round(t * 1000))
                p = p256(per, 0 if as_sample else nt.sample)
                if abs(p - last_p) >= pitch_eps:
                    evs.append(BusEv(f, card, "PITCH", p, 0, 0)); last_p = p
                if vol != last_v:
                    evs.append(BusEv(f, card, "CTRL", 3, int(round(vol * 16383 / 64)), 0)); last_v = vol
        if pan:
            last_pan = sr[0][3]
            for (t, per, vol, pn) in sr[1:]:
                if pn != last_pan:
                    evs.append(BusEv(int(round(t * 1000)), card, "PARAM", PAN_PARAM, pn - 128, 0)); last_pan = pn
        evs.append(BusEv(int(round(t_off * 1000)), card, "NOTE_OFF", 0, 0, 0))
    evs.sort(key=lambda e: (e.frame, e.card))
    return evs


def bus_load(evs):
    """Bytes per 1 ms frame (FRAME packet included) of the messages at their execution frames: (list, dict frame -> bytes)."""
    per = defaultdict(int)
    for e in evs:
        per[e.frame] += MSG[e.type]
    if not per:
        return [], per
    last = max(per)
    return [MSG["FRAME"] + per.get(f, 0) for f in range(last + 1)], per


def schedule(evs, horizon, lead=2, cap=100 - MSG["FRAME"]):
    """Send the events over the bus, earliest deadline first, `cap` bytes per frame after the FRAME packet. An event for
    execution frame d must be on the wire by d - lead; it becomes known `horizon` frames before d (horizon = lead: live
    MIDI with no look-ahead; 32: a player that sends ahead, the most the cards accept). Returns how much later than
    d - lead the last byte of each event went out (frames): count, late events, maximum, 99th percentile."""
    import heapq
    pend = sorted(evs, key=lambda e: e.frame)
    heap, i, seq, late, inflight = [], 0, 0, [], None
    f = (pend[0].frame - horizon) if pend else 0
    while i < len(pend) or heap or inflight:
        while i < len(pend) and pend[i].frame - horizon <= f:
            heapq.heappush(heap, (pend[i].frame, seq, MSG[pend[i].type]))
            seq += 1
            i += 1
        room = cap
        while room > 0:
            if inflight is None:
                if not heap:
                    break
                d, _, size = heapq.heappop(heap)
                inflight = [d, size]
            take = min(room, inflight[1])
            inflight[1] -= take
            room -= take
            if inflight[1] == 0:
                late.append(max(0, f - (inflight[0] - lead)))
                inflight = None
        if not heap and inflight is None and i < len(pend):
            f = max(f + 1, pend[i].frame - horizon)
        else:
            f += 1
    late.sort()
    n = len(late)
    return {"events": n, "late_events": sum(1 for x in late if x > 0), "max_late_frames": late[-1] if late else 0,
            "p99_late_frames": late[int(0.99 * (n - 1))] if late else 0}


# ----------------------------------------------------------------------------------------------- MIDI file
def vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def midi_track(events):
    """events: list of (tick, order, bytes). Returns the MTrk chunk."""
    events = sorted(events, key=lambda e: (e[0], e[1]))
    out, last = bytearray(), 0
    for tick, _, data in events:
        out += vlq(tick - last) + data
        last = tick
    out += vlq(0) + b"\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(out)) + bytes(out)


def write_midi(path, assign, ticks, ncards, grid="ms", base_note=60, bend_range=12, pitch_eps=3,
               pitch_offset=None, rows_per_beat=4):
    """Format 1 file: a tempo track and one track per card (MIDI channel = card, 0-15, drum samples on channel 10 of a
    track of their own when drum_samples is given). Pitch: note on at the nearest semitone, pitch bend (range
    +-bend_range semitones, set by RPN 0) carries the rest and all slides / vibrato / arpeggio. Volume: velocity at the
    note on, CC 11 afterwards. Program change = sample number - 1 (the patch). pitch_offset: semitones per sample
    (see pitch_offsets). grid 'row': 24 MIDI ticks per row, rows_per_beat rows per beat, tempo events follow the
    song's speed and tempo."""
    off = pitch_offset or {}
    if grid == "ms":
        ppq = 500                                        # 120 BPM: one MIDI tick = 1 ms
        def at(t, tick_hint=None): return int(round(t * 1000))
        tempo_events = [(0, 0, b"\xFF\x51\x03" + (500000).to_bytes(3, "big"))]
    else:
        ppq = 24 * rows_per_beat                         # 24 MIDI ticks per row
        rowpos = []                                      # (t, row_index + fraction) for interpolation
        for (t, o, r, tk, sp, tp, ri) in ticks:
            rowpos.append((t, ri + tk / sp, sp, tp))
        tempo_events = []
        last = None
        for (t, mt, sp, tp) in rowpos:
            if (sp, tp) != last:
                bpm = 24.0 * tp / (rows_per_beat * sp)
                tempo_events.append((int(round(mt * 24)), 0, b"\xFF\x51\x03" + int(round(60e6 / bpm)).to_bytes(3, "big")))
                last = (sp, tp)
        ts = [r[0] for r in rowpos]
        import bisect
        def at(t, tick_hint=None):
            i = max(0, bisect.bisect_right(ts, t) - 1)
            t0, mt, sp, tp = rowpos[i]
            return int(round((mt + (t - t0) / (2.5 / tp) / sp) * 24))
    tracks = [midi_track(tempo_events + [(0, 1, b"\xFF\x03" + bytes([len(b"tempo")]) + b"tempo")])]
    per_card = defaultdict(list)
    for nt, card, t_off in assign:
        per_card[card].append((nt, t_off))
    bend_unit = 8192.0 / (bend_range * 256.0)
    for card in sorted(per_card):
        ch = card % 16
        ev = [(0, 0, b"\xFF\x03" + bytes([len(("card %d" % card).encode())]) + ("card %d" % card).encode()),
              (0, 1, bytes([0xB0 | ch, 101, 0])), (0, 1, bytes([0xB0 | ch, 100, 0])),        # RPN 0: pitch bend range
              (0, 1, bytes([0xB0 | ch, 6, bend_range])), (0, 1, bytes([0xB0 | ch, 38, 0]))]
        lst = sorted(per_card[card], key=lambda x: x[0].t_on)
        cur_prog = None
        for nt, t_off in lst:
            tk_on = at(nt.t_on)
            tk_off = max(tk_on + 1, at(t_off))
            def pq(per, smp=nt.sample):
                return period_to_pitch256(per, base_note) + int(round(off.get(smp, 0.0) * 256))
            p256 = pq(nt.series[0][1] if nt.series else nt.period0)
            key = max(0, min(127, int(round(p256 / 256.0))))
            if nt.sample - 1 != cur_prog:
                ev.append((tk_on, 2, bytes([0xC0 | ch, (nt.sample - 1) & 127])))
                cur_prog = nt.sample - 1
            bend0 = int(round((p256 - key * 256) * bend_unit)) + 8192
            ev.append((tk_on, 3, bytes([0xE0 | ch, bend0 & 127, (bend0 >> 7) & 127])))
            ev.append((tk_on, 4, bytes([0xB0 | ch, 11, min(127, int(round((nt.series[0][2] if nt.series else nt.vol0) * 127 / 64)))])))
            ev.append((tk_on, 5, bytes([0x90 | ch, key, to_midi_vel(nt.vol0)])))
            last_b, last_v, last_tk = bend0, None, tk_on
            for (t, per, vol, pn) in nt.series[1:]:
                if t >= t_off:
                    break
                tk = at(t)
                p = pq(per)
                b = max(0, min(16383, int(round((p - key * 256) * bend_unit)) + 8192))
                if abs(b - last_b) * 256 / bend_unit >= pitch_eps and tk >= last_tk:
                    ev.append((tk, 3, bytes([0xE0 | ch, b & 127, (b >> 7) & 127]))); last_b = b
                v = min(127, int(round(vol * 127 / 64)))
                if v != last_v and (last_v is not None or v != min(127, int(round(nt.series[0][2] * 127 / 64)))):
                    ev.append((tk, 4, bytes([0xB0 | ch, 11, v]))); last_v = v
                last_tk = tk
            ev.append((tk_off, 1, bytes([0x80 | ch, key, 0])))
        tracks.append(midi_track(ev))
    hdr = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), ppq)
    with open(path, "wb") as f:
        f.write(hdr + b"".join(tracks))


# ----------------------------------------------------------------------------------------------- sample pitch
def detect_pitch(s, window=2048, max_lag=1500):
    """Natural pitch of a looped sample, as a MIDI note (float) when the sample is played at period 428 (C-2), and the
    confidence (normalised autocorrelation peak). Returns (None, 0) for samples without a loop or a periodic loop.
    Method: autocorrelation of the loop (repeated to fill the window) at lags 16...max_lag, the smallest lag within 90 % of
    the best peak (avoids octave-down errors), parabolic refinement."""
    if not sample_loops(s):
        return None, 0.0
    d = [b - 256 if b > 127 else b for b in s.data[s.loop_start:s.loop_start + s.loop_len]]
    if len(d) < 32:
        return None, 0.0
    reps = d * (window // len(d) + 2)
    seg = reps[:window + max_lag + 2]
    mean = sum(seg[:window]) / window
    seg = [x - mean for x in seg]
    e0 = sum(x * x for x in seg[:window:2]) or 1.0
    lags = range(16, min(max_lag, window // 2))
    ac = {}
    for lag in lags:
        ac[lag] = sum(seg[i] * seg[i + lag] for i in range(0, window, 2)) / e0
    best = max(ac.values())
    if best < 0.5:
        return None, best
    peaks = [k for k in lags if k > 16 and k + 1 in ac and ac[k] >= ac[k - 1] and ac[k] >= ac[k + 1] and ac[k] >= 0.9 * best]
    if not peaks:
        return None, best
    k = peaks[0]
    a, b, c = ac[k - 1], ac[k], ac[k + 1]
    den = a - 2 * b + c
    period = k + ((a - c) / (2 * den) if den else 0.0)
    f = PAL_CLOCK / C2_PERIOD / period
    return 69.0 + 12.0 * math.log2(f / 440.0), b


def pitch_offsets(mod, base_note=60, min_conf=0.75):
    """Semitone offset per sample so that period 428 sounds at the sample's natural pitch (looped, periodic samples
    only; the others stay at base_note). Used by the synth-patch mapping, where an oscillator must sound at the pitch
    the tracker sample really has, not at the note name written in the pattern."""
    out = {}
    for i, smp in enumerate(mod.samples, 1):
        m, conf = detect_pitch(smp)
        if m is not None and conf >= min_conf:
            out[i] = round((m - base_note) * 20) / 20.0         # 5 cent steps hide the detector's noise
    return out


# ----------------------------------------------------------------------------------------------- sample analysis
def count_onsets(s, rate, smooth=0.008, gap=0.06):
    """Number of separate hits in a one-shot: peaks of the rectified, smoothed envelope that rise above 35 % of the
    maximum after a dip below 50 % of the peak before them, at least `gap` seconds apart (a drum loop has several)."""
    d = [abs(b - 256 if b > 127 else b) for b in s.data]
    w = max(1, int(smooth * rate))
    env = [sum(d[i:i + w]) / w for i in range(0, len(d), w)]
    if not env:
        return 0
    top = max(env) or 1.0
    hits, last_t, valley = 0, -1e9, True
    peak_v, peak_i = 0.0, 0
    for i, v in enumerate(env):
        if valley and v > 0.35 * top:
            valley, peak_v, peak_i = False, v, i
        elif not valley:
            if v > peak_v:
                peak_v, peak_i = v, i
            elif v < 0.5 * peak_v:
                if (peak_i * w) / rate - last_t >= gap:
                    hits += 1
                    last_t = (peak_i * w) / rate
                valley = True
    if not valley and (peak_i * w) / rate - last_t >= gap:
        hits += 1
    return hits


def sample_stats(mod, notes):
    """Per sample: usage, pitch span, durations at the rate it is played, loop, class guess:
    'tonal looped' (periodic loop: an oscillator patch or a stored cycle), 'textured loop' (looped, not periodic),
    'phrase' (a one-shot with several hits: a drum loop; only sample playback reproduces it), 'percussive' (one hit)."""
    use = defaultdict(list)
    for nt in notes:
        use[nt.sample].append(nt)
    out = {}
    for i, s in enumerate(mod.samples, 1):
        if s.length == 0:
            continue
        ns = use.get(i, [])
        periods = Counter(round(n.period0) for n in ns)
        moved = sum(1 for n in ns if len({round(x[1]) for x in n.series}) > 1)
        d = sorted(note_end_time(n) - n.t_on for n in ns)
        med_per = sorted(n.period0 for n in ns)[len(ns) // 2] if ns else C2_PERIOD
        rate = PAL_CLOCK / med_per
        dur = s.length / rate
        hits = 0 if sample_loops(s) else count_onsets(s, rate)
        pm, pconf = detect_pitch(s)
        if not ns:
            cls = "unused"
        elif sample_loops(s):
            cls = "tonal looped" if pm is not None and pconf >= 0.75 else "textured loop"
        elif dur >= 0.3 and (hits >= 3 or (hits >= 2 and sample_features(s, rate).get("brightness", 9) < 0.6)):
            cls = "phrase"
        elif len(periods) > 6 and sample_features(s, rate).get("brightness", 9) < 0.7:
            cls = "tonal one-shot"
        else:
            cls = "percussive"
        out[i] = dict(name=s.name, length=s.length, loop=s.loop_len if sample_loops(s) else 0, loop_start=s.loop_start,
                      volume=s.volume, finetune=s.finetune, uses=len(ns), distinct_periods=len(periods),
                      pitch_moving=moved, median_dur=d[len(d) // 2] if d else 0.0, max_dur=d[-1] if d else 0.0,
                      rate=rate, dur=dur, hits=hits, cls=cls, pitch=pm, pitch_conf=pconf,
                      lo=min(periods) if periods else 0, hi=max(periods) if periods else 0)
    return out


def sample_features(s, rate):
    """Cheap descriptors of a sample for the patch heuristic: brightness (mean |dx| / mean |x|; a 4-pole low-pass lowers
    it), attack and decay times (to -20 / -40 dB) at the playing rate, peak."""
    d = [b - 256 if b > 127 else b for b in s.data]
    n = len(d)
    if n < 64:
        return {}
    mag = [abs(x) for x in d]
    mean = sum(mag) / n or 1e-9
    dx = sum(abs(d[i] - d[i - 1]) for i in range(1, n)) / (n - 1)
    win = max(16, int(rate * 0.005))
    env = [max(mag[i:i + win]) for i in range(0, n, win)]
    emax = max(env) or 1
    imax = env.index(emax)

    def t_below(db):
        thr = emax * 10 ** (db / 20)
        for j in range(imax, len(env)):
            if env[j] < thr:
                return (j * win) / rate
        return (len(env) * win) / rate
    return dict(peak=emax, brightness=dx / mean, att=imax * win / rate, t20=t_below(-20), t40=t_below(-40), dur=n / rate)


def guess_patch(i, s, st):
    """First-guess patch (midi.md parameter names) for a sample, from its class and features: a starting point to be
    edited by ear. Phrases (drum loops) get no patch: a synth cannot play them back without splitting them into hits."""
    ft = sample_features(s, st["rate"])
    if not ft:
        return None
    p = {"name": ("S%02d %s" % (i, s.name))[:16], "class": st["cls"]}
    cls, br = st["cls"], ft["brightness"]
    if cls == "phrase":
        p["kind"] = "sample only (multi-hit phrase)"
    elif cls == "tonal looped":
        p.update(ENGINE=0, OSC1_WAVE=1 if br > 0.2 else 2, OSC1_LEVEL=110, OSC2_WAVE=1, OSC2_LEVEL=50, OSC2_FINE=7,
                 CUTOFF=int(min(2560, 900 + 1400 * min(br, 1.0))), RESONANCE=40,
                 AENV_A=int(min(127, 10 + ft["att"] * 120)), AENV_D=60, AENV_S=100, AENV_R=40,
                 tune_semitones=round(st["pitch"] - 60, 2) if st["pitch"] is not None else 0.0, kind="sustained tonal (saw / pulse + ladder)")
    elif cls == "textured loop":
        p.update(ENGINE=0, OSC1_WAVE=1, OSC1_LEVEL=70, NOISE_LEVEL=50, CUTOFF=1500, RESONANCE=30, AENV_A=40, AENV_D=60,
                 AENV_S=110, AENV_R=60, kind="pad / texture (saw + noise, slow attack)")
    elif cls == "tonal one-shot":
        p.update(ENGINE=1, MODAL_MODEL=2, MALLET=int(40 + 40 * (1 - min(br, 1.0))),
                 MODAL_DECAY=int(max(-64, min(63, (ft["t40"] - 0.3) * 60))), kind="plucked / struck tonal (modal)")
    elif br > 1.0:
        p.update(ENGINE=0, NOISE_LEVEL=127, OSC1_WAVE=0, CUTOFF=2400, RESONANCE=20, AENV_A=0,
                 AENV_D=int(30 + ft["t20"] * 120), AENV_S=0, AENV_R=15, kind="hat / cymbal (noise, filter open)")
    elif br > 0.3:
        p.update(ENGINE=1, MODAL_MODEL=1, MALLET=30, MODAL_NOISE=90, MODAL_DECAY=0, kind="snare / clap (modal + noise)")
    else:
        p.update(ENGINE=0, OSC1_WAVE=0, OSC2_WAVE=0, PENV_AMT=24, PENV_DECAY=30, AENV_A=0, AENV_D=int(30 + ft["t20"] * 150),
                 AENV_S=0, AENV_R=10, CUTOFF=700, kind="kick / bass drum (pitch envelope on a sine-like)")
    p["features"] = {k: round(v, 3) for k, v in ft.items()}
    return p


# ----------------------------------------------------------------------------------------------- command line
def parse_set(spec):
    out = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def cmd_info(mod, args, notes, ticks, stats):
    print("title %r  tag %s  channels %d  song length %d  restart %d  patterns %d" %
          (mod.title, mod.tag, mod.channels, mod.song_length, mod.restart, len(mod.patterns)))
    for w in mod.warnings:
        print("warning:", w)
    used = [s for s in mod.samples if s.length]
    print("samples %d, %d bytes (%.1f KiB); plays %.1f s (%s); %d rows, %d notes" %
          (len(used), sum(s.length for s in used), sum(s.length for s in used) / 1024,
           ticks[-1][0] if ticks else 0, stats["stop"], stats["rows"], len(notes)))
    print("speeds", dict(stats["speed"]), "tempos", dict(stats["tempo"]))
    mx, hist = polyphony(notes)
    mq, histq = polyphony(notes, use_quiet=True)
    print("max simultaneous notes: %d (audible, one-shots cut at -48 dB: %d)" % (mx, mq))
    st = sample_stats(mod, notes)
    print("sample  bytes  loop    vol  uses periods  rate Hz  dur s hits pitch  class")
    for i, d in st.items():
        print("%5d %7d %6d %4d %5d %5d %8.0f %6.2f %4d %5s  %s  %r" % (i, d["length"], d["loop"], d["volume"], d["uses"], d["distinct_periods"],
              d["rate"], d["dur"], d["hits"], "%.1f" % d["pitch"] if d["pitch"] is not None else "-", d["cls"], d["name"]))
    hist, nn, lo, hi = effect_histogram(mod)
    for ci in range(mod.channels):
        print("ch%02d notes %5d range %s-%s  %s" % (ci, nn[ci], lo[ci], hi[ci], dict(hist[ci].most_common(8))))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["info", "events", "midi", "bus", "patches", "samples"])
    ap.add_argument("file")
    ap.add_argument("-o", "--out")
    ap.add_argument("-d", "--dir")
    ap.add_argument("--cards", type=int, default=8, help="voice cards the notes are allocated to")
    ap.add_argument("--mode", choices=["a", "b", "c"], default="a",
                    help="a: synth patch per sample, b: sample playback on the card, c: hybrid (--sampled: stored samples, the rest patches)")
    ap.add_argument("--grid", choices=["ms", "row"], default="ms", help="MIDI time base: 1 ms ticks or the song's rows")
    ap.add_argument("--base-note", type=int, default=60, help="MIDI note of C-2 (period 428)")
    ap.add_argument("--tune", action="store_true",
                    help="pitch the looped, periodic samples by their detected natural pitch instead of the note names")
    ap.add_argument("--sampled", default="", help="mode c: sample numbers played from the card's flash, e.g. 1-3,21")
    ap.add_argument("--bits", type=int, default=8, help="bits per stored sample in the flash estimate (8, or 4 with ADPCM)")
    ap.add_argument("--flash", type=int, default=40 * 1024, help="free flash per card for samples (bytes)")
    ap.add_argument("--resident", action="store_true",
                    help="plan which patches / samples live on which card (4 patch slots, flash) and allocate only within that")
    ap.add_argument("--rows-per-beat", type=int, default=4, help="MIDI grid 'row': rows per beat")
    ap.add_argument("--release", type=float, default=0.05, help="patch release time that keeps a card busy after note off (s)")
    ap.add_argument("--policy", choices=["oldest", "channel", "energy"], default="energy",
                    help="voice allocation: oldest (free card, else steal the oldest), channel (card groups per MOD channel, "
                         "alternating), energy (offline reduction by loudness for songs with more channels than cards)")
    ap.add_argument("--boost", default="", help="energy policy: priority factors sample=factor,... (e.g. 19=4,20=3) so quiet "
                    "rhythm samples keep a card against louder notes")
    ap.add_argument("--per-card", type=int, default=1,
                    help="notes per card: 1 (default, one voice per card) or 3 (paraphonic: the card's three oscillators play "
                         "three notes through one filter and VCA; the MIDI / bus output then has one channel per oscillator)")
    ap.add_argument("--group", default="class",
                    help="--per-card > 1: which cards play which samples: 'class' (guess from the sample classes, "
                         "plan_groups) or 'samples=cards;...' e.g. '12=0,1;10,11=2;9,14=3;4,5=4;8=5'")
    ap.add_argument("--steps", action="store_true", help="volume / pitch as CTRL / PITCH steps instead of ramps (bus.md messages only)")
    ap.add_argument("--ringout", action="store_true", help="one-shots cut by a retrigger ring on to their natural end")
    ap.add_argument("--min-vol", type=int, default=1, help="a note whose volume (0-64) falls below this frees its card")
    ap.add_argument("--no-quiet", action="store_true", help="play one-shots to the end of their data")
    ap.add_argument("--ntsc", action="store_true")
    ap.add_argument("--pitch-eps", type=int, default=3, help="smallest pitch change sent (1/256 semitone)")
    args = ap.parse_args()
    mod = load_mod(args.file)
    notes, ticks, stats = play(mod, NTSC_CLOCK if args.ntsc else PAL_CLOCK)
    if args.cmd == "info":
        cmd_info(mod, args, notes, ticks, stats)
        return
    if args.cmd == "samples":
        os.makedirs(args.dir or ".", exist_ok=True)
        for i, s in enumerate(mod.samples, 1):
            if s.length:
                with wave.open(os.path.join(args.dir or ".", "s%02d.wav" % i), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(1); w.setframerate(8363)
                    w.writeframes(bytes((b + 128) & 255 for b in s.data))
        return
    if args.cmd == "patches":
        st = sample_stats(mod, notes)
        out = {i: guess_patch(i, mod.samples[i - 1], st[i]) for i in st}
        text = json.dumps(out, indent=1)
        if args.out:
            open(args.out, "w").write(text)
        else:
            print(text)
        return
    sampled = set(range(1, 32)) if args.mode == "b" else parse_set(args.sampled) if args.mode == "c" else set()
    eligible, plan = None, None
    if args.resident:
        plan = plan_residency(mod, notes, args.cards, 4, sampled, args.bits, args.flash)
        holds = defaultdict(list)
        for c, ss in enumerate(plan[0]):
            for x in ss:
                holds[x].append(c)
        eligible = lambda nt: holds.get(nt.sample, [])
    boost = {int(k): float(v) for k, v in (x.split("=") for x in args.boost.split(",") if x)}
    if args.per_card > 1:
        groups = plan_groups(mod, notes, args.cards, args.per_card) if args.group == "class" else parse_groups(args.group)
        assign, ast = allocate_paraphonic(notes, args.cards, args.per_card, groups, mod, args.release, not args.no_quiet,
                                          args.ringout, args.min_vol, boost=boost)
        # bus / MIDI: one logical voice per oscillator (card * per_card + oscillator), as a card of its own
        assign = [(nt, card * args.per_card + o, t_off) for (nt, card, t_off), o in zip(assign, ast["osc"])]
        args.cards *= args.per_card
        print("paraphonic: groups %s; most notes at once per card %s" % (dict(sorted(groups.items())), ast["max_per_card"]),
              file=sys.stderr)
    else:
        assign, ast = allocate(notes, args.cards, mod, args.policy, args.release, not args.no_quiet, args.ringout, args.min_vol,
                               eligible=eligible, boost=boost)
    if args.cmd == "midi":
        if not args.out:
            ap.error("midi needs -o")
        write_midi(args.out, assign, ticks, args.cards, args.grid, args.base_note, pitch_eps=args.pitch_eps,
                   pitch_offset=pitch_offsets(mod, args.base_note) if args.tune else None, rows_per_beat=args.rows_per_beat)
        print("wrote %s: %d notes on %d cards, %d steals" % (args.out, ast["notes"], args.cards, ast["steals"]))
        return
    evs = bus_events(assign, args.base_note, pitch_eps=args.pitch_eps, mode=args.mode, ramp=not args.steps,
                     pitch_offset=pitch_offsets(mod, args.base_note) if args.tune and args.mode != "b" else None, sampled=sampled)
    if args.cmd == "events":
        lines = ["frame,card,type,a,b,c"] + ["%d,%d,%s,%d,%d,%d" % e for e in evs]
        text = "\n".join(lines) + "\n"
        if args.out:
            open(args.out, "w").write(text)
        else:
            sys.stdout.write(text)
        return
    if args.cmd == "bus":
        load, per = bus_load(evs)
        over = sum(1 for b in load if b > 100)
        print("frames %d, mean %.1f B per frame, max %d B, frames over 100 B: %d" % (len(load), sum(load) / len(load), max(load), over))
        for h in (2, 8, 32):
            r = schedule(evs, h)
            print("look-ahead %2d frames: %d of %d events late, max lateness %d frames, 99th percentile %d" %
                  (h, r["late_events"], r["events"], r["max_late_frames"], r["p99_late_frames"]))
        print("messages", dict(Counter(e.type for e in evs)))
        print("bytes by message", {k: v * MSG[k] for k, v in Counter(e.type for e in evs).items()})
        print("allocation", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in ast.items() if k != "osc"})
        if plan:
            print("resident patches per card", [sorted(c) for c in plan[0]])
            print("flash for stored samples per card (KiB at %d bit)" % args.bits, [round(f / 1024, 1) for f in plan[2]],
                  "unplaced", plan[3])


if __name__ == "__main__":
    main()
