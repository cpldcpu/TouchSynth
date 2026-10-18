#!/usr/bin/env python3
"""Minimal SCPI access to the Rigol MSO5074 (LAN, port 5555), run on the Linux host next to it.

  python3 scope.py query ":MEAS:ITEM? VPP,CHAN1"
  python3 scope.py wave out.csv [CHAN1]      # screen waveform (NORM mode, 1000 points) as t, v CSV
  python3 scope.py png shot.png              # screenshot
"""
import os, socket, sys, time
import labconf

HOST = labconf.get("SCOPE_HOST")                         # tools/lab.conf (gitignored)


class Scope:
    def __init__(self, host=HOST):
        self.s = socket.create_connection((host, 5555), timeout=10)

    def write(self, cmd):
        self.s.sendall((cmd + "\n").encode())

    def query(self, cmd):
        self.write(cmd)
        buf = b""
        while not buf.endswith(b"\n"):
            buf += self.s.recv(65536)
        return buf.decode().strip()

    def block(self, cmd):
        """IEEE 488.2 definite-length block (#NDDDD...)."""
        self.write(cmd)
        head = b""
        while len(head) < 2:
            head += self.s.recv(2 - len(head))
        nd = int(head[1:2])
        while len(head) < 2 + nd:
            head += self.s.recv(2 + nd - len(head))
        n = int(head[2:2 + nd])
        data = b""
        while len(data) < n:
            data += self.s.recv(n - len(data))
        self.s.recv(1)                                  # trailing newline
        return data

    def wave(self, ch="CHAN1"):
        self.write(f":WAV:SOUR {ch}")
        self.write(":WAV:MODE NORM")
        self.write(":WAV:FORM BYTE")
        pre = self.query(":WAV:PRE?").split(",")
        xinc, xorg, yinc, yorg, yref = float(pre[4]), float(pre[5]), float(pre[7]), float(pre[8]), float(pre[9])
        raw = self.block(":WAV:DATA?")
        return [(xorg + i * xinc, (b - yorg - yref) * yinc) for i, b in enumerate(raw)]


    def check(self, cmd):
        self.write(cmd)
        err = self.query(":SYST:ERR?")
        if not err.startswith("0"):
            raise RuntimeError(f"{cmd}: {err}")

    def record(self, seconds, ch="CHAN1", scale=0.2, start_cb=None, target_rate=100e3, trig_level=None):
        """Single-shot capture over `seconds` (10 divisions, 50 Mpts, normal acquisition: the MSO5074 stores 8 bit
        even in HRES mode, so resolution comes from oversampling + decimation instead; HRES would remove the noise
        that dithers the 8-bit steps). start_cb() runs right after arming. The record is read as 8-bit blocks of
        exactly announced length (WORD transfers on this firmware send more bytes than announced and desync the
        socket) and boxcar-decimated to about target_rate. Returns (rate, numpy float32 volts, preamble)."""
        import numpy as np
        self.s.settimeout(20)
        self.write(":RUN")
        time.sleep(0.5)
        for c in (":ACQ:TYPE NORM", f":{ch}:SCAL {scale}", f":{ch}:OFFS 0", f":{ch}:COUP AC", f":{ch}:BWL 20M",
                  f":TIM:SCAL {seconds / 10}", f":TIM:OFFS {seconds / 2}", ":ACQ:MDEP 50M", ":TRIG:SWE AUTO"):
            self.check(c)
        if trig_level is not None:                              # trigger on the part's sync pulse (a falling
            for c in (":TRIG:MODE EDGE", f":TRIG:EDGE:SOUR {ch}",  # step at trim 128): at slow timebases the
                      ":TRIG:EDGE:SLOP NEG", f":TRIG:EDGE:LEV {trig_level}", ":TRIG:SWE NORM"):  # scope only
                self.check(c)                                   # starts on a real trigger crossing
        time.sleep(0.5)
        mem_s = float(self.query(":ACQ:MDEP?")) / float(self.query(":ACQ:SRAT?"))
        pre_s = max(0.0, (mem_s - seconds) / 2)                 # memory beyond the screen is split around it
        self.write(":SING")
        if trig_level is not None and pre_s > 0:                # the scope only triggers once the pre-trigger
            time.sleep(pre_s + 1.0)                             # memory is full: start the part (and its sync
        t0 = time.time()                                        # pulse) only then
        while True:                                             # arming a 50 Mpts single shot takes a moment; a
            st = self.query(":TRIG:STAT?")                      # force sent earlier is ignored. At slow timebases
            if st in ("WAIT", "TD", "RUN"):                     # (>= ~10 s/div) it acquires at once (TD -> RUN)
                break
            time.sleep(0.2)
            if time.time() - t0 > 20:
                raise RuntimeError(f"scope did not arm ({st})")
        if start_cb:
            start_cb()
        time.sleep(0.3)
        if st == "WAIT" and trig_level is None:
            self.write(":TFOR")                                 # single shot waits for a real trigger even in AUTO
        t0 = time.time()
        while self.query(":TRIG:STAT?") != "STOP":
            time.sleep(1.0)
            if time.time() - t0 > seconds * 2 + 200:
                raise RuntimeError("capture did not finish")
        srate = float(self.query(":ACQ:SRAT?"))
        if trig_level is not None:                              # restore the user's trigger setup
            for c in (":TRIG:EDGE:SLOP POS", ":TRIG:EDGE:LEV 0.198", ":TRIG:SWE AUTO"):
                self.write(c)
        for c in (f":WAV:SOUR {ch}", ":WAV:MODE RAW", ":WAV:FORM BYTE"):
            self.check(c)
        npts = int(float(self.query(":ACQ:MDEP?")))             # the preamble's point count follows the last
        self.write(":WAV:STAR 1")                               # STAR/STOP window, so set the full range first
        self.write(f":WAV:STOP {npts}")
        pre = self.query(":WAV:PRE?").split(",")
        yinc, yorg, yref = float(pre[7]), float(pre[8]), float(pre[9])
        dec = max(1, int(round(srate / target_rate)))
        step = 250000 - 250000 % dec
        out = []
        for a in range(1, npts + 1, step):
            b = min(npts, a + step - 1)
            self.write(f":WAV:STAR {a}")
            self.write(f":WAV:STOP {b}")
            x = np.frombuffer(self.block(":WAV:DATA?"), np.uint8).astype(np.float32)
            n = len(x) - len(x) % dec
            out.append(((x[:n].reshape(-1, dec).mean(1) - yorg - yref) * yinc).astype(np.float32))
        return srate / dec, np.concatenate(out), pre


