"""Voice bus (docs/bus.md) on the bench: packet coding and the bench controller's PC commands (firmware/bench_ctrl).

The bench controller (CH32V203) shares its USART1 between the Ardulink SWIO bridge (minichlink -C ardulink) and the
bus commands below, so a test must not run while minichlink talks to the same port.

  bench = Bench()                      # port from tools/lab.conf (BENCH_PORT, else the LinkE serial LINKE_V203)
  fx = bench.events(0x90, 60, 100)     # MIDI note on -> NOTE_ON for voice 0, returns the execution frame
  c = bench.counters()                 # the card's counters (REQUEST COUNTERS over the return line)
  bench.voices(8, V_PARTS)             # [2026-10-19] load tests: voices 1-7 virtual (no card answers for them)
  bench.gen(chord=8, every=200, ctrl=G_BEND | G_WHEEL | G_CUTOFF, cevery=5)   # the controller's load generator
  l = bench.load(clear=True)           # bus load: bytes per frame, frames at the budget, late packets
"""
import struct
import time

try:
    import labconf
except ImportError:                                      # run from another directory
    labconf = None

# message types (bus.md 5)
FRAME, CONFIG, ASSIGN = 0x01, 0x02, 0x03
NOTE_ON, NOTE_OFF, PITCH, VOICE_STATE = 0x10, 0x11, 0x12, 0x13
CTRL, PARAM, PATCH_DATA, PATCH_SELECT, PATCH_PRESET = 0x20, 0x21, 0x22, 0x23, 0x24
REQUEST, CALIBRATE = 0x30, 0x31
HELLO, STATUS, CAL_DATA, COUNTERS = 0x80, 0x81, 0x82, 0x83
R_STATUS, R_CAL_DATA, R_HELLO, R_COUNTERS = 0, 1, 2, 3
MULTI = 0x40                                             # type flag: one record per voice in dst (bus.md 5.1)

# bench controller 'V' flags and generator controllers (firmware/bench_ctrl)
V_PARTS, V_RESERVE, V_PHASE, V_MULTI, V_PRIO = 1, 2, 4, 8, 16
G_BEND, G_WHEEL, G_CUTOFF, G_RES, G_EXPR, G_VOL = 1, 2, 4, 8, 16, 32

COUNTER_NAMES = ["rx_bytes", "packets", "crc", "framing", "uart", "late", "far", "qfull", "slips", "late_ticks",
                 "underruns", "sync_gaps", "repairs", "replies", "other", "glitches", "frame", "tick_run_max",
                 "stack_free"]
BUS_STATES = ["standalone", "trim", "listen", "synced", "lost"]


def crc8(data):
    """CRC-8, polynomial 0x07, initial value 0, MSB first, no final XOR (bus.md 4)."""
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def cobs_encode(data):
    out, block = bytearray(), bytearray()
    for b in data:
        if b:
            block.append(b)
            if len(block) == 254:
                out += bytes([255]) + block
                block = bytearray()
        else:
            out += bytes([len(block) + 1]) + block
            block = bytearray()
    out += bytes([len(block) + 1]) + block
    return bytes(out)


def cobs_decode(data):
    out, i = bytearray(), 0
    while i < len(data):
        code = data[i]
        if code == 0 or i + code > len(data):
            raise ValueError("bad COBS")
        out += data[i + 1:i + code]
        i += code
        if code < 255 and i < len(data):
            out.append(0)
    return bytes(out)


def packet(body, corrupt=False):
    """Encoded packet with its delimiter: COBS(body crc8) 0x00; body = dst type [frame] payload."""
    c = crc8(body) ^ (0x5A if corrupt else 0)
    return cobs_encode(bytes(body) + bytes([c])) + b"\0"


def bench_port():
    if labconf is None:
        raise SystemExit("tools/labconf.py not found")
    p = labconf.get("BENCH_PORT", "")
    if p:
        return p
    return f"/dev/serial/by-id/usb-wch.cn_WCH-Link_{labconf.get('LINKE_V203')}-if01"


