#!/usr/bin/env python3
"""USB tests of the bench controller (firmware/bench_ctrl: USB-MIDI + CDC, usbdev.h, controller.md 5) on the lab
PC. The control channel is the bench port (USART1 over the WCH-LinkE, as bustest.py); the device under test is the
controller's own USB port: the ALSA raw MIDI port of the card "TouchSynth Poly" and its CDC port
(/dev/serial/by-id/usb-TouchSynth_TouchSynth_Poly_<serial>-if02, or USB_CDC_PORT in lab.conf). Copy buslib.py,
bustest.py, labconf.py, scope.py and lab.conf next to this file.

  python3 usbtest.py all               # enum cdc inject pins replug reset, then midi flood latency (ALSA port needed)
  python3 usbtest.py inject            # bustest's notes / patch / ctrl checks with the MIDI as USB-MIDI packets put
                                       # into the firmware's USB-MIDI path ('Q'): the parsing, without ALSA
  python3 usbtest.py enum              # sysfs, ALSA, tty: ID, speed, interfaces and their drivers, the firmware's view
  python3 usbtest.py cdc [--n 1000]    # the bench commands over CDC: sync, status, 'e' bursts (rate, arrival ->
                                       # execution), a command cut off by closing the port, USART1 still answers
  python3 usbtest.py midi              # ALSA: the identity request (MIDI IN), then bustest's notes / patch / ctrl
                                       # checks with every MIDI message sent over USB-MIDI (the card's counters)
  python3 usbtest.py flood [--n 20000] # dense MIDI as fast as ALSA takes it: every event arrives (firmware counters),
                                       # the rate (bus-bound notes + controllers, then unmapped CCs: the intake)
  python3 usbtest.py latency [--n 20] [--scope]   # USB arrival -> execution frame edge (firmware stamps); --scope:
                                       # the execution frame's SYNC marker -> the note on PC2 (bustest latency, the
                                       # notes over USB-MIDI): the sum is USB -> note
  python3 usbtest.py jitter [--seconds 3]   # scope: SYNC (CH1) period and time interval error, the frame interrupt's
                                       # latency ('L' irq_max), without USB traffic, with a CDC flood, a MIDI flood
  python3 usbtest.py replug [--n 5]    # soft re-plug ('u': the D+ pull-up off for 300 ms): the host sees the device
                                       # leave and return; CDC (and MIDI) work again
  python3 usbtest.py reset             # V203 reset (minichlink -b): USB and voice bus re-enumerate
  python3 usbtest.py pins              # 'X': PA11 / PA12 / PB6 / PB7 levels, the USBD pull-up probe

ALSA's raw MIDI devices are root:audio 0660 (plus an ACL for the user at the seat): over SSH the user must be in
the group audio (sudo usermod -aG audio $USER, then log in again); without it the MIDI tests report SKIP.
Each test prints PASS / FAIL / SKIP lines; the exit code is the number of failures.
"""
import argparse
import glob
import os
import re
import select
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buslib                                            # noqa: E402
import bustest                                           # noqa: E402
import labconf                                           # noqa: E402
try:
    import numpy as np                                   # jitter
except ImportError:
    np = None

USB_ID = labconf.get("USB_ID", "1209:0001")              # the firmware's default (pid.codes test ID)
PRODUCT = "TouchSynth Poly"
check, settle, delta = bustest.check, bustest.settle, bustest.delta


def skip(name, why):
    print(f"SKIP {name}: {why}")


# ------------------------------------------------------------------ finding the device
def sysfs_dev():
    vid, pid = USB_ID.split(":")
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            if open(d + "/idVendor").read().strip() == vid and open(d + "/idProduct").read().strip() == pid:
                return d
        except OSError:
            pass
    return None


def rd(path, default=""):
    try:
        return open(path).read().strip()
    except OSError:
        return default


def cdc_port():
    p = labconf.get("USB_CDC_PORT", "")
    if p:
        return p
    g = sorted(glob.glob(f"/dev/serial/by-id/usb-TouchSynth_{PRODUCT.replace(' ', '_')}_*-if02"))
    return g[0] if g else None


