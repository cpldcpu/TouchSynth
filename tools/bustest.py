#!/usr/bin/env python3
"""Voice bus bench tests (docs/bus.md): the bench controller (firmware/bench_ctrl, CH32V203) and one voice card
(firmware/voice, make BOARD=card BUS_TX_PP=1) on the lab PC. Settings from tools/lab.conf (BENCH_PORT or
LINKE_V203, MINICHLINK, SCOPE_HOST); copy buslib.py, labconf.py, scope.py and lab.conf next to this file.

  python3 bustest.py all                 # enum notes patch ctrl crc repair late config sync reset (no scope)
  python3 bustest.py notes crc           # single tests
  python3 bustest.py counters            # the card's counters, STATUS and the controller's status line
  python3 bustest.py carrier             # scope: the DAC carrier on PC2 with a DAC patch, none without
  python3 bustest.py latency [--n 10] [--delay 4] [--lead 2] [--mark 1]
        scope (CH1 = SYNC, CH2 = PC2, the DAC PWM): the controller shortens the SYNC pulse of the execution frame
        (--mark 1) or of the frame that transmits the event (--mark 2); the scope triggers on that pulse and the
        script measures from its rising edge to the first PWM period of the note (NOTE_ON with phase reset on a DAC
        oscillator patch: the output leaves its constant 50 % duty at once). Expected: D frames (mark 1) or
        L - 1 + D frames (mark 2), plus about one carrier period (5.3 us).
  python3 bustest.py stress [--period 0.0625] [--progs 17,10]
        20 s of notes (each with bend, a cutoff PARAM and a wheel CTRL) as fast as the commands go or one per
        --period seconds, a program change every 100 notes; checks the error counters (rejected SYNC glitches and
        the DAC's load are reported, not checked)
  python3 bustest.py load [--voices 8] [--seconds 10] [--multi] [--prio] [--lead 2] [--parts sizes,refresh,...]
        [2026-10-19] 8 voices with one card: the controller treats voices 1-7 as populated (no answers expected) and
        sends all their traffic; the card is voice 0 and discards the rest (docs/bus.md 9.5). Parts: sizes (packet
        sizes and the expected bytes of the bursts, from the format), refresh (VOICE_STATE / PATCH_DATA rates),
        bursts (a chord of 8, a legato chord change, chords with bend / wheel / cutoff, one command each, one poly
        part and 8 parts), sweep (the controller's generator: chords and controller steps, 10 s each), ramp
        (controller steps on 8 parts every 8 ... 1 frames: the limit), card (the card's CPU per patch: 2 oscillators,
        modal, 3 oscillators, no DAC; no traffic, foreign traffic only, the card as one of the poly voices). Per row:
        the controller's bytes per frame (all, events, refreshes), peak, frames at the budget, late packets (sent too
        late for their execution frame; of them notes and the card's), backlog, generator lag; the card's error
        counters, foreign / own packets, longest tick (without and with the REQUEST replies), parser cycles per tick
        (mean, longest, most bytes), DAC fill_max / slack_min, free stack. Reported, not checked. --multi: per-voice
        records (V_MULTI), --prio: notes ahead of controllers (V_PRIO), --lead: L for the run (restored to 2).
  python3 bustest.py latency --load parts|chord [--cevery 3] [--multi] [--prio] [--lead 2] [--n 10]
        the latency test under load: "parts" -- 7 virtual parts play chords and bend / wheel / cutoff every --cevery
        frames, the card (outside the load) gets the NOTE_ON alone; "chord" -- one poly part over 8 voices, the
        card's note is one of an 8-note chord in one command, controllers on the part. Late events show up as whole
        frames (5, 6 ms instead of 4).

Each test prints PASS / FAIL lines with the numbers it checked; the exit code is the number of failures.
"""
import argparse
import os
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buslib                                            # noqa: E402
import labconf                                           # noqa: E402
try:
    import numpy as np                                   # the scope tests
except ImportError:
    np = None

DAC_PRESET = 23            # lead_dac: saw + sub pulse on the PWM DAC (programs 10, 17-24 use the DAC)
NOTE_PHASE = 2             # NOTE_ON flags bit 1: reset the oscillator phases
MODAL_PRESET = 10          # kettle (modal)
PLAIN_PRESET = 0           # init: no DAC
fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    if not ok:
        fails += 1


def settle(ms=15):
    time.sleep(ms / 1000.0)


def delta(c0, c1, *keys):
    return {k: (c1[k] - c0[k]) & 0xFFFF for k in keys}


# ------------------------------------------------------------------ tests without the scope
def t_enum(b):
    s = b.status()
    h = b.hello()
    st = b.card_status()
    check("enumeration", s.get("enum") == 3 and s.get("card") == 1, f"controller enum state {s.get('enum')} "
          f"(3 = run), card {s.get('card')}, uid {s.get('uid')}")
    check("HELLO", h is not None and h["src"] == 0 and h["uid"] == s.get("uid"), f"{h}")
    check("STATUS", st is not None and st.get("state") == "synced", f"{st}")


