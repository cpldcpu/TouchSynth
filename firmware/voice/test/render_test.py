#!/usr/bin/env python3
"""Bit-exactness test of the DAC renderer (dsp.c) on the host (WSL gcc, x86): builds test/render_test.c against the
working tree's dsp.c and against a reference revision's (git show), plays the same scenarios through both (all DSP
patches of tables.h plus test patches with other pulse widths, levels and offsets; held notes over the whole range,
vibrato, glides with gate and phase resets, pitch lock, immediate states, modal strikes) and compares the duty codes
per carrier period. Differences are reported as maximum and rms error in DAC codes and as the error's level in the
audio band (re the signal and re full scale). Prints the hashes of the render check (dsp_check.h) per patch: the
card's console command `check <patch>` must print the same (the target build renders what the host compared).

  python3 test/render_test.py [--ref 9294199] [--dual] [--keep DIR]      (in firmware/voice, WSL)
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
FILES = ("dsp.c", "dsp.h", "hw.h", "board.h", "synth.h", "tables.h")
# test patches (appended to tables.h): (wave 0 saw / 1 pulse, level Q15, offset 1/256 semitone) ..., pulse width
TEST_PATCHES = (
    (((1, 32000, 0),), 37),
    (((1, 16000, 0), (0, 16000, 700)), 0),
    (((1, 10900, 0), (0, 10900, -3072), (0, 10900, 3072)), 255),
    (((1, 10000, 0), (1, 10000, 5), (1, 10000, -1200)), 200),
    (((0, 32767, 0),), 128),
    (((0, 10000, 0), (0, 10000, 7), (0, 10000, -1205)), 128),
)
FS, ARR, K_DUAL = 187500, 128, 31309 / 256


def sources(dst, ref):
    os.makedirs(dst)
    for f in FILES:
        if ref:
            txt = subprocess.run(["git", "show", f"{ref}:firmware/voice/{f}"], cwd=SRC, check=True,
                                 capture_output=True, text=True).stdout
        else:
            txt = open(os.path.join(SRC, f)).read()
        if f == "tables.h":
            txt = add_patches(txt)
        open(os.path.join(dst, f), "w").write(txt)
    shutil.copy(os.path.join(SRC, "dsp_check.h"), dst)  # the working tree's check scenario for both


def add_patches(txt):
    m_osc = re.search(r"#define DSP_OSC_TABLE \{(.*)\}\s*$", txt, re.M)
    m_pat = re.search(r"#define DSP_PATCH_TABLE \{(.*)\}\s*$", txt, re.M)
    first = len(re.findall(r"\{[^{}]*\}", m_osc.group(1)))
    oscs, pats = [], []
    for osc, pw in TEST_PATCHES:
        pats.append(f"{{ {first}, {len(osc)}, {pw}, 0, 0, 1 }}")
        oscs += [f"{{ {w}, {l}, {o} }}" for w, l, o in osc]
        first += len(osc)
    txt = txt.replace(m_osc.group(0), f"#define DSP_OSC_TABLE {{{m_osc.group(1).rstrip()}, {', '.join(oscs)} }}")
    return txt.replace(m_pat.group(0), f"#define DSP_PATCH_TABLE {{{m_pat.group(1).rstrip()}, {', '.join(pats)} }}")


def patch_kinds(build):
    txt = open(os.path.join(build, "tables.h")).read()
    body = re.search(r"#define DSP_PATCH_TABLE \{(.*)\}\s*$", txt, re.M).group(1)
    kinds = [int(e.split(",")[-1]) for e in re.findall(r"\{([^{}]*)\}", body)]
    osc = [i + 1 for i, k in enumerate(kinds) if k == 1]
    modal = [i + 1 for i, k in enumerate(kinds) if k == 0]
    return osc, modal


def build_run(tmp, name, ref, dual):
    b = os.path.join(tmp, name)
    sources(b, ref)
    exe = os.path.join(b, "render_test")
    subprocess.run(["gcc", "-O2", "-std=gnu11", "-Wall", "-Wno-unused-function", "-Wno-unused-variable",
                    "-DCH32V006", "-DBOARD_CARD=1", f"-DDAC_DUAL={int(dual)}", "-iquote", b, "-I",
                    os.path.join(HERE, "stub"), "-o", exe, os.path.join(HERE, "render_test.c"),
                    os.path.join(b, "dsp.c")], check=True)
    osc, modal = patch_kinds(b)
    out = os.path.join(b, "out")
    os.makedirs(out)
    checks = subprocess.run([exe, out, ",".join(map(str, osc)), ",".join(map(str, modal))], check=True,
                            capture_output=True, text=True).stdout.splitlines()
    return out, [c for c in checks if c]


def codes(raw, dual):
    a = np.frombuffer(raw, np.uint8).astype(float)
    if not dual:
        return a
    a = a.reshape(-1, 3)
    return a[:, 0] + a[:, 2] / K_DUAL


def band_db(x, ref, lo=20, hi=20000):
    """Power of x in lo...hi Hz re the power of ref (Hann window)."""
    w = np.hanning(len(x))
    f = np.fft.rfftfreq(len(x), 1 / FS)
    sel = (f >= lo) & (f <= hi)
    px = np.sum(np.abs(np.fft.rfft(x * w))[sel] ** 2)
    pr = np.sum(np.abs(np.fft.rfft(ref * w))[sel] ** 2)
    return 10 * np.log10(px / pr) if px > 0 and pr > 0 else -np.inf


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="9294199", help="reference revision (git)")
    ap.add_argument("--dual", action="store_true", help="the dual-PWM build (DAC_DUAL=1)")
    ap.add_argument("--keep", default=None, help="keep the builds and outputs in this directory")
    a = ap.parse_args()
    tmp = a.keep or tempfile.mkdtemp(prefix="render_test_")
    if a.keep and os.path.exists(tmp):
        shutil.rmtree(tmp)
    try:
        ro, _ = build_run(tmp, "ref", a.ref, a.dual)
        co, cc = build_run(tmp, "cur", None, a.dual)
        names = sorted(os.listdir(ro))
        diff = 0
        for n in names:
            r = open(os.path.join(ro, n), "rb").read()
            c = open(os.path.join(co, n), "rb").read() if os.path.exists(os.path.join(co, n)) else b""
            if r == c:
                print(f"  {n[:-4]:24s} {len(r) // (3 if a.dual else 1):7d} periods  identical")
                continue
            diff += 1
            if len(r) != len(c):
                print(f"  {n[:-4]:24s} length {len(r)} != {len(c)}")
                continue
            x, y = codes(r, a.dual), codes(c, a.dual)
            e = y - x
            fs_ref = np.full(len(x), 0.0) + np.sin(2 * np.pi * 1000 * np.arange(len(x)) / FS) * ARR / 2
            print(f"  {n[:-4]:24s} {len(x):7d} periods  DIFFERS: {np.count_nonzero(e)} periods, max "
                  f"{np.max(np.abs(e)):.3f} codes, rms {np.sqrt(np.mean(e ** 2)):.4f}; error in 20 Hz-20 kHz "
                  f"{band_db(e, x - x.mean()):.1f} dB re signal, {band_db(e, fs_ref):.1f} dB re full scale")
        for c in cc:                                   # the console's 'check <patch>' (dsp_check.h) on the card
            print(f"  {c}")
        print(f"{len(names)} scenarios, {diff} differ ({'dual' if a.dual else 'single'} PWM, reference {a.ref})")
        sys.exit(1 if diff else 0)
    finally:
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