def main():
    sc = Scope()
    if sys.argv[1] == "query":
        for q in sys.argv[2:]:
            print(q, sc.query(q) if q.endswith("?") or "?" in q else (sc.write(q) or "sent"))
    elif sys.argv[1] == "write":
        for c in sys.argv[2:]:
            sc.write(c)
            time.sleep(0.1)
    elif sys.argv[1] == "wave":
        pts = sc.wave(sys.argv[3] if len(sys.argv) > 3 else "CHAN1")
        with open(sys.argv[2], "w") as fh:
            fh.write("t_s,v\n")
            for t, v in pts:
                fh.write(f"{t:.9g},{v:.6g}\n")
        print(len(pts), "points")
    elif sys.argv[1] == "record":                      # record <out.f32> <seconds> [console cmds...]
        import subprocess
        out, secs = sys.argv[2], float(sys.argv[3])
        cmds = sys.argv[4:]
        log = open(out + ".log", "w")                       # console log incl. a status poll during the capture
        cb = (lambda: subprocess.Popen(["python3", "synthtest.py", "--wait", "1", "--hold", str(secs + 15),
                                        "--poll", "status"] + cmds,
                                       env=dict(os.environ, MINICHLINK=labconf.get("MINICHLINK", "ch32fun/minichlink/minichlink")),
                                       stdout=log)) if cmds else None
        t = time.time()
        lvl = float(os.environ["TRIG"]) if os.environ.get("TRIG") else None
        rate, v, pre = sc.record(secs, start_cb=cb, trig_level=lvl)
        v.tofile(out)
        open(out + ".txt", "w").write(f"{rate}\n")
        print(f"{len(v)} samples at {rate:g} Sa/s -> {out} ({time.time() - t:.0f} s); preamble {','.join(pre)}")
    elif sys.argv[1] == "png":
        open(sys.argv[2], "wb").write(sc.block(":DISP:DATA? PNG"))
        print("saved", sys.argv[2])


if __name__ == "__main__":
    main()
