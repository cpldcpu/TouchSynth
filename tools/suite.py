#!/usr/bin/env python3
"""'Space Toccata' suite: the Aerosphere intro (wind and pads, bars 1-8) dissolving into Bach's Toccata BWV 565.

  python suite.py hw|model <dir>       takes / model cache as for mix_parts.py; writes <dir>/suite_<src>.wav/.mp3
  python suite.py hw <dir> --moog      the Toccata's top track (m1) played by the Moog DAC voice (part variant
                                       toccata_m1_moog, recorded as <dir>/toccata_m1.*): writes suite_moog_<src>

The intro ends on a D major pad chord (bars 7-8); the Toccata's opening A mordent enters over it while the
intro fades, and the pad's reverb tail carries into the first fermata.
"""
import os, sys
import numpy as np
import mix_parts as MX

BAR = 16 * 0.150                                   # Aerosphere bar (100 bpm, 16 steps of 150 ms)
INTRO_END = 8 * BAR                                # the sequencer starts here: cut before it
FADE = 1.5 * BAR                                   # fade over the D major chord
OVERLAP = 1.2 * BAR                                # Toccata entry before INTRO_END
LEVEL = 0.7                                        # intro rms relative to the Toccata
MOOG_GAIN = 9.6                                    # dB for the Moog m1 take: its line-out level is 10.6 dB below
                                                   # the organ take (DAC via the 470k pulse resistor), +2 dB lead


def rms(st):
    a = np.sqrt(np.mean(st ** 2, 1))
    return np.sqrt(np.mean(a[a > 0.05 * a.max()] ** 2))


def main(src, d, moog=False):
    if moog:
        MX.PC.PIECES["toccata"]["parts"]["m1"] = MX.PC.VARIANTS["toccata_m1_moog"]
        MX.PC.PIECES["toccata"]["mix"]["m1"] = (MOOG_GAIN, MX.PC.PIECES["toccata"]["mix"]["m1"][1])
    intro, k = MX.render(src, d, "aero", only=("wind", "pad1", "pad2"), end_s=INTRO_END, fade_s=FADE)
    toc, _ = MX.render(src, d, "toccata")
    intro *= LEVEL * rms(toc) / rms(intro)
    t0 = int((INTRO_END - OVERLAP) * k * MX.FS)
    out = np.zeros((max(len(intro), t0 + len(toc)), 2))
    out[:len(intro)] += intro
    out[t0:t0 + len(toc)] += toc
    print(f"intro {len(intro) / MX.FS:.1f} s, Toccata from {t0 / MX.FS:.1f} s")
    MX.write(out, os.path.join(d, f"suite_moog_{src}" if moog else f"suite_{src}"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--moog" in sys.argv)
