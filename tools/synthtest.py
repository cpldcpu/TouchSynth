#!/usr/bin/env python3
"""Host side of the TouchSynth test console: runs `minichlink -T` and sends console commands (Linux).

  python3 synthtest.py id status "touch"
  python3 synthtest.py --wait 3 "cap 512 20"
  python3 synthtest.py --log 150 touch status      # repeat the commands for 150 s, timestamped

minichlink's terminal mode needs a terminal on stdin (on a pipe it sees end-of-file at once), and it switches to
an interactive line editor when stdout is a terminal. So stdin gets a pseudo-terminal and stdout a plain pipe.
Each command is sent as one line; the output is collected until the console has been quiet for --idle seconds
(or --wait seconds have passed) and printed. Lines that minichlink prints itself are dropped unless -v.
"""
import argparse, os, pty, select, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
try:                                                     # tools/lab.conf (gitignored), else the ch32fun build
    import labconf
    DEFAULT_MCL = labconf.get("MINICHLINK", os.path.join(HERE, "..", "ch32fun", "minichlink", "minichlink"))
except ImportError:
    DEFAULT_MCL = os.environ.get("MINICHLINK", os.path.join(HERE, "..", "ch32fun", "minichlink", "minichlink"))
BANNER = ("minichlink version", "Found WCH Link", "WCH Programmer", "Detected CH32", "Flash Storage", "Part UUID",
          "Part Type", "Read protection", "Interface Setup", "Terminal started", "USER/RDPR", "DATA1/DATA0", "WRPR", "R32_ESIG")


def collect(proc, wait, idle):
    out, t0, last = b"", time.time(), time.time()
    while time.time() - t0 < wait:
        r, _, _ = select.select([proc.stdout], [], [], 0.05)
        if r:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            out += chunk
            last = time.time()
        elif out and time.time() - last > idle:
            break
    return out.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commands", nargs="*")
    ap.add_argument("--mcl", default=DEFAULT_MCL, help="minichlink binary")
    ap.add_argument("--wait", type=float, default=2.0, help="max seconds per command")
    ap.add_argument("--idle", type=float, default=0.4, help="seconds of silence that end a reply")
    ap.add_argument("-v", action="store_true", help="also show minichlink's own messages")
    ap.add_argument("--log", type=float, default=0, help="repeat the command list for this many seconds")
    ap.add_argument("--hold", type=float, default=0,
                    help="keep the session open this long after the commands (disconnecting resets the MCU)")
    ap.add_argument("--poll", default="", help="command to repeat about once a second during --hold")
    a = ap.parse_args()

    master, slave = pty.openpty()
    proc = subprocess.Popen([a.mcl, "-T"], stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    os.close(slave)
    try:
        head = collect(proc, 4.0, 1.0)                      # connect banner
        if a.v:
            sys.stdout.write(head)
        if "Detected" not in head:
            sys.stdout.write(head)
            sys.exit("synthtest: no target found")
        t0 = time.time()
        while True:
            for cmd in a.commands:
                os.write(master, (cmd + "\n").encode())
                w = a.wait
                if cmd.startswith("wait "):                  # the firmware is busy for that long: sending the next
                    w = max(w, int(cmd.split()[1]) / 1000 + 1.0)   # command earlier garbles it
                reply = collect(proc, w, a.idle)
                lines = [l for l in reply.splitlines() if l.strip() and (a.v or not l.startswith(BANNER))]
                print(f"> {cmd}" + (f"  t={time.time() - t0:.2f}" if a.log else ""))
                print("\n".join(lines), flush=True)
            if time.time() - t0 >= a.log:
                break
        if a.hold:
            t1 = time.time()
            while time.time() - t1 < a.hold:
                if a.poll:                                  # e.g. --poll status: watch the firmware meanwhile
                    os.write(master, (a.poll + "\n").encode())
                    reply = collect(proc, 1.0, 0.3)
                    lines = [l for l in reply.splitlines() if l.strip() and not l.startswith(BANNER)]
                    print(f"t={time.time() - t0:6.1f} " + " | ".join(lines), flush=True)
                    time.sleep(0.5)
                else:
                    collect(proc, a.hold, a.hold)
                    break
    finally:
        proc.terminate()
        try:
            proc.wait(2)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
