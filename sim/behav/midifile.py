"""Minimal Standard MIDI File reader (format 0/1): notes with times in quarter notes and seconds, plus the track
names, programs and the tempo map. Enough to turn a MIDI file into TouchSynth parts (see pieces.py)."""
import struct


def _vlq(b, i):
    v = 0
    while True:
        c = b[i]; i += 1
        v = (v << 7) | (c & 0x7F)
        if not c & 0x80:
            return v, i


def read(path):
    """Returns dict(ppq, tempos=[(tick, us_per_quarter)], tracks=[dict(name, notes, programs, channels)]);
    notes = [dict(start, dur, start_s, dur_s, midi, vel, ch)] with start/dur in quarter notes; programs =
    {channel: first program}."""
    b = open(path, "rb").read()
    assert b[:4] == b"MThd", "not a MIDI file"
    hlen, fmt, ntrk, div = struct.unpack(">IHHH", b[4:14])
    assert not div & 0x8000, "SMPTE time division not supported"
    ppq, i = div, 8 + hlen
    raw, tempos = [], []
    for _ in range(ntrk):
        assert b[i:i + 4] == b"MTrk"
        n = struct.unpack(">I", b[i + 4:i + 8])[0]
        j, end, t, status = i + 8, i + 8 + n, 0, 0
        tr = dict(name="", events=[], programs={}, channels=set())
        while j < end:
            dt, j = _vlq(b, j)
            t += dt
            if b[j] & 0x80:
                status = b[j]; j += 1
            if status == 0xFF:                                   # meta
                typ = b[j]; ln, j = _vlq(b, j + 1)
                data = b[j:j + ln]; j += ln
                if typ == 0x51:
                    tempos.append((t, int.from_bytes(data, "big")))
                elif typ == 0x03 and not tr["name"]:
                    tr["name"] = data.decode("latin-1").strip()
                elif typ == 0x2F:
                    break
            elif status in (0xF0, 0xF7):                         # sysex
                ln, j = _vlq(b, j); j += ln
            else:
                hi, ch = status & 0xF0, status & 0x0F
                nd = 1 if hi in (0xC0, 0xD0) else 2
                d = b[j:j + nd]; j += nd
                if hi == 0xC0:
                    tr["programs"].setdefault(ch, d[0])
                elif hi in (0x80, 0x90):
                    on = hi == 0x90 and d[1] > 0
                    tr["events"].append((t, on, d[0], d[1], ch))
                    tr["channels"].add(ch)
        raw.append(tr)
        i = end
    tempos = sorted(tempos) or [(0, 500000)]
    if tempos[0][0] != 0:
        tempos.insert(0, (0, 500000))

    def secs(tick):
        s, (t0, us) = 0.0, tempos[0]
        for t1, us1 in tempos[1:]:
            if t1 >= tick:
                break
            s += (t1 - t0) * us / ppq / 1e6
            t0, us = t1, us1
        return s + (tick - t0) * us / ppq / 1e6

    tracks = []
    for tr in raw:
        notes, open_ = [], {}
        for t, on, m, v, ch in sorted(tr["events"], key=lambda e: (e[0], e[1])):   # offs before ons
            k = (ch, m)
            if k in open_:                                       # note off, or a retrigger ends the old note
                t0, v0 = open_.pop(k)
                notes.append(dict(start=t0 / ppq, dur=(t - t0) / ppq, start_s=secs(t0), dur_s=secs(t) - secs(t0),
                                  midi=m, vel=v0, ch=ch))
            if on:
                open_[k] = (t, v)
        notes.sort(key=lambda n: (n["start"], n["midi"]))
        tracks.append(dict(name=tr["name"], notes=notes, programs=tr["programs"],
                           channels=sorted(tr["channels"])))
    return dict(ppq=ppq, tempos=tempos, tracks=tracks)
