#!/usr/bin/env python3
"""[2026-10-20] USB host tests of the bench controller (firmware/bench_ctrl built with make USBH=1: a USB-MIDI host on
USBFS, PB6 / PB7, firmware/bench_ctrl/usbhost.h; controller.md 6). Control over the bench port (USART1 over the
WCH-LinkE, as bustest.py), so the tests work while the development board's USB-C is not on the lab PC. Copy
buslib.py, bustest.py, labconf.py and lab.conf next to this file.

  python3 hosttest.py status            # 'H': the host's state and counters, one line
  python3 hosttest.py idle [--seconds 3]   # nothing attached (or the lab PC on the cable): no attach, no SOF, no
                                        # polling; SYNC: frame interrupt latency, shortened frames, tx_over
  python3 hosttest.py pd                # 'h 3': the D+ / D- pull-down probe (USBFS off / device mode / host mode,
                                        # with and without PD_DIS): levels against the GPIO pull-ups and the fall
                                        # times; the ratios give the internal pull-down against an external one
  python3 hosttest.py enum [--wait 5]   # a device on the port: wait for it, print its identity, endpoints and
                                        # descriptors ('h 4'), enumeration time
  python3 hosttest.py loop              # the controller's own USB device (USBD, PA11 / PA12) wired to its host port
                                        # (PB6 / PB7): bustest's notes / patch / ctrl checks with every MIDI message
                                        # sent as a USB-MIDI packet from the device ('I') and received by the host,
                                        # then a burst (none lost), the device -> host latency, a detach / re-attach
                                        # ('u': the USBD pull-up off), the OUT direction ('h 5')
  python3 hosttest.py keys [--seconds 20]  # a USB-MIDI keyboard on the port: play; prints every packet count change,
                                        # the card's gate / pitch and the host's latency counters
  python3 hosttest.py jitter [--seconds 3]   # scope (CH1 = SYNC): period, TIE, frame interrupt latency with the
                                        # host idle and, with the loop wiring, during an 'I' burst
  python3 hosttest.py bus               # bustest.py all with the host build (the bus checks over USART1)

Each test prints PASS / FAIL / SKIP lines; the exit code is the number of failures.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buslib                                            # noqa: E402
import bustest                                           # noqa: E402

check, settle, delta = bustest.check, bustest.settle, bustest.delta
STATES = ["off", "wait", "debounce", "reset", "recover", "enum", "run", "nomidi", "failed", "fault"]


def skip(name, why):
    print(f"SKIP {name}: {why}")


def host(b, clear=False):
    """'H': the host's status line as a dict (numbers as int, ids as hex strings)."""
    b.s.write(b"H" + bytes([1 if clear else 0]))
    w = b.s.readline().decode().split()
    d = {}
    for k, v in zip(w[1::2], w[2::2]):                   # "usbh state 1 ..."
        d[k] = int(v) if v.isdigit() else v
    d["state_name"] = STATES[d["state"]] if d.get("state", 99) < len(STATES) else d.get("state")
    return d


def hcmd(b, op, data=None):
    b.s.write(b"h" + bytes([op]) + (bytes([len(data)]) + bytes(data) if data is not None else b""))
    if op in (3, 4):
        return b.s.readline().decode().strip()
    r = b.s.read(1)
    return r == b"+"


def dev_send(b, data):
    """'I': a USB-MIDI packet on the controller's own MIDI IN endpoint (the USBD device)."""
    b.s.write(b"I" + bytes([len(data)]) + bytes(data))
    r = b.s.read(1)
    if r not in (b"+", b"-"):
        raise IOError(f"'I': {r!r}")
    return r == b"+"


def usb_status(b, clear=False):
    b.s.write(b"U" + bytes([1 if clear else 0]))
    w = b.s.readline().decode().split()
    return {k: (int(v) if v.isdigit() else v) for k, v in zip(w[1::2], w[2::2])}