def t_notes(b):
    b.refresh(1)
    b.events(0xC0, DAC_PRESET)
    settle()
    c0 = b.counters()
    check("program change", c0["preset"] == DAC_PRESET, f"card preset {c0['preset']}, slot {c0['slot']}")
    b.events(0x90, 60, 100)
    settle()
    c1 = b.counters()
    b.events(0x80, 60, 0)
    settle()
    c2 = b.counters()
    check("note on / off", c1["gate"] == 1 and c2["gate"] == 0, f"gate after NOTE_ON {c1['gate']}, after NOTE_OFF "
          f"{c2['gate']}; {delta(c0, c2, 'packets', 'crc', 'late', 'other')}")
    for n in (48, 55, 60, 67, 72):                       # a short phrase
        b.events(0x90, n, 90)
        time.sleep(0.12)
        b.events(0x80, n, 0)
        time.sleep(0.03)
    c3 = b.counters()
    d = delta(c2, c3, "packets", "crc", "late", "far", "qfull", "slips", "other")
    check("phrase", c3["gate"] == 0 and d["crc"] == 0 and d["late"] == 0 and d["slips"] == 0, f"{d}")


def t_patch(b):
    b.events(0xC0, DAC_PRESET)
    settle()
    a = b.counters()
    b.events(0xC0, MODAL_PRESET)
    settle()
    m = b.counters()
    b.events(0xC0, PLAIN_PRESET)
    settle()
    p = b.counters()
    b.events(0xC0, DAC_PRESET)                           # back to a patch already in a slot: PATCH_SELECT only
    settle()
    a2 = b.counters()
    check("patch slots", (a["preset"], m["preset"], p["preset"], a2["preset"]) ==
          (DAC_PRESET, MODAL_PRESET, PLAIN_PRESET, DAC_PRESET) and a2["slot"] == a["slot"] and
          len({a["slot"], m["slot"], p["slot"]}) == 3,
          f"presets {a['preset']} {m['preset']} {p['preset']} {a2['preset']}, slots {a['slot']} {m['slot']} "
          f"{p['slot']} {a2['slot']}")
    b.events(0xC0, MODAL_PRESET)                          # modal strikes: the tick stages the bank, the renderer
    settle()                                              # starts it at its V_n
    for n in (45, 52, 45):
        b.events(0x90, n, 110)
        settle(150)
        b.events(0x80, n, 0)
    c = b.counters()
    d = delta(a, c, "underruns", "late_ticks")
    check("modal strikes", c["preset"] == MODAL_PRESET and d["late_ticks"] == 0,   # underruns: the CPU budget of
          f"{d}, tick_run_max {c['tick_run_max']} cycles")                         # the DAC patches (bus.md 9.3)
    b.events(0xC0, DAC_PRESET)


def t_crc(b):
    b.refresh(0)
    b.events(0xC0, DAC_PRESET)
    b.events(0x80, 60, 0)
    settle()
    c0 = b.counters()
    note_on = struct.pack("<HBB", 60 << 8, 100, 0)
    b.body(0x01, buslib.NOTE_ON, note_on, lead=2, corrupt=True)
    settle()
    c1 = b.counters()
    b.body(0x01, buslib.NOTE_ON, note_on, lead=2)
    settle()
    c2 = b.counters()
    b.body(0x01, buslib.NOTE_OFF, b"\0", lead=2)
    b.raw(buslib.packet(bytes([0x01, buslib.NOTE_ON, 0]) + note_on)[:-3] + b"\x55\x00")   # cut short, bad CRC
    settle()
    c3 = b.counters()
    d1, d3 = delta(c0, c1, "crc", "packets"), delta(c2, c3, "crc", "framing")
    check("CRC rejection", d1["crc"] == 1 and d1["packets"] >= 0 and c1["gate"] == 0 and c2["gate"] == 1,
          f"corrupted NOTE_ON: crc +{d1['crc']}, gate {c1['gate']}; intact: gate {c2['gate']}")
    check("damaged packet", d3["crc"] + d3["framing"] == 1 and c3["gate"] == 0, f"{d3}, gate {c3['gate']}")
    b.refresh(1)


def t_repair(b):
    b.refresh(1)
    b.events(0x80, 60, 0)
    settle(60)
    b.refresh(0)
    c0 = b.counters()
    b.corrupt(1)                                         # the NOTE_ON is lost (bad CRC) ...
    b.events(0x90, 60, 100)
    settle(30)
    c1 = b.counters()
    b.refresh(1)
    time.sleep(0.12)                                     # ... until the next VOICE_STATE (every 50 frames)
    c2 = b.counters()
    b.events(0x80, 60, 0)
    settle()
    d = delta(c0, c2, "crc", "repairs")
    check("VOICE_STATE repair", c1["gate"] == 0 and c2["gate"] == 1 and d["crc"] == 1 and d["repairs"] == 1,
          f"gate {c1['gate']} after the lost NOTE_ON, {c2['gate']} after the refresh; {d}")