def alsa_card():
    """The ALSA card number of the device, or None."""
    for line in rd("/proc/asound/cards").splitlines():
        m = re.match(r"\s*(\d+)\s+\[.*\]:\s+USB-Audio - (.*)", line)
        if m and m.group(2).strip() == PRODUCT:
            return int(m.group(1))
    return None


def wait_for(cond, timeout, step=0.02):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return time.time() - t0
        time.sleep(step)
    return None


class RawMidi:
    """ALSA raw MIDI device (/dev/snd/midiCxD0): blocking writes, reads with a timeout."""

    def __init__(self, card):
        self.path = f"/dev/snd/midiC{card}D0"
        self.fd = os.open(self.path, os.O_RDWR)

    def write(self, data):
        mv = memoryview(bytes(data))
        while mv:
            n = os.write(self.fd, mv)
            mv = mv[n:]

    def read(self, n, timeout=0.5):
        out, t_end = b"", time.time() + timeout
        while len(out) < n:
            r, _, _ = select.select([self.fd], [], [], max(0.0, t_end - time.time()))
            if not r:
                break
            out += os.read(self.fd, n - len(out))
        return out

    def drain(self):
        while select.select([self.fd], [], [], 0.05)[0]:
            os.read(self.fd, 256)

    def close(self):
        os.close(self.fd)


def open_midi():
    """(RawMidi, None) or (None, the reason)."""
    card = alsa_card()
    if card is None:
        return None, "no ALSA card named " + PRODUCT
    try:
        return RawMidi(card), None
    except PermissionError:
        return None, (f"no access to /dev/snd/midiC{card}D0 (root:audio 0660): sudo usermod -aG audio $USER, then a "
                      f"new login")


# ------------------------------------------------------------------ the firmware's USB status ('U')
def usb_status(b, clear=False):
    b.s.write(b"U" + bytes([1 if clear else 0]))
    words = b.s.readline().decode().split()
    d = {}
    for k, v in zip(words[1::2], words[2::2]):          # "usb port fs conf 1 ..."
        d[k] = int(v) if v.isdigit() else v
    return d


def bench_load(b, clear=False):
    return b.load(clear)


class ViaUsb:
    """bustest's Bench with every MIDI message (events) sent over USB-MIDI instead of 'e', and NOTE_ON / NOTE_OFF
    bodies (the latency test) as MIDI notes; everything else on the bench port."""

    def __init__(self, bench, midi):
        self.bench, self.midi, self.note = bench, midi, 60

    def events(self, *m):
        self.midi.write(bytes(m))
        time.sleep(0.003)                                # a USB frame, so that settle() starts after the arrival
        return None

    def body(self, dst, mtype, payload=b"", lead=None, corrupt=False):
        if mtype == buslib.NOTE_ON:
            self.note = payload[1]
            self.midi.write(bytes([0x90, self.note, payload[2]]))
            return 0
        if mtype == buslib.NOTE_OFF:
            self.midi.write(bytes([0x80, self.note, 0]))
            return 0
        return self.bench.body(dst, mtype, payload, lead, corrupt)

    def __getattr__(self, name):
        return getattr(self.bench, name)


def usb_midi_packets(m):
    """MIDI bytes (status bytes present) -> 4-byte USB-MIDI event packets, cable 0 (SysEx in chunks of 3)."""
    out, i = bytearray(), 0
    while i < len(m):
        st = m[i]
        if st == 0xF0:
            j = m.index(0xF7, i) + 1
            sx = m[i:j]
            for k in range(0, len(sx), 3):
                c = sx[k:k + 3]
                cin = 0x4 if len(sx) - k > 3 else (0x5, 0x6, 0x7)[len(c) - 1]
                out += bytes([cin]) + bytes(c) + bytes(3 - len(c))
            i = j
            continue
        n = 2 if st & 0xF0 in (0xC0, 0xD0) else 3
        out += bytes([st >> 4]) + bytes(m[i:i + n]) + bytes(3 - n)
        i += n
    return bytes(out)