def show(h, keys):
    return ", ".join(f"{k} {h.get(k)}" for k in keys)


# ------------------------------------------------------------------ tests
def t_status(b):
    h = host(b)
    print(" ".join(f"{k}={v}" for k, v in h.items()))


def t_idle(b, seconds=3):
    h0, l0, s0 = host(b, True), b.load(True), b.status()
    time.sleep(seconds)
    h1, l1, s1 = host(b), b.load(), b.status()
    check("host idle: nothing attached", h1["state_name"] == "wait" and h1["attaches"] == 0 and h1["sofs"] == 0 and
          h1["polls"] == 0, show(h1, ("state_name", "power", "flt", "attaches", "sofs", "polls", "cpu_max")))
    check("SYNC frame engine with the host build", l1["irq_max"] < 40 and l1["shortened"] == 0 and
          s1["tx_over"] == s0["tx_over"], f"{l1['frames']} frames, frame interrupt within {l1['irq_max']} us of the "
          f"edge, shortened {l1['shortened']}, tx_over +{s1['tx_over'] - s0['tx_over']}")


def t_pd(b):
    """'h 3' (usbhost.c usbh_pd_probe). While USBFS owns PB6 / PB7 the GPIO block does not reach the pads, so the
    probe charges a pin with the SIE in reset (pads = GPIO), then takes the SIE out of reset in the condition under
    test and times the pin's fall through whatever pulls it down. Same pin, same capacitance: the times are
    proportional to the pull-down resistance."""
    line = hcmd(b, 3)
    print("  " + line)
    w = line.split()
    tpu, tmax = int(w[w.index("tpu") + 1]), int(w[w.index("tmax") + 1])
    ref = [int(w[w.index("ref") + 1]), int(w[w.index("ref") + 2])]
    res = {}
    for name in ("off", "dev", "devd", "host", "hostd"):
        i = w.index(name)
        r = {"up": w[i + 2], "drv": w[i + 4], "sie": w[i + 6]}
        if w[i + 7] == "fall":
            r["t"] = [int(w[i + 8]), int(w[i + 9])]
        else:
            r["t"] = [int(w[i + 8]), int(w[i + 9])]
            r["io"] = [int(w[i + 11]), int(w[i + 12])]
            r["ok"] = int(w[i + 14])
            r["hc"] = w[i + 16]
        res[name] = r

    def us(x):
        return f"> {tmax / tpu:.0f} us" if x >= tmax else f"{(x - 5) / tpu:.2f} us"
    for name, r in res.items():
        extra = (f"; the SIE pin bit falls in D- {us(r['t'][0])}, D+ {us(r['t'][1])} (GPIO input {us(r['io'][0])}, "
                 f"{us(r['io'][1])}; precharge ok {r['ok']}, HOST_CTRL {r['hc']})" if "io" in r else
                 f"; GPIO pin falls from 3.3 V in D- {us(r['t'][0])}, D+ {us(r['t'][1])}")
        print(f"  {name:5s}: GPIO pull-ups read {r['up']}, driven high read {r['drv']}, SIE pins {r['sie']}{extra}")
    ext = all(x < tmax for x in res["hostd"]["t"])
    ok = True
    for k, pin in enumerate(("D-", "D+")):
        t_on, t_dis = res["host"]["t"][k] - ref[k], res["hostd"]["t"][k] - ref[k]
        if t_on >= tmax:
            ok = False
            print(f"  {pin}: host mode with PD_DIS 0 does not fall: no internal pull-down")
        elif ext:
            ratio = t_on / (t_dis - t_on) if t_dis > t_on else float("inf")
            print(f"  {pin}: PD_DIS 1 falls in {t_dis / tpu:.2f} us (external pull-down alone; GPIO with USBFS off: "
                  f"{(res['off']['t'][k] - ref[k]) / tpu:.2f} us), PD_DIS 0 in {t_on / tpu:.2f} us -> R_int = "
                  f"{ratio:.2f} x R_ext (R_ext = 15 kOhm: {15 * ratio:.1f} kOhm; USB 2.0 allows 14.25-24.8 kOhm "
                  f"for R_ext: {14.25 * ratio:.1f}-{24.8 * ratio:.1f} kOhm)")
            ok = ok and t_on < 0.8 * t_dis
        else:
            print(f"  {pin}: no external pull-down (PD_DIS 1 does not fall within {tmax / tpu:.0f} us); PD_DIS 0 "
                  f"falls in {t_on / tpu:.2f} us (internal pull-down x pin capacitance)")
    check("internal D+ / D- pull-downs in host mode (UH_PD_DIS 0)", ok and res["host"]["hc"] == "00" and
          res["hostd"]["hc"] == "80", "present" if ok else "not found")
    return res