def t_late(b):
    b.refresh(0)
    c0 = b.counters()
    note_on = struct.pack("<HBB", 62 << 8, 100, 0)
    b.body(0x01, buslib.NOTE_ON, note_on, lead=0)        # for the current frame: parsed two ticks too late
    settle()
    c1 = b.counters()
    b.body(0x01, buslib.NOTE_OFF, b"\0", lead=40)        # more than 32 frames ahead: dropped
    settle(60)
    c2 = b.counters()
    b.body(0x01, buslib.NOTE_OFF, b"\0", lead=2)
    settle()
    d = delta(c0, c2, "late", "far")
    check("late / far events", d["late"] == 1 and d["far"] == 1 and c1["gate"] == 1 and c2["gate"] == 1,
          f"{d}, gate {c1['gate']} (late NOTE_ON runs at once), {c2['gate']} (far NOTE_OFF dropped)")
    b.refresh(1)


def t_config(b):
    b.config(6, 2)
    settle()
    c = b.counters()
    b.config(4, 2)
    settle()
    c2 = b.counters()
    check("CONFIG", c["delay"] == 6 and c2["delay"] == 4, f"D {c['delay']} then {c2['delay']}")


def t_sync(b):
    b.refresh(1)
    for gap, lost in ((3, False), (40, True)):
        c0 = b.counters()
        b.sync_gap(gap)
        time.sleep(0.005 + gap / 2000.0)
        mid = b.card_status() if lost else None          # a REQUEST during the gap: the card still parses
        time.sleep(gap / 1000.0 + 0.05)
        c1 = b.counters()
        st = b.card_status()
        d = delta(c0, c1, "sync_gaps", "slips", "glitches", "crc")
        ok = d["sync_gaps"] == gap and d["slips"] == 0 and st["state"] == "synced"
        if lost:
            ok = ok and mid is not None and mid["state"] == "lost"
        check(f"SYNC gap of {gap} frames", ok, f"{d}, state during the gap: {mid and mid['state']}, after: "
              f"{st['state']}")


def t_ctrl(b):
    b.refresh(1)
    b.events(0xC0, PLAIN_PRESET)                         # init: no vibrato, no pitch envelope
    b.events(0xE0, 0x00, 0x40, 0xB0, 1, 0)               # bend centre, mod wheel 0 (no extra vibrato)
    b.events(0x90, 60, 100)
    settle(30)
    c0 = b.counters()
    b.events(0xE0, 0x7F, 0x7F)                           # bend +8191: +2 semitones (CTRL 0)
    settle(30)
    c1 = b.counters()
    b.events(0xE0, 0x00, 0x00)                           # -8192
    settle(30)
    c2 = b.counters()
    b.events(0xE0, 0x00, 0x40)
    b.events(0xB0, 74, 64, 0xB0, 71, 20, 0xB0, 1, 0)     # PARAM 32 cutoff, 33 resonance, CTRL 1 wheel
    settle(30)
    c3 = b.counters()
    b.body(0x01, buslib.PARAM, bytes([60, 1, 0]), lead=2)   # ID 60: reserved, ignored and counted
    settle(30)
    c4 = b.counters()
    b.events(0x80, 60, 0)
    ok = (c0["pitch"] == 60 * 256 and c1["pitch"] == 60 * 256 + 511 and c2["pitch"] == 60 * 256 - 512 and
          c3["pitch"] == 60 * 256 and c3["other"] == c0["other"] and c4["other"] == c0["other"] + 1)
    check("CTRL / PARAM", ok, f"pitch (1/256 semitone) {c0['pitch']} -> bend up {c1['pitch']}, down {c2['pitch']}, "
          f"centre {c3['pitch']}; 'other' +{c3['other'] - c0['other']} for PARAM 32 / 33 and CTRL 1, "
          f"+{c4['other'] - c3['other']} for PARAM 60")