class ViaInject:
    """Every MIDI message (events) as USB-MIDI packets through the firmware's USB-MIDI path ('Q', the bench port):
    the parsing after the endpoint, without the USB transfer (when ALSA cannot be opened)."""

    def __init__(self, bench):
        self.bench = bench

    def events(self, *m):
        p = usb_midi_packets(list(m))
        for k in range(0, len(p), 64):
            self.bench.s.write(b"Q" + bytes([len(p[k:k + 64])]) + p[k:k + 64])
            self.bench._plus()
        return None

    def __getattr__(self, name):
        return getattr(self.bench, name)


# ------------------------------------------------------------------ tests
def t_inject(b):
    v = ViaInject(b)
    u0 = usb_status(b, True)
    bustest.t_notes(v)
    bustest.t_patch(v)
    bustest.t_ctrl(v)
    v.events(0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7)        # the identity request: a reply on MIDI IN (if read)
    time.sleep(0.05)
    u = usb_status(b)
    check("injected USB-MIDI packets", u["sysex"] == 1 and u["ident"] + u["ident_lost"] == 1,
          f"{u['packets']} packets, {u['events']} events parsed; identity request answered on MIDI IN "
          f"{'yes' if u['ident'] else 'no (endpoint busy: no program reads)'}; arrival -> execution edge "
          f"{u['lat_min']} / {u['lat_mean']} / {u['lat_max']} us")


def t_enum(b):
    d = sysfs_dev()
    if not d:
        check("USB device", False, f"{USB_ID} not on the bus (lsusb, journalctl -k)")
        return
    itf = {}
    for i in sorted(glob.glob(d + ":1.*")):
        drv = os.path.basename(os.path.realpath(i + "/driver")) if os.path.exists(i + "/driver") else "-"
        itf[i.rsplit(":", 1)[1]] = (rd(i + "/bInterfaceClass"), rd(i + "/bInterfaceSubClass"), drv)
    speed, prod, ser = rd(d + "/speed"), rd(d + "/product"), rd(d + "/serial")
    check("USB device", speed == "12" and prod == PRODUCT,
          f"{os.path.basename(d)}: {USB_ID} '{rd(d + '/manufacturer')} {prod}' serial {ser}, {speed} Mbit/s, "
          f"{rd(d + '/bMaxPower')}, configuration {rd(d + '/bConfigurationValue')}")
    want = {"1.0": ("01", "01", "snd-usb-audio"), "1.1": ("01", "03", "snd-usb-audio"), "1.2": ("02", "02", "cdc_acm"),
            "1.3": ("0a", "00", "cdc_acm")}
    check("interfaces and drivers", itf == want,
          ", ".join(f"{k}: class {c}/{s} -> {v}" for k, (c, s, v) in itf.items()))
    card = alsa_card()
    midi = rd(f"/proc/asound/card{card}/midi0") if card is not None else ""
    check("ALSA card", card is not None and "Output 0" in midi and "Input 0" in midi,
          f"card {card}: " + " / ".join(x.strip() for x in midi.splitlines() if x.strip()))
    p = cdc_port()
    check("CDC port", p is not None and os.path.exists(p), f"{p} -> {p and os.path.realpath(p)}")
    u = usb_status(b)
    check("firmware view", u.get("conf") == 1, f"port {u.get('port')}, configured {u.get('conf')}, address "
          f"{u.get('addr')}, DTR {u.get('dtr')}, configurations lost {u.get('resets')}, stack_free "
          f"{u.get('stack_free')}")