class Bench:
    """The bench controller's bus commands (firmware/bench_ctrl/bench_ctrl.c)."""

    def __init__(self, port=None, timeout=1.0):
        import serial                                    # pyserial
        self.s = serial.Serial(port or bench_port(), 115200, timeout=timeout)
        self.s.reset_input_buffer()
        self.s.write(b"?")
        if self.s.read(1) != b"!":
            raise IOError("bench controller: no sync")

    def close(self):
        self.s.close()

    def _read(self, n):
        b = self.s.read(n)
        if len(b) != n:
            raise IOError(f"bench controller: {len(b)} of {n} bytes")
        return b

    def _plus16(self):
        b = self._read(3)
        if b[:1] != b"+":
            raise IOError(f"bench controller: {b!r}")
        return b[1] | b[2] << 8

    def _plus(self):
        if self._read(1) != b"+":
            raise IOError("bench controller: no '+'")

    def raw(self, data):
        """Raw bytes onto the bus (one unit in the next frame); returns when they are sent."""
        self.s.write(b"m" + bytes([len(data)]) + bytes(data))
        self._plus()

    def events(self, *midi):
        """MIDI bytes -> bus events for voice 0, all for frame + L; returns that execution frame."""
        self.s.write(b"e" + bytes([len(midi)]) + bytes(midi))
        return self._plus16()

    def body(self, dst, mtype, payload=b"", lead=None, corrupt=False):
        """One packet (the controller adds CRC and COBS); lead: timed, frame byte = frame + lead."""
        fl = (0x80 | (lead & 0x3F) if lead is not None else 0) | (0x40 if corrupt else 0)
        b = bytes([dst, mtype]) + bytes(payload)
        self.s.write(b"b" + bytes([len(b), fl]) + b)
        return self._plus16()

    def request(self, what, arg=0):
        """REQUEST to voice 0; the reply (src type payload) or None."""
        self.s.write(b"R" + bytes([what, arg]))
        n = self._read(1)[0]
        return self._read(n) if n else None

    def status(self):
        """The controller's status line as a dict."""
        self.s.write(b"S")
        line = self.s.readline().decode().split()
        return {k: (int(v) if v.isdigit() else v) for k, v in zip(line[::2], line[1::2])}

    def config(self, d, lead):
        self.s.write(b"c" + bytes([d, lead]))
        self._plus()

    def marker(self, mode):
        """SYNC marker: 0 off, 1 execution frame, 2 transmit frame (that frame's SYNC pulse 0.2 ms)."""
        self.s.write(b"k" + bytes([mode]))
        self._plus()

    def refresh(self, on):
        self.s.write(b"v" + bytes([1 if on else 0]))
        self._plus()

    def corrupt(self, n):
        """Corrupt the CRC of the next n packets made by events()."""
        self.s.write(b"f" + bytes([n]))
        self._plus()

    def sync_gap(self, n):
        """Leave out the next n SYNC rising edges (the FRAME packets continue)."""
        self.s.write(b"g" + struct.pack("<H", n))
        self._plus()

    def enumerate(self):
        self.s.write(b"n")
        self._plus()

    # replies
    def hello(self):
        r = self.request(R_HELLO)
        if not r or r[1] != HELLO:
            return None
        u1, u2, fw, caps = struct.unpack("<IIHB", r[2:13])
        return {"src": r[0], "uid": f"{u1:08x}-{u2:08x}", "fw": fw, "caps": caps}

    def card_status(self):
        r = self.request(R_STATUS)
        if not r or r[1] != STATUS:
            return None
        p = r[2:]
        d = {"src": r[0], "flags": p[0], "hsitrim": p[1], "ppm": struct.unpack("<h", p[2:4])[0], "crc": p[4],
             "late": p[5], "slips": p[6], "late_ticks": p[7], "underruns": p[8], "load": p[9]}
        if len(p) > 10:
            d["state"] = BUS_STATES[p[10]] if p[10] < len(BUS_STATES) else p[10]
        return d

    def counters(self, clear=False):
        r = self.request(R_COUNTERS, 1 if clear else 0)
        if not r or r[1] != COUNTERS:
            return None
        p = r[2:]
        n = len(COUNTER_NAMES)
        d = dict(zip(COUNTER_NAMES, struct.unpack(f"<{n}H", p[:2 * n])))
        if len(p) >= 2 * n + 4:
            d["gate"], d["preset"], d["slot"], d["delay"] = p[2 * n:2 * n + 4]
        if len(p) >= 2 * n + 6:
            d["pitch"] = struct.unpack("<H", p[2 * n + 4:2 * n + 6])[0]
        if len(p) >= 2 * n + 10:
            d["fill_max"], d["slack_min"] = struct.unpack("<HH", p[2 * n + 6:2 * n + 10])
        if len(p) >= 2 * n + 18:
            d["parse_avg"], d["parse_max"], d["rx_max"], d["foreign"] = struct.unpack("<4H", p[2 * n + 10:2 * n + 18])
        if len(p) >= 2 * n + 20:
            d["tick_core_max"] = struct.unpack("<H", p[2 * n + 18:2 * n + 20])[0]
        d["src"] = r[0]
        return d

    # [2026-10-19] load tests
    def voices(self, n, flags=0):
        """n voices (voice 0 = the card, 1 ... n - 1 virtual), flags V_*; all notes off."""
        self.s.write(b"V" + bytes([n, flags]))
        self._plus()

    def refresh_periods(self, vs=0, pp=200, pd=0):
        """Frames per VOICE_STATE (0: auto), PATCH_PRESET and PATCH_DATA packet (0: off)."""
        self.s.write(b"T" + struct.pack("<BHH", vs, pp, pd))
        self._plus()

    def gen(self, chord=0, every=0, hold=0, ctrl=0, cevery=0):
        """Load generator: a chord of `chord` notes every `every` frames (released after `hold`; 0: legato),
        a step of the controllers `ctrl` (G_*) every `cevery` frames; all 0: off."""
        self.s.write(b"G" + struct.pack("<BHHBH", chord, every, hold, ctrl, cevery))
        self._plus()

    def load(self, clear=False):
        """The controller's bus load counters (since the last clear) as a dict; hist: frames per 10 bytes."""
        self.s.write(b"L" + bytes([1 if clear else 0]))
        line = self.s.readline().decode().split()
        d = {k: int(v) for k, v in zip(line[::2], line[1::2]) if k != "hist"}
        d["hist"] = [int(x) for x in line[line.index("hist") + 1].split(",")]
        return d

    def wait_frames(self, n):
        time.sleep(n / 1000.0 + 0.02)