def t_stress(b, seconds=20, period=0.0, progs=(DAC_PRESET, MODAL_PRESET, PLAIN_PRESET, 17)):
    """Dense traffic: a note as fast as the commands go (period 0: about 70 per second) or every period seconds,
    each with pitch bend, a cutoff PARAM and a mod-wheel CTRL; a program change every 100 notes."""
    b.refresh(1)
    c0, s0 = b.counters(True), b.status()
    t0, k, events = time.time(), 0, 0
    while time.time() - t0 < seconds:
        tn = time.time()
        if k % 100 == 0:
            b.events(0xC0, progs[(k // 100) % len(progs)])
            events += 1
        n = 40 + (k * 7) % 36
        b.events(0x90, n, 64 + k % 64, 0xE0, k & 0x7F, 0x40, 0xB0, 74, k & 0x7F, 0xB0, 1, (k * 3) & 0x7F)
        time.sleep(0.005 if not period else period / 2)
        b.events(0x80, n, 0)
        time.sleep(max(0.004, period - (time.time() - tn)) if period else 0.004)
        k += 1
        events += 5
    time.sleep(0.1)
    c1, s1 = b.counters(), b.status()
    d = delta(c0, c1, "packets", "crc", "framing", "uart", "late", "far", "qfull", "slips", "late_ticks", "underruns",
              "other", "glitches")
    bad = {n: v for n, v in d.items() if n not in ("packets", "glitches") and v}   # glitches: rejected SYNC noise
    ok = not bad and s1["tx_over"] == s0["tx_over"] and s1["fifo_late"] == s0["fifo_late"]
    check(f"stress {seconds} s, {k / seconds:.0f} notes/s, programs {list(progs)}", ok,
          f"{k} notes, {events} MIDI events, {d['packets']} packets accepted, errors {bad or 'none'}, SYNC glitches "
          f"rejected {d['glitches']}; controller "
          f"tx_over +{s1['tx_over'] - s0['tx_over']}, fifo_late +{s1['fifo_late'] - s0['fifo_late']}; card "
          f"tick_run_max {c1['tick_run_max']} cycles, stack_free {c1['stack_free']} bytes, DAC fill_max "
          f"{c1.get('fill_max')} cycles, slack_min {c1.get('slack_min')} periods")


def card_reset(port):
    mcl = os.path.join(os.path.expanduser(labconf.get("LAB_DIR", HERE)), labconf.get("MINICHLINK"))
    if not os.path.exists(mcl):
        mcl = labconf.get("MINICHLINK")
    subprocess.run([mcl, "-C", "ardulink", "-c", port, "-b"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=60)


def t_reset(b, port):
    s0 = b.status()
    b.close()
    card_reset(port)                                     # minichlink -b: a reset over SWIO (NRST is not wired)
    t0 = time.time()
    time.sleep(0.3)
    b2 = buslib.Bench(port)
    while time.time() - t0 < 3:
        s1 = b2.status()
        if s1["hellos"] != s0["hellos"] and s1["enum"] == 3:
            break
        time.sleep(0.1)
    dt = time.time() - t0
    time.sleep(0.05)
    c = b2.counters()
    check("re-enumeration after a card reset", s1["hellos"] - s0["hellos"] == 1 and c is not None and
          c["src"] == 0 and c["delay"] == 4, f"HELLO {s1['hellos'] - s0['hellos']} within {dt:.1f} s, card frame "
          f"{c and c['frame']}, D {c and c['delay']}, uid {s1['uid']}")
    return b2


def t_counters(b):
    print("controller:", b.status())
    print("card STATUS:", b.card_status())
    print("card COUNTERS:", b.counters())


# ------------------------------------------------------------------ load: 8 voices, 7 of them virtual
# [2026-10-19] The controller treats voices 1-7 as populated (Bench.voices); the card is voice 0 and must discard
# their packets. Bursts come from the PC ('e', one command = one execution frame); sustained traffic from the
# controller's generator (Bench.gen), which runs its MIDI through the same allocator and packet path.
LOAD_PROGS = (DAC_PRESET, MODAL_PRESET, 17, PLAIN_PRESET)   # 2 oscillators, modal, 3 oscillators, no DAC
PROG_NAMES = {DAC_PRESET: "lead_dac (2 osc)", MODAL_PRESET: "kettle (modal)", 17: "moog_bass (3 osc)",
              PLAIN_PRESET: "init (no DAC)"}
CHORD_IV = (0, 4, 7, 11, 12, 16, 19, 23)                 # as the generator's chord
CARD_ERR = ("crc", "framing", "uart", "late", "far", "qfull", "slips", "late_ticks", "underruns", "other")
CTRL3 = buslib.G_BEND | buslib.G_WHEEL | buslib.G_CUTOFF


def size(dst, mtype, payload, timed=True):
    """Encoded bytes of one packet (COBS, CRC, delimiter)."""
    return len(buslib.packet(bytes([dst, mtype]) + (b"\0" if timed else b"") + bytes(payload)))


def sizes():
    """Packet sizes and the 1 Mbaud budget, from the packet format (bus.md 4, 5.3)."""
    s = {"FRAME": size(0xFF, buslib.FRAME, b"\0\0", False), "NOTE_ON": size(1, buslib.NOTE_ON, b"\0" * 4),
         "NOTE_OFF": size(1, buslib.NOTE_OFF, b"\0"), "CTRL": size(1, buslib.CTRL, b"\0" * 3),
         "VOICE_STATE": size(1, buslib.VOICE_STATE, b"\0" * 3),
         "PATCH_PRESET": size(1, buslib.PATCH_PRESET, b"\0\0", False),
         "PATCH_DATA(8)": size(1, buslib.PATCH_DATA, b"\0" * 19, False)}
    for n in (2, 8):
        s[f"NOTE_ON x{n}"] = size(0xFF, buslib.NOTE_ON | buslib.MULTI, b"\0" * 4 * n)
        s[f"CTRL x{n}"] = size(0xFF, buslib.CTRL | buslib.MULTI, b"\0" * (1 + 2 * n))
    s["VOICE_STATE x8"] = size(0xFF, buslib.VOICE_STATE | buslib.MULTI, b"\0" * 24)
    return s


def chord_midi(parts, n=8, root=48, off=False, vel=100):
    m = []
    for i in range(n):
        m += [(0x80 if off else 0x90) | (i if parts else 0), root + CHORD_IV[i], 0 if off else vel - 4 * i]
    return m


def ctrl_midi(parts, n=8, v=64):
    m = []
    for c in range(n if parts else 1):
        m += [0xE0 | c, 0, (v + c) & 0x7F, 0xB0 | c, 1, (v + 2 * c) & 0x7F, 0xB0 | c, 74, (v + 3 * c) & 0x7F]
    return m


CARD_SUM = CARD_ERR + ("packets", "foreign", "rx_bytes")


def card_summary(c0, c1, acc=None):
    """Counter deltas (acc: added up over several reads, the counters are 16 bit) and the maxima since the clear."""
    d = delta(c0, c1, *CARD_SUM)
    if acc:
        d = {k: d[k] + acc.get(k, 0) for k in d}
    return d, {k: c1.get(k) for k in ("tick_run_max", "tick_core_max", "parse_avg", "parse_max", "rx_max",
                                      "fill_max", "slack_min", "stack_free")}


def counters_retry(b, n=3):
    for _ in range(n):
        c = b.counters()
        if c:
            return c
        time.sleep(0.05)
    raise IOError("no COUNTERS reply")


def load_row(name, l, d=None, c=None):
    fr = max(1, l["frames"])
    s = (f"  {name:44s} avg {l['bytes'] / fr:5.1f} B/frame (events {l['events'] / fr:4.1f}, refresh "
         f"{l['refresh'] / fr:4.1f}), peak {l['peak']:3d}, full {100 * l['full'] / fr:5.1f} %, late {l['late']} "
         f"(notes {l.get('late_hi', '?')}, card {l['late_card']}, max {l['late_max']} fr), backlog "
         f"{l['backlog_max']} B, lag {l['lag_max']} fr, drops {l['drops']}")
    if d is not None:
        bad = {k: v for k, v in d.items() if k in CARD_ERR and v}
        s += (f"\n  {'':44s} card: {bad or 'no errors'}, foreign {d['foreign']}, own {d['packets']}, tick_max "
              f"{c['tick_core_max']} ({c['tick_run_max']} with replies), parse avg {c['parse_avg']} max "
              f"{c['parse_max']} cyc ({c['rx_max']} B), fill_max {c['fill_max']}, slack_min {c['slack_min']}, "
              f"stack_free {c['stack_free']}")
    print(s)


def load_burst(b, midi, wait=0.05):
    c0 = counters_retry(b)
    b.counters(True)
    b.load(True)
    b.events(*midi)
    time.sleep(wait)
    l = b.load()
    return l, *card_summary(c0, counters_retry(b))


def load_run(b, seconds, **gen):
    """The generator for `seconds`, then stopped; the controller's load counters and the card's counters (read
    every 3 s: they are 16 bit)."""
    c0 = counters_retry(b)
    b.counters(True)
    b.load(True)
    b.gen(**gen)
    acc, prev, t_end = {}, c0, time.time() + seconds
    while time.time() < t_end:
        time.sleep(max(0.0, min(3.0, t_end - time.time())))
        c = b.counters()                                 # None if the REQUEST timed out behind a backlog
        if c:
            acc = {k: acc.get(k, 0) + v for k, v in delta(prev, c, *CARD_SUM).items()}
            prev = c
    b.gen()
    time.sleep(0.1)
    l = b.load()
    return l, *card_summary(prev, counters_retry(b), acc)


def load_setup(b, voices, flags, prog=None, hold_card=False):
    """Voices and flags; prog to the card (and, without V_RESERVE, to the whole part); a held note on the card."""
    b.gen()
    if prog is not None:
        b.voices(1)
        b.events(0xC0, prog)
        settle(50)
    b.voices(voices, flags)
    if prog is not None and not flags & buslib.V_RESERVE:
        for c in range(voices if flags & buslib.V_PARTS else 1):
            b.events(0xC0 | c, prog)
    if hold_card and flags & buslib.V_RESERVE:          # voice 0 outside the load: not refreshed, played directly
        b.body(0x01, buslib.NOTE_ON, struct.pack("<HBB", 57 << 8, 100, 0), lead=2)
    elif hold_card:                                      # through the controller (its VOICE_STATE knows the note)
        b.events(0x90, 57, 100)
    settle(100)


def t_load(b, voices=8, seconds=10, multi=False, parts=("sizes", "refresh", "bursts", "sweep", "ramp", "card"), delay=4,
           lead=2, prio=False):
    fm = (buslib.V_MULTI if multi else 0) | (buslib.V_PRIO if prio else 0)
    tag = ((" (" + ", ".join(x for x, on in (("multi", multi), ("prio", prio)) if on) + ")" if multi or prio else "")
           + (f", D {delay} L {lead}" if (delay, lead) != (4, 2) else ""))
    b.config(delay, lead)
    b.refresh(1)
    b.refresh_periods(0, 200, 0)
    if "sizes" in parts:
        s = sizes()
        print("packet sizes (bytes on the wire):", ", ".join(f"{k} {v}" for k, v in s.items()))
        fr, on, off, ct = s["FRAME"], s["NOTE_ON"], s["NOTE_OFF"], s["CTRL"]
        print(f"  expected: 8-note chord {fr + 8 * on} B with FRAME (budget 95); legato chord change "
              f"{fr + 8 * (on + off)}; chord + 3 controllers, one part {fr + 8 * on + 3 * ct}, 8 parts "
              f"{fr + 8 * on + 24 * ct}; multi: chord {fr + s['NOTE_ON x8']}, legato {fr + s['NOTE_ON x8'] + off}, "
              f"+ 3 controllers on 8 parts {fr + s['NOTE_ON x8'] + 3 * s['CTRL x8']}")
        print(f"  refresh per frame: VOICE_STATE {s['VOICE_STATE']} B every 50/{voices} frames = "
              f"{s['VOICE_STATE'] * voices / 50:.2f} B (multi: {s['VOICE_STATE x8']} / 50 = "
              f"{s['VOICE_STATE x8'] / 50:.2f} B); PATCH_PRESET {s['PATCH_PRESET']} / 200 = "
              f"{s['PATCH_PRESET'] / 200:.3f} B per part")
    if "refresh" in parts:
        print(f"--- refreshes, {voices} parts{tag}, no events (3 s each): VOICE_STATE (frames per packet; 0: auto), "
              f"PATCH_PRESET every 200 frames, PATCH_DATA (8 values, to the virtual voices)")
        load_setup(b, voices, buslib.V_PARTS | fm, prog=DAC_PRESET)
        for vs, pd in ((0, 0), (1, 0), (0, 16), (0, 2)):
            b.refresh_periods(vs, 200, pd)
            load_row(f"VOICE_STATE {vs or 'auto'}, PATCH_DATA {pd or 'off'}", *load_run(b, 3))
        b.refresh_periods(0, 200, 0)
    if "bursts" in parts:
        print(f"--- bursts, {voices} voices{tag}: one command each (all events for one frame)")
        for pm, pname in ((0, "one poly part"), (buslib.V_PARTS, f"{voices} parts")):
            load_setup(b, voices, pm | fm)
            p = bool(pm)
            b.load(True)
            time.sleep(2)
            load_row(f"{pname}: idle 2 s", b.load())
            load_row(f"{pname}: chord of {voices}", *load_burst(b, chord_midi(p, voices)))
            load_row(f"{pname}: legato chord change", *load_burst(b, chord_midi(p, voices, off=True) +
                                                                   chord_midi(p, voices, root=53)))
            b.events(*chord_midi(p, voices, root=53, off=True))
            settle(30)
            load_row(f"{pname}: chord + bend, wheel, cutoff", *load_burst(b, chord_midi(p, voices) +
                                                                       ctrl_midi(p, voices)))
            load_row(f"{pname}: release + bend, wheel, cutoff", *load_burst(b, chord_midi(p, voices, off=True) +
                                                                         ctrl_midi(p, voices, 20)))
    if "sweep" in parts:
        print(f"--- sustained {seconds} s, {voices} voices{tag}: 8-note chords every 250 frames (held 200), bend, "
              f"wheel and cutoff steps")
        for pm, pname in ((0, "one poly part"), (buslib.V_PARTS, f"{voices} parts")):
            load_setup(b, voices, pm | fm, prog=DAC_PRESET)
            for ce in (10, 5):
                load_row(f"{pname}: controllers every {ce} frames",
                         *load_run(b, seconds, chord=8, every=250, hold=200, ctrl=CTRL3, cevery=ce))
            load_row(f"{pname}: legato chords every 50 frames, ctl every 5",
                     *load_run(b, seconds, chord=8, every=50, hold=0, ctrl=CTRL3, cevery=5))
    if "ramp" in parts:
        print(f"--- limit, {voices} parts{tag}: bend, wheel, cutoff on every part every N frames, chords every 250 "
              f"frames ({max(2, seconds // 2)} s each)")
        load_setup(b, voices, buslib.V_PARTS | fm, prog=DAC_PRESET)
        for ce in (8, 6, 5, 4, 3, 2, 1):
            load_row(f"every {ce} frames ({1000 * 3 * voices / ce:.0f} events/s)",
                     *load_run(b, max(2, seconds // 2), chord=8, every=250, hold=200, ctrl=CTRL3, cevery=ce))
    if "card" in parts:
        print(f"--- card load per patch ({seconds} s each): a held note on the card; foreign traffic: {voices - 1} "
              f"virtual parts (V_RESERVE), chords every 250 frames, bend, wheel, cutoff every 3 frames; "
              f"own: the card is one of {voices} poly voices, chords + controllers every 5 frames")
        for prog in LOAD_PROGS:
            name = PROG_NAMES.get(prog, str(prog))
            load_setup(b, 1, 0, prog=prog, hold_card=True)
            load_row(f"{name}: no traffic", *load_run(b, seconds))
            load_setup(b, voices, buslib.V_PARTS | buslib.V_RESERVE | fm, prog=prog, hold_card=True)
            load_row(f"{name}: foreign traffic", *load_run(b, seconds, chord=8, every=250, hold=200, ctrl=CTRL3,
                                                           cevery=3))
            load_setup(b, voices, fm, prog=prog)
            load_row(f"{name}: one of {voices} poly voices", *load_run(b, seconds, chord=8, every=250, hold=200,
                                                                       ctrl=CTRL3, cevery=5))
    b.gen()
    b.voices(1)
    b.events(0x80, 57, 0)
    b.events(0xC0, DAC_PRESET)
    b.config(4, 2)


# ------------------------------------------------------------------ scope
def scope():
    import scope as sc
    return sc.Scope()


def t_carrier(b):
    s = scope()
    for c in (":RUN", ":TIM:SCAL 2E-6", ":TIM:OFFS 0", ":TRIG:MODE EDGE", ":TRIG:EDGE:SOUR CHAN2",
              ":TRIG:EDGE:LEV 1.5", ":TRIG:SWE AUTO"):
        s.check(c)
    res = {}
    for prog in (DAC_PRESET, PLAIN_PRESET, MODAL_PRESET):
        b.events(0xC0, prog)
        time.sleep(0.5)
        f = float(s.query(":MEAS:ITEM? FREQ,CHAN2"))
        v = np.array([y for _, y in s.wave("CHAN2")])
        res[prog] = (f, float(v.max() - v.min()))
    on = [res[p] for p in (DAC_PRESET, MODAL_PRESET)]
    check("DAC carrier", all(abs(f - 187500) < 1000 and pp > 2 for f, pp in on) and res[PLAIN_PRESET][1] < 1,
          ", ".join(f"program {p}: {f / 1e3:.2f} kHz, {pp:.2f} Vpp" if f < 1e37 else f"program {p}: no edges, "
                    f"{pp:.2f} Vpp" for p, (f, pp) in res.items()))


def edges(v, thr):
    hi = v > thr
    d = np.diff(hi.astype(np.int8))
    return np.nonzero(d == 1)[0] + 1, np.nonzero(d == -1)[0] + 1


def t_latency(b, n, delay, lead, mark, load=None, cevery=3, multi=False, prio=False):
    """load (8 voices, 7 virtual, generator running): "parts" -- the card is outside the load (V_RESERVE), the other
    7 parts play chords every 250 frames and bend / wheel / cutoff every `cevery` frames, the NOTE_ON goes to the
    card alone; "chord" -- one poly part over 8 voices, the card's note is one of an 8-note chord sent in one
    command (NOTE_ON with phase reset, V_PHASE), bend / wheel / cutoff on the part every `cevery` frames."""
    s = scope()
    s.s.settimeout(30)
    b.config(delay, lead)
    fm = (buslib.V_MULTI if multi else 0) | (buslib.V_PRIO if prio else 0)
    if load == "parts":
        load_setup(b, 8, buslib.V_PARTS | buslib.V_RESERVE | fm, prog=DAC_PRESET)
        b.gen(chord=8, every=250, hold=200, ctrl=CTRL3, cevery=cevery)
    elif load == "chord":
        load_setup(b, 8, buslib.V_PHASE | fm, prog=DAC_PRESET)
        b.gen(ctrl=CTRL3, cevery=cevery)
    else:
        b.refresh(0)
    b.events(0xC0, DAC_PRESET, 0xB0, 1, 0, 0xE0, 0x00, 0x40)   # no extra vibrato, bend centre
    b.marker(mark)
    if load:
        c0 = b.counters(True)
        b.load(True)
    s.write("*CLS")
    expect = delay if mark == 1 else lead - 1 + delay
    for c in (":RUN", ":CHAN1:SCAL 1", ":CHAN2:SCAL 1", ":TIM:SCAL 1E-3", f":TIM:OFFS {expect / 2 * 1e-3}",
              ":ACQ:MDEP 1M", ":TRIG:MODE PULS", ":TRIG:PULS:SOUR CHAN1", ":TRIG:PULS:WHEN LESS",
              ":TRIG:PULS:UWID 3E-4", ":TRIG:PULS:LEV 1.65", ":TRIG:SWE NORM"):
        s.check(c)
    lat = []
    note_on = struct.pack("<HBB", 60 << 8, 100, NOTE_PHASE)
    for i in range(n):
        if load == "chord":
            b.events(*chord_midi(False, 8, off=True))
        else:
            b.body(0x01, buslib.NOTE_OFF, b"\0", lead=lead)
        time.sleep(1.2 if i else 2.5)                    # full release: the output is back at 50 % duty
        s.write(":SING")
        t0 = time.time()
        while s.query(":TRIG:STAT?") not in ("WAIT", "TD"):
            time.sleep(0.05)
            if time.time() - t0 > 10:
                raise RuntimeError("scope did not arm")
        time.sleep(0.1)
        if load == "chord":
            fx = b.events(*chord_midi(False, 8))
        else:
            fx = b.body(0x01, buslib.NOTE_ON, note_on, lead=lead)
        t0 = time.time()
        while s.query(":TRIG:STAT?") != "STOP":
            time.sleep(0.05)
            if time.time() - t0 > 5:
                raise RuntimeError("no trigger (marker)")
        w = {}
        for ch in ("CHAN1", "CHAN2"):
            for c in (f":WAV:SOUR {ch}", ":WAV:MODE RAW", ":WAV:FORM BYTE"):
                s.check(c)
            npts = int(float(s.query(":ACQ:MDEP?")))
            s.write(":WAV:STAR 1")
            s.write(f":WAV:STOP {npts}")
            pre = s.query(":WAV:PRE?").split(",")
            xinc, xorg, yinc, yorg, yref = (float(pre[k]) for k in (4, 5, 7, 8, 9))
            parts = []
            for a in range(1, npts + 1, 250000):
                s.write(f":WAV:STAR {a}")
                s.write(f":WAV:STOP {min(npts, a + 249999)}")
                parts.append(np.frombuffer(s.block(":WAV:DATA?"), np.uint8))
            raw = np.concatenate(parts).astype(np.float32)
            w[ch] = (raw - yorg - yref) * yinc
        t = xorg + np.arange(len(w["CHAN1"])) * xinc
        r1, f1 = edges(w["CHAN1"], 1.65)
        mk = None
        for r in r1:                                     # the short SYNC pulse
            f = f1[f1 > r]
            if len(f) and (f[0] - r) * xinc < 3e-4:
                mk = t[r]
                break
        r2, f2 = edges(w["CHAN2"], 1.65)
        if mk is None or len(r2) < 10:
            check(f"latency {i}", False, f"marker {mk}, {len(r2)} PWM edges")
            continue
        f2 = f2[f2 > r2[0]]
        m = min(len(r2), len(f2))
        hw = (f2[:m] - r2[:m]) * xinc                    # high time of each PWM pulse
        per = np.median(np.diff(r2)) * xinc
        cen = t[r2[:m]] + hw / 2                         # pulse centres (centre-aligned PWM)
        dev = np.abs(hw - per / 2) > 0.1 * per
        idx = np.nonzero(dev & (cen > mk - 0.5e-3))[0]
        before = np.count_nonzero(dev & (cen > mk - 0.5e-3) & (cen < mk + expect * 1e-3 - 0.2e-3))
        if not len(idx):
            check(f"latency {i}", False, "no note on PC2")
            continue
        lt = cen[idx[0]] - mk
        lat.append(lt)
        print(f"  {i}: exec frame {fx}, marker at {mk * 1e3:.4f} ms, note at {cen[idx[0]] * 1e3:.4f} ms: "
              f"{lt * 1e3:.4f} ms (carrier {1 / per / 1e3:.2f} kHz, {before} deviant periods before)")
    b.marker(0)
    if load:
        b.gen()
        time.sleep(0.1)
        l = b.load()
        load_row(f"load during the latency test ({load}{', multi' if multi else ''}{', prio' if prio else ''}, "
                 f"controllers every {cevery} frames)", l,
                 *card_summary(c0, b.counters()))
        b.events(*chord_midi(False, 8, off=True))
        b.voices(1)
    b.config(4, 2)
    b.refresh(1)
    for c in (":TRIG:MODE EDGE", ":TRIG:EDGE:SOUR CHAN2", ":TRIG:EDGE:LEV 1.5", ":TRIG:SWE AUTO", ":TIM:SCAL 2E-6",
              ":TIM:OFFS 0", ":RUN"):
        s.write(c)
    if lat:
        a = np.array(lat) * 1e3
        check(f"latency D {delay} L {lead} mark {mark}{f' under load ({load})' if load else ''}"
              f"{' multi' if multi else ''}{' prio' if prio else ''}",
              abs(a.mean() - expect) < 0.05 and a.max() - a.min() < 0.02,
              f"{len(a)} notes: mean {a.mean():.4f} ms (expected {expect} ms + about a carrier period), "
              f"min {a.min():.4f}, max {a.max():.4f}, spread {(a.max() - a.min()) * 1e3:.1f} us")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tests", nargs="+")
    ap.add_argument("--port", default=None)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--delay", type=int, default=4)
    ap.add_argument("--lead", type=int, default=2)
    ap.add_argument("--mark", type=int, default=1)
    ap.add_argument("--period", type=float, default=0.0, help="stress: seconds per note (0: as fast as possible)")
    ap.add_argument("--progs", default="", help="stress: programs, comma-separated")
    ap.add_argument("--voices", type=int, default=8, help="load: voices (voice 0 = the card, the others virtual)")
    ap.add_argument("--seconds", type=int, default=10, help="load: seconds per sustained run")
    ap.add_argument("--multi", action="store_true", help="load, latency: per-voice records (V_MULTI)")
    ap.add_argument("--prio", action="store_true", help="load, latency: notes ahead of controllers (V_PRIO)")
    ap.add_argument("--parts", default="sizes,refresh,bursts,sweep,ramp,card",
                    help="load: which parts, comma-separated")
    ap.add_argument("--load", default=None, choices=("parts", "chord"), help="latency: under 8-voice load")
    ap.add_argument("--cevery", type=int, default=3, help="latency --load: frames per controller step")
    a = ap.parse_args()
    port = a.port or buslib.bench_port()
    b = buslib.Bench(port)
    tests = a.tests
    if tests == ["all"]:
        tests = ["enum", "notes", "patch", "ctrl", "crc", "repair", "late", "config", "sync", "reset"]
    for t in tests:
        print(f"--- {t}")
        if t == "reset":
            b = t_reset(b, port)
        elif t == "latency":
            t_latency(b, a.n, a.delay, a.lead, a.mark, a.load, a.cevery, a.multi, a.prio)
        elif t == "load":
            t_load(b, a.voices, a.seconds, a.multi, a.parts.split(","), a.delay, a.lead, a.prio)
        elif t == "stress":
            progs = tuple(int(x) for x in a.progs.split(",")) if a.progs else (DAC_PRESET, MODAL_PRESET, PLAIN_PRESET,
                                                                                17)
            t_stress(b, 20, a.period, progs)
        else:
            globals()[f"t_{t}"](b)
    if "counters" not in tests:
        t_counters(b)
    sys.exit(fails)


if __name__ == "__main__":
    main()