def t_cdc(b, n=1000):
    p = cdc_port()
    if not p:
        check("CDC", False, "no CDC port")
        return
    c = buslib.Bench(p)
    s = c.status()
    check("CDC: bench commands", s.get("enum") == 3, f"'?' -> '!', status over CDC: enum {s.get('enum')}, card "
          f"{s.get('card')}, frame {s.get('frame')}")
    c.refresh(1)
    c.events(0xC0, bustest.PLAIN_PRESET)
    for name, pace, msg in (("unmapped CC 20 (no bus traffic), back to back", 0, lambda k: (0xB0, 20, k & 0x7F)),
                            ("note on / off, at most 2 per frame", 0.0005,
                             lambda k: (0x90 if k % 2 == 0 else 0x80, 48 + (k // 2) % 24, 100 if k % 2 == 0 else 0))):
        s0, l0, c0 = b.status(), b.load(True), bustest.counters_retry(b)
        usb_status(c, True)
        t0 = time.time()
        for k in range(n):                               # each command waits for its reply
            c.events(*msg(k))
            if pace:
                time.sleep(pace)
        dt = time.time() - t0
        time.sleep(0.05)
        u = usb_status(c)
        s1, l1, c1 = b.status(), b.load(), bustest.counters_retry(b)
        d = delta(c0, c1, *bustest.CARD_ERR)
        bad = {k: v for k, v in d.items() if v}
        check(f"CDC: {n} 'e' commands, {name}", u["elat_n"] == n and not bad and s1["tx_over"] == s0["tx_over"] and
              s1["fifo_late"] == s0["fifo_late"] and not l1["drops"],
              f"{n / dt:.0f} commands/s ({1e3 * dt / n:.3f} ms each, reply included); arrival -> publish mean "
              f"{u['elat_proc_mean']} us, max {u['elat_proc_max']} us; arrival -> execution frame edge "
              f"{u['elat_min']} / {u['elat_mean']} / {u['elat_max']} us (min / mean / max, L = 2); card errors "
              f"{bad or 'none'}; frame interrupt latency max {l1['irq_max']} us, tx_over "
              f"+{s1['tx_over'] - s0['tx_over']}, fifo_late +{s1['fifo_late'] - s0['fifo_late']}")
    c.s.write(b"e\x06\x90\x3c")                          # a command cut off: the port closes after 2 of 6 bytes
    c.s.flush()
    time.sleep(0.05)
    c.close()
    time.sleep(0.1)
    ok1 = b.status().get("enum") == 3
    c = buslib.Bench(p)
    ok2 = c.status().get("enum") == 3
    c.close()
    check("CDC: a command cut off by closing the port", ok1 and ok2, f"USART1 answers {ok1}, CDC reopened {ok2}")


def t_pins(b):
    b.s.write(b"X")
    w = b.s.readline().decode().split()
    bits, t = w[0], [int(x) for x in w[1:]]
    ns = 1e3 / 144                                       # HCLK ticks
    host = {"PA11/PA12": bits[0:2] == "00", "PB6/PB7": bits[4:6] == "00"}
    print(f"  GPIO pull-up / pull-down: PA11 {bits[0]}/{bits[2]} PA12 {bits[1]}/{bits[3]} PB6 {bits[4]}/{bits[6]} PB7 "
          f"{bits[5]}/{bits[7]} -> a host's pull-downs on: {', '.join(k for k, v in host.items() if v) or 'none'}")
    print(f"  USBD pull-up on PA12: against the GPIO pull-down {bits[8]} (USBD in reset) {bits[9]} (running); "
          f"floating from 0 V: on {bits[10]}, off {bits[11]}; with the GPIO pull-up: on {bits[12]}, off {bits[13]}")
    names = ("USBD pull-up", "GPIO pull-up", "GPIO pull-down", "floating")
    for j, st in enumerate(("transceiver on, EF 0", "transceiver on, EF 1", "transceiver off")):
        cell = ("none" if v >= 2880 else "at once" if v <= t[0] else f"{(v - t[0]) * ns:.0f} ns"
                for v in t[1 + 4 * j:5 + 4 * j])
        print(f"  PA12 edges, {st:21s}: " + ", ".join(f"{nm} {c}" for nm, c in zip(names, cell)))
    print(f"  (loop delay {t[0] * ns:.0f} ns subtracted; 'none': no edge within 20 us)")
    check("USBD D+ pull-up switchable", bits[10] == "1" and bits[11] == "0" and t[1] < 2880 and t[9] >= 2880,
          "EXTEN_USBD_PU_EN raises PA12 only with the bit set and the transceiver powered")
    u = usb_status(b)
    check("pin check left USB attached", wait_for(lambda: usb_status(b).get("conf") == 1, 5) is not None,
          f"configured again after the probe's detach ({u.get('port')})")


def t_replug(b, n=5):
    times, ok_all = [], True
    for i in range(n):
        d0 = sysfs_dev()
        b.s.write(b"u" + bytes([30]))                     # pull-up off for 300 ms
        b._plus()
        gone = wait_for(lambda: sysfs_dev() is None, 2, 0.005)
        back = wait_for(lambda: sysfs_dev() is not None and cdc_port() and os.path.exists(cdc_port()), 5)
        ok = gone is not None and back is not None
        if ok:
            wait_for(lambda: usb_status(b).get("conf") == 1, 3)
            c = buslib.Bench(cdc_port())
            ok = c.status().get("enum") == 3
            c.close()
        times.append(back)
        ok_all &= ok
        print(f"  {i}: {os.path.basename(d0 or '-')} gone after {gone and gone * 1e3:.0f} ms, back (tty) "
              f"{back and back * 1e3:.0f} ms later, CDC {'ok' if ok else 'FAIL'}")
    m, why = open_midi()
    if m:
        m.write(b"\xF0\x7E\x7F\x06\x01\xF7")
        r = m.read(15, 0.5)
        m.close()
        check("MIDI after the re-plugs", r[:5] == b"\xF0\x7E\x00\x06\x02", f"identity reply {r.hex(' ')}")
    else:
        skip("MIDI after the re-plugs", why)
    u = usb_status(b)
    check(f"soft re-plug x{n}", ok_all, f"re-enumerated within {max(t or 9 for t in times):.2f} s each; firmware: "
          f"configured {u.get('conf')}, configurations lost {u.get('resets')}")


def t_reset(b):
    mcl = os.path.join(os.path.expanduser(labconf.get("LAB_DIR", HERE)), labconf.get("MINICHLINK"))
    b.close()
    t0 = time.time()
    subprocess.run([mcl, "-b"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)   # the V203
    t1 = time.time()
    gone = wait_for(lambda: sysfs_dev() is None, 2, 0.005)
    back = wait_for(lambda: sysfs_dev() is not None and cdc_port() and os.path.exists(cdc_port()), 8)
    b2 = None
    for _ in range(20):
        try:
            b2 = buslib.Bench()
            break
        except (IOError, OSError):
            time.sleep(0.2)
    en = wait_for(lambda: b2.status().get("enum") == 3, 5, 0.1) if b2 else None
    s = b2.status() if b2 else {}
    check("V203 reset", back is not None and s.get("enum") == 3 and s.get("card") == 1,
          f"minichlink -b took {t1 - t0:.1f} s; USB device gone {gone is not None}, back after "
          f"{back and back:.2f} s; voice bus: card enumerated {s.get('card')} (frame {s.get('frame')}, "
          f"{en and en:.1f} s after USB)")
    return b2 or buslib.Bench()


def t_midi(b):
    m, why = open_midi()
    if not m:
        skip("USB-MIDI", why)
        return
    m.drain()
    t0 = time.time()
    m.write(b"\xF0\x7E\x7F\x06\x01\xF7")
    r = m.read(15, 0.5)
    dt = time.time() - t0
    check("identity request (MIDI OUT -> IN)", r == bytes.fromhex("F07E000602 7D 0000 0000 00010000 F7"),
          f"reply {r.hex(' ')} after {dt * 1e3:.1f} ms")
    v = ViaUsb(b, m)
    u0 = usb_status(b, True)
    bustest.t_notes(v)
    bustest.t_patch(v)
    bustest.t_ctrl(v)
    u = usb_status(b)
    print(f"  firmware: {u['packets']} USB-MIDI packets, {u['events']} events, arrival -> execution edge "
          f"{u['lat_min']} / {u['lat_mean']} / {u['lat_max']} us, arrival -> publish max {u['lat_proc_max']} us")
    m.close()


def flood_run(b, m, msgs, label, bus=True):
    """Write msgs (3-byte MIDI messages) as fast as ALSA takes them; wait for the firmware; compare."""
    data = b"".join(msgs)
    s0, l0, c0 = b.status(), b.load(True), bustest.counters_retry(b)
    usb_status(b, True)
    t0 = time.time()
    for i in range(0, len(data), 3 * 256):
        m.write(data[i:i + 3 * 256])
    t1 = time.time()
    last, t_last = -1, time.time()
    while time.time() - t_last < 0.3:                    # until the event count stops growing
        u = usb_status(b)
        if u["events"] != last:
            last, t_last = u["events"], time.time()
        time.sleep(0.05)
    t2 = t_last
    s1, l1, c1 = b.status(), b.load(), bustest.counters_retry(b)
    d = delta(c0, c1, *bustest.CARD_ERR)
    # a flood beyond the bus capacity (about 86 B/frame at 1 Mbaud, bus.md 9.5) makes events late by design: then
    # the test is that USB loses nothing and the bus drops nothing; lateness is reported, not failed
    saturated = bus and l1["bytes"] / max(1, l1["frames"]) > 70
    bad = {k: v for k, v in d.items() if v and (bus or k != "other") and not (saturated and k == "late")}
    rate = len(msgs) / max(1e-6, t2 - t0)
    ok = u["events"] == len(msgs) and not l1["drops"] and s1["tx_over"] == s0["tx_over"] and not bad
    if saturated:
        label += " (bus saturated: late events expected)"
    check(f"flood: {label}", ok, f"{len(msgs)} messages sent in {t1 - t0:.2f} s, {u['events']} events in "
          f"{u['packets']} packets arrived ({rate:.0f} / s, {u['midi_bytes'] / max(1, u['midi_pkts']):.0f} B per "
          f"packet); endpoint held (NAK) {u['midi_held']} times; bus: {l1['bytes'] / max(1, l1['frames']):.1f} "
          f"B/frame, peak {l1['peak']}, full {100 * l1['full'] / max(1, l1['frames']):.0f} %, late {l1['late']}, "
          f"drops {l1['drops']}, backlog max {l1['backlog_max']} B; card errors {bad or 'none'}; irq_max "
          f"{l1['irq_max']} us; arrival -> publish max {u['lat_proc_max']} us")
    return u, l1


def t_flood(b, n=20000):
    m, why = open_midi()
    if not m:
        skip("USB-MIDI flood", why)
        return
    b.refresh(1)
    b.voices(1)
    b.events(0xC0, bustest.PLAIN_PRESET)
    msgs = []
    for k in range(n // 4):                              # note on, bend, wheel, note off: all reach the bus
        note = 36 + k % 48
        msgs += [bytes([0x90, note, 100]), bytes([0xE0, k & 0x7F, 0x40]), bytes([0xB0, 1, k & 0x7F]),
                 bytes([0x80, note, 0])]
    flood_run(b, m, msgs, f"{len(msgs)} notes / bend / wheel (to the bus)")
    msgs = [bytes([0xB0, 20, k & 0x7F]) for k in range(n)]   # CC 20: not mapped, nothing on the bus
    flood_run(b, m, msgs, f"{n} unmapped CCs (USB intake only)", bus=False)
    b.events(0xE0, 0x00, 0x40, 0xB0, 1, 0)
    m.close()


def t_latency(b, n=20, use_scope=False):
    m, why = open_midi()
    if not m:
        skip("USB-MIDI latency", why)
        return
    b.refresh(1)
    b.voices(1)
    b.events(0xC0, bustest.DAC_PRESET)
    usb_status(b, True)
    for k in range(n):
        m.write(bytes([0x90, 60, 100]))
        time.sleep(0.03)
        m.write(bytes([0x80, 60, 0]))
        time.sleep(0.02)
    u = usb_status(b)
    check(f"USB-MIDI arrival -> execution frame edge ({2 * n} messages)", u["lat_n"] == 2 * n,
          f"min {u['lat_min']} us, mean {u['lat_mean']} us, max {u['lat_max']} us (expected 1000-2000 at L = 2: the "
          f"rest of the arrival frame + 1 frame); arrival -> publish mean {u['lat_proc_mean']} us, max "
          f"{u['lat_proc_max']} us; + D = 4 frames to the note")
    if use_scope:
        b.voices(1, buslib.V_PHASE)                      # NOTE_ON with phase reset: the PWM leaves 50 % at once
        bustest.t_latency(ViaUsb(b, m), min(n, 10), 4, 2, 1)
        b.voices(1)
        u = usb_status(b)
        print(f"  during the scope run: arrival -> execution edge {u['lat_min']} / {u['lat_mean']} / {u['lat_max']} "
              f"us: USB -> note = that + the marker -> note above")
    m.close()


# ------------------------------------------------------------------ SYNC jitter (scope)
def capture(s, ch, npts):
    for c in (f":WAV:SOUR {ch}", ":WAV:MODE RAW", ":WAV:FORM BYTE"):
        s.check(c)
    s.write(":WAV:STAR 1")
    s.write(f":WAV:STOP {npts}")
    pre = s.query(":WAV:PRE?").split(",")
    xinc, xorg, yinc, yorg, yref = (float(pre[k]) for k in (4, 5, 7, 8, 9))
    parts = []
    for a in range(1, npts + 1, 250000):
        s.write(f":WAV:STAR {a}")
        s.write(f":WAV:STOP {min(npts, a + 249999)}")
        parts.append(np.frombuffer(s.block(":WAV:DATA?"), np.uint8))
    v = (np.concatenate(parts).astype(np.float32) - yorg - yref) * yinc
    return xorg, xinc, v


def rising_edges(xorg, xinc, v, thr=1.65):
    i = np.nonzero((v[:-1] < thr) & (v[1:] >= thr))[0]
    frac = (thr - v[i]) / (v[i + 1] - v[i])               # linear interpolation between the two samples
    return xorg + (i + frac) * xinc


def sync_stats(s, captures):
    """SYNC rising edges of several captures: periods and the time interval error (the residual of a straight line
    through each capture's edges)."""
    per, tie = [], []
    for _ in range(captures):
        s.write(":SING")
        wait_for(lambda: s.query(":TRIG:STAT?") == "STOP", 5, 0.05)
        e = rising_edges(*capture(s, "CHAN1", int(float(s.query(":ACQ:MDEP?")))))
        if len(e) < 3:
            continue
        per += list(np.diff(e))
        k = np.arange(len(e))
        fit = np.polyval(np.polyfit(k, e, 1), k)
        tie += list(e - fit)
    per, tie = np.array(per), np.array(tie)
    return per, tie


class Flood(threading.Thread):
    """Background USB traffic until stop(): 'e' commands over CDC, or MIDI messages over ALSA."""

    def __init__(self, kind, midi=None):
        super().__init__(daemon=True)
        self.kind, self.midi, self.go, self.count = kind, midi, True, 0

    def run(self):
        if self.kind == "cdc":
            c = buslib.Bench(cdc_port())
            while self.go:
                c.events(0x90, 60, 100, 0xE0, self.count & 0x7F, 0x40, 0x80, 60, 0)
                self.count += 1
            c.close()
        else:
            while self.go:
                self.midi.write(bytes([0xB0, 1, self.count & 0x7F, 0xE0, self.count & 0x7F, 0x40] * 20))
                self.count += 40

    def stop(self):
        self.go = False
        self.join(5)


def t_jitter(b, seconds=3, captures=4):
    if np is None:
        skip("SYNC jitter", "numpy missing")
        return
    s = bustest.scope()
    s.s.settimeout(30)
    for c in (":RUN", ":CHAN1:SCAL 1", ":TIM:SCAL 2E-3", ":TIM:OFFS 9E-3", ":ACQ:MDEP 10M", ":TRIG:MODE EDGE",
              ":TRIG:EDGE:SOUR CHAN1", ":TRIG:EDGE:SLOP POS", ":TRIG:EDGE:LEV 1.65", ":TRIG:SWE NORM"):
        s.check(c)
    print(f"  scope: 20 ms per capture at {float(s.query(':ACQ:SRAT?')) / 1e6:.0f} MSa/s, {captures} captures per "
          f"condition; SYNC edges interpolated at 1.65 V")
    m, why = open_midi()
    conds = [("no USB traffic", None), ("CDC flood ('e' commands)", "cdc")] + ([("MIDI flood", "midi")] if m else [])
    res = {}
    for name, kind in conds:
        f = Flood(kind, m) if kind else None
        if f:
            f.start()
            time.sleep(0.5)
        s0, l0 = b.status(), b.load(True)
        time.sleep(seconds)
        per, tie = sync_stats(s, captures)
        s1, l1 = b.status(), b.load()
        if f:
            f.stop()
        res[name] = (per, tie, l1)
        print(f"  {name:26s}: period mean {per.mean() * 1e6:.4f} us, std {per.std() * 1e9:.2f} ns, p-p "
              f"{(per.max() - per.min()) * 1e9:.2f} ns ({len(per)} periods); TIE std {tie.std() * 1e9:.2f} ns, p-p "
              f"{(tie.max() - tie.min()) * 1e9:.2f} ns; frame interrupt latency max {l1['irq_max']} us, shortened "
              f"frames {l1['shortened']}, tx_over +{s1['tx_over'] - s0['tx_over']}"
              + (f"; {f.count} {'commands' if kind == 'cdc' else 'MIDI messages'} sent" if f else ""))
    if not m:
        skip("SYNC jitter with a MIDI flood", why)
    for c in (":ACQ:MDEP 50M", ":TRIG:MODE EDGE", ":TRIG:EDGE:SOUR CHAN2", ":TRIG:EDGE:LEV 1.5", ":TRIG:SWE AUTO",
              ":TIM:SCAL 2E-6", ":TIM:OFFS 0", ":RUN"):
        s.write(c)
    base = res["no USB traffic"]
    worst = max(r[1].max() - r[1].min() for r in res.values())
    check("SYNC unaffected by USB", all(abs(r[0].mean() - base[0].mean()) < 2e-9 for r in res.values()) and
          worst < 20e-9 and all(r[2]["irq_max"] < 40 for r in res.values()),
          f"TIE p-p at most {worst * 1e9:.1f} ns in every condition, frame interrupt within "
          f"{max(r[2]['irq_max'] for r in res.values())} us of the edge (budget cut only beyond 40 us)")
    if m:
        m.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tests", nargs="+")
    ap.add_argument("--port", default=None, help="bench port (default: lab.conf, as bustest.py)")
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--seconds", type=int, default=3)
    ap.add_argument("--scope", action="store_true", help="latency: also the marker -> note on the scope")
    a = ap.parse_args()
    b = buslib.Bench(a.port)
    tests = a.tests
    if tests == ["all"]:
        tests = ["enum", "cdc", "inject", "pins", "replug", "reset", "midi", "flood", "latency"]
    for t in tests:
        print(f"--- {t}")
        if t == "enum":
            t_enum(b)
        elif t == "cdc":
            t_cdc(b, a.n or 1000)
        elif t == "pins":
            t_pins(b)
        elif t == "replug":
            t_replug(b, a.n or 5)
        elif t == "reset":
            b = t_reset(b)
        elif t == "inject":
            t_inject(b)
        elif t == "midi":
            t_midi(b)
        elif t == "flood":
            t_flood(b, a.n or 20000)
        elif t == "latency":
            t_latency(b, a.n or 20, a.scope)
        elif t == "jitter":
            t_jitter(b, a.seconds)
        else:
            raise SystemExit(f"unknown test {t}")
    print("controller:", b.status())
    print("usb:", usb_status(b))
    sys.exit(bustest.fails)


if __name__ == "__main__":
    main()