def wait_state(b, states, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = host(b)
        if h["state_name"] in states:
            return h, time.time() - t0
        time.sleep(0.05)
    return host(b), None


def parse_descriptors(hexline):
    w = hexline.split()
    if w[0] != "dev":
        return None, None
    return bytes.fromhex(w[1]), bytes.fromhex(w[3])


def describe_cfg(cfg):
    out, i = [], 0
    names = {2: "config", 4: "interface", 5: "endpoint", 11: "IAD", 0x24: "CS_INTERFACE", 0x25: "CS_ENDPOINT"}
    while i + 2 <= len(cfg) and cfg[i] >= 2:
        d = cfg[i:i + cfg[i]]
        t = d[1]
        s = f"    {names.get(t, hex(t)):12s} {d.hex(' ')}"
        if t == 4 and len(d) >= 9:
            s += f"   (if {d[2]} alt {d[3]}, {d[4]} EPs, class {d[5]:02x}/{d[6]:02x}/{d[7]:02x})"
        elif t == 5 and len(d) >= 7:
            s += (f"   (EP {d[2]:02x} {'IN' if d[2] & 0x80 else 'OUT'} {['ctrl', 'iso', 'bulk', 'int'][d[3] & 3]} "
                  f"{d[4] | d[5] << 8} bytes, interval {d[6]})")
        out.append(s)
        i += cfg[i]
    return "\n".join(out)


def t_enum(b, wait=5):
    h, dt = wait_state(b, ("run", "nomidi", "failed"), wait)
    if dt is None:
        check("enumeration", False, f"no device enumerated within {wait} s: {show(h, ('state_name', 'attaches', 'resets', 'enum_fails', 'last_err', 'last_res', 'xfer_err', 'ctl_naks'))}")
        return h
    check("enumeration", h["state_name"] in ("run", "nomidi"),
          f"{h['state_name']}: {h['vid']}:{h['pid']} '{h['product'].replace('_', ' ')}', "
          f"{'full' if h['speed'] else 'low'} speed, address {h['addr']}, attach -> running {h['enum_ms']} ms, "
          f"{h['enums']} enumeration(s), {h['enum_fails']} failed; MIDI streaming interface {h['ms_if']} alt "
          f"{h['ms_alt']}: IN {h['ep_in']} ({['', '', 'bulk', 'interrupt'][h['in_type']]}, {h['in_size']} bytes, "
          f"every {h['interval']} frame(s)), OUT {h['ep_out']} ({h['out_size']} bytes)")
    dev, cfg = parse_descriptors(hcmd(b, 4))
    if dev:
        print(f"  device descriptor: {dev.hex(' ')}")
        print(f"  configuration descriptor ({len(cfg)} bytes):\n{describe_cfg(cfg)}")
    return h


def packets(m):
    """MIDI bytes -> USB-MIDI event packets, cable 0 (as usbtest.usb_midi_packets, without SysEx)."""
    out, i = bytearray(), 0
    while i < len(m):
        st = m[i]
        n = 2 if st & 0xF0 in (0xC0, 0xD0) else 3
        out += bytes([st >> 4]) + bytes(m[i:i + n]) + bytes(3 - n)
        i += n
    return bytes(out)


class ViaHost:
    """bustest's Bench with every MIDI message (events) sent as a USB-MIDI packet from the controller's own USB device
    ('I', USBD) and received by its USB host (USBFS): the full host path into the bus."""

    def __init__(self, bench):
        self.bench = bench

    def events(self, *m):
        p = packets(list(m))
        for k in range(0, len(p), 64):
            if not dev_send(self.bench, p[k:k + 64]):
                raise IOError("'I': the host did not take the packet within 100 ms")
        time.sleep(0.003)                                # the host polls once per USB frame
        return None

    def __getattr__(self, name):
        return getattr(self.bench, name)


def t_loop(b, n_burst=2000):
    h = t_enum(b, 5)
    if h["state_name"] != "run":
        skip("loop", "no MIDI device running on the host port (wire PA11 -> PB6, PA12 -> PB7, nothing on the USB-C)")
        return
    u = usb_status(b)
    print(f"  the USB device (USBD) as seen by itself: conf {u.get('conf')} addr {u.get('addr')} resets "
          f"{u.get('resets')}")
    v = ViaHost(b)
    h0 = host(b, True)
    bustest.t_notes(v)
    bustest.t_patch(v)
    bustest.t_ctrl(v)
    h1 = host(b)
    check("MIDI through the host port", h1["errors"] == 0 and h1["tog_err"] == 0 and h1["pkts"] > 0,
          f"{h1['pkts']} packets, {h1['events']} events received; errors {h1['errors']}, toggle errors "
          f"{h1['tog_err']}; device -> host {h1['dlat_min']} / {h1['dlat_mean']} / {h1['dlat_max']} us (min / mean / "
          f"max), arrival -> execution frame edge {h1['hlat_min']} / {h1['hlat_mean']} / {h1['hlat_max']} us")
    # burst: notes (no bus overload: one note on / off pair per packet would saturate; use CC 20, unmapped)
    host(b, True)
    c0 = b.counters()
    t0 = time.time()
    sent = 0
    for k in range(n_burst):
        m = []
        for j in range(16):                              # 16 events per packet (64 bytes)
            m += [0xB0, 20, (k * 16 + j) & 0x7F]
        if dev_send(b, packets(m)):
            sent += 16
    dt = time.time() - t0
    time.sleep(0.05)
    h2 = host(b)
    c1 = b.counters()
    check(f"burst of {n_burst} packets ({sent} events)", h2["events"] == sent and h2["errors"] == 0,
          f"{h2['events']} events received in {dt:.1f} s ({sent / dt:.0f} events/s, the bench port's rate: "
          f"{n_burst / dt:.0f} packets/s), errors {h2['errors']}, toggle errors {h2['tog_err']}, ring full "
          f"{h2['ring_full']}, late SOF {h2['late_sof']}; host CPU max {h2['cpu_max']} us per call, "
          f"{h2['cpu_sum'] / max(h2['sofs'], 1):.1f} us per USB frame; card crc +"
          f"{(c1['crc'] - c0['crc']) & 0xFFFF}")
    # fast notes: a note on and off per packet, as fast as the bench port goes
    host(b, True)
    c0 = b.counters()
    for k in range(200):
        n = 48 + k % 24
        dev_send(b, packets([0x90, n, 100, 0x80, n, 0]))
    time.sleep(0.05)
    h3, c1 = host(b), b.counters()
    d = delta(c0, c1, "packets", "crc", "late", "qfull", "slips")
    check("200 note on / off pairs through the host", h3["events"] == 400 and c1["gate"] == 0 and d["crc"] == 0 and
          d["late"] == 0, f"{h3['events']} events, card {d}, gate {c1['gate']}; arrival -> execution edge "
          f"{h3['hlat_min']} / {h3['hlat_mean']} / {h3['hlat_max']} us")
    # OUT: host -> device MIDI OUT endpoint (the device's own path into the bus)
    u0 = usb_status(b)
    ok = hcmd(b, 5, packets([0x90, 60, 100]))
    time.sleep(0.02)
    c = b.counters()
    hcmd(b, 5, packets([0x80, 60, 0]))
    time.sleep(0.02)
    u1, h4 = usb_status(b), host(b)
    check("host OUT -> device", ok and u1["midi_pkts"] - u0["midi_pkts"] == 2 and c["gate"] == 1,
          f"'h 5' {'taken' if ok else 'refused'}, the device received {u1['midi_pkts'] - u0['midi_pkts']} packets, "
          f"gate {c['gate']}; host outs {h4['outs']}")
    # detach / re-attach: the device's pull-up off for 300 ms ('u 0', 'u 1': the main loop keeps running)
    for k in range(3):
        h0 = host(b)
        b.s.write(b"u\x00")
        b._plus()
        t0 = time.time()
        time.sleep(0.3)
        b.s.write(b"u\x01")
        b._plus()
        h, dt = None, None
        while time.time() - t0 < 3:
            h = host(b)
            if h["detaches"] > h0["detaches"] and h["state_name"] == "run" and h["enums"] > h0["enums"]:
                dt = time.time() - t0
                break
            time.sleep(0.02)
        ok = dt is not None and dev_send(b, packets([0x90, 64, 90, 0x80, 64, 0]))
        check(f"detach / re-attach {k + 1}", ok, f"detaches +{h['detaches'] - h0['detaches']}, enums "
              f"+{h['enums'] - h0['enums']}, running again {dt and round(dt, 2)} s after the pull-up went off (300 ms "
              f"off; attach -> running {h['enum_ms']} ms)")
    # a detach the main loop does not see while it happens ('u 30' blocks it for the 300 ms)
    h0 = host(b)
    b.s.write(b"u" + bytes([30]))
    b._plus()
    t0 = time.time()
    while time.time() - t0 < 3:
        h = host(b)
        if h["detaches"] > h0["detaches"] and h["enums"] > h0["enums"] and h["state_name"] == "run":
            break
        time.sleep(0.02)
    check("detach while the main loop is blocked", h["detaches"] > h0["detaches"] and h["enums"] > h0["enums"] and
          h["state_name"] == "run", f"detaches +{h['detaches'] - h0['detaches']}, enums +{h['enums'] - h0['enums']}")


def t_jitter(b, seconds=3, captures=4):
    """Scope (CH1 = SYNC, as usbtest.py jitter): SYNC period and time interval error, the frame interrupt's latency,
    with the host idle and (when a MIDI device runs on the port, the loop wiring) during a burst of 'I' packets."""
    import threading
    import usbtest
    if usbtest.np is None:
        skip("SYNC jitter", "numpy missing")
        return
    s = bustest.scope()
    s.s.settimeout(30)
    for c in (":RUN", ":CHAN1:SCAL 1", ":TIM:SCAL 2E-3", ":TIM:OFFS 9E-3", ":ACQ:MDEP 10M", ":TRIG:MODE EDGE",
              ":TRIG:EDGE:SOUR CHAN1", ":TRIG:EDGE:SLOP POS", ":TRIG:EDGE:LEV 1.65", ":TRIG:SWE NORM"):
        s.check(c)
    h = host(b)
    conds = [("host " + h["state_name"], False)] + ([("host polling, 'I' burst", True)] if h["state_name"] == "run"
                                                     else [])
    res = []
    for name, burst in conds:
        go, cnt = [True], [0]

        def run():
            p = packets([0xB0, 20, 1] * 16)
            while go[0]:
                dev_send(b, p)
                cnt[0] += 1
        th = threading.Thread(target=run, daemon=True) if burst else None
        s0, l0 = b.status(), b.load(True)
        host(b, True)
        if th:
            th.start()
        time.sleep(0.3)
        t0 = time.time()
        while time.time() - t0 < seconds:
            time.sleep(0.1)
        per, tie = usbtest.sync_stats(s, captures)
        go[0] = False
        if th:
            th.join(5)
        s1, l1, h1 = b.status(), b.load(), host(b)
        res.append((per, tie, l1))
        print(f"  {name:28s}: period mean {per.mean() * 1e6:.4f} us, p-p {(per.max() - per.min()) * 1e9:.2f} ns "
              f"({len(per)} periods); TIE p-p {(tie.max() - tie.min()) * 1e9:.2f} ns; frame interrupt max "
              f"{l1['irq_max']} us, shortened {l1['shortened']}, tx_over +{s1['tx_over'] - s0['tx_over']}; host "
              f"{h1['pkts']} packets, cpu_max {h1['cpu_max']} us" + (f"; {cnt[0]} 'I' packets" if burst else ""))
    for c in (":ACQ:MDEP 50M", ":TRIG:EDGE:SOUR CHAN2", ":TRIG:EDGE:LEV 1.5", ":TRIG:SWE AUTO", ":TIM:SCAL 2E-6",
              ":TIM:OFFS 0", ":RUN"):
        s.write(c)
    worst = max(r[1].max() - r[1].min() for r in res)
    check("SYNC unaffected by the USB host", worst < 20e-9 and all(r[2]["irq_max"] < 40 for r in res),
          f"TIE p-p at most {worst * 1e9:.1f} ns, frame interrupt within {max(r[2]['irq_max'] for r in res)} us")


def t_keys(b, seconds=20):
    h = host(b, True)
    if h["state_name"] != "run":
        skip("keys", f"no MIDI device running (state {h['state_name']})")
        return
    print(f"  play on '{h['product'].replace('_', ' ')}' for {seconds} s ...")
    t0, last = time.time(), None
    gates, pitches = set(), set()
    while time.time() - t0 < seconds:
        hh = host(b)
        c = b.counters()
        gates.add(c["gate"])
        pitches.add(c["pitch"] >> 8)
        cur = (hh["pkts"], hh["events"], c["gate"], c["pitch"])
        if cur != last:
            print(f"  {time.time() - t0:5.1f} s: packets {hh['pkts']} events {hh['events']} sysex {hh['sysex']}; card "
                  f"gate {c['gate']} note {c['pitch'] >> 8}; arrival -> execution {hh['hlat_min']} / "
                  f"{hh['hlat_mean']} / {hh['hlat_max']} us")
            last = cur
        time.sleep(0.05)
    h = host(b)
    check("keyboard -> card", h["events"] > 0 and 1 in gates and 0 in gates and h["errors"] == 0,
          f"{h['pkts']} packets, {h['events']} events, notes seen {sorted(pitches)}, gate seen {sorted(gates)}, "
          f"errors {h['errors']}, toggle errors {h['tog_err']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tests", nargs="+")
    ap.add_argument("--port", default=None)
    ap.add_argument("--seconds", type=int, default=None)
    ap.add_argument("--wait", type=float, default=5)
    ap.add_argument("--n", type=int, default=2000)
    a = ap.parse_args()
    b = buslib.Bench(a.port)
    for t in a.tests:
        print(f"--- {t}")
        if t == "status":
            t_status(b)
        elif t == "idle":
            t_idle(b, a.seconds or 3)
        elif t == "pd":
            t_pd(b)
        elif t == "enum":
            t_enum(b, a.wait)
        elif t == "loop":
            t_loop(b, a.n)
        elif t == "jitter":
            t_jitter(b, a.seconds or 3)
        elif t == "keys":
            t_keys(b, a.seconds or 20)
        elif t == "bus":
            b.close()
            os.system(f"{sys.executable} {os.path.join(HERE, 'bustest.py')} all")
            b = buslib.Bench(a.port)
        else:
            raise SystemExit(f"unknown test {t}")
    print("host:", " ".join(f"{k}={v}" for k, v in host(b).items()))
    sys.exit(bustest.fails)


if __name__ == "__main__":
    main()
