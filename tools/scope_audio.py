#!/usr/bin/env python3
"""Turn a scope recording (scope.py record: float32 volts + rate file, ~200 kSa/s after boxcar decimation) into
48 kHz / 16-bit WAV and MP3: anti-alias FIR + polyphase resampling, DC removal, leading silence trimmed (0.2 s
pre-roll kept), peak normalised to -1 dBFS. Prints the noise floor before the first note as a resolution check.

  python scope_audio.py rec.f32 out_basename [--keep-level]
"""
import sys, subprocess, wave
from fractions import Fraction
import numpy as np
from scipy.signal import resample_poly

FS = 48000


def convert(f32, base, keep_level=False):
    rate = float(open(f32 + ".txt").read().split()[0])
    v = np.fromfile(f32, np.float32).astype(np.float64)
    fr = Fraction(FS / rate).limit_denominator(1000)
    y = resample_poly(v, fr.numerator, fr.denominator)       # Kaiser FIR, cutoff at 24 kHz
    y -= np.median(y)
    blk = int(0.1 * FS)                                       # noise floor: quietest 0.1 s block
    rms = np.array([np.std(y[k:k + blk]) for k in range(0, len(y) - blk, blk)])
    noise = rms.min()
    b = int(0.05 * FS)                                        # sustained sound: 50 ms blocks above 10 % of the
    lv = np.array([np.std(y[k:k + b]) for k in range(0, len(y) - b, b)])     # loudest block, held for 0.5 s
    act = lv > max(0.1 * lv.max(), 20 * noise)
    run = np.convolve(act, np.ones(10), mode="full")[9:]       # active blocks in the next 0.5 s
    on = int(np.argmax(run >= 8)) * b                         # (ignores the reset click when the console connects)
    off = (len(act) - int(np.argmax(act[::-1]))) * b          # last active block, then 0.5 s of tail
    y = y[max(0, on - int(0.2 * FS)):min(len(y), off + int(0.5 * FS))]
    y[: int(0.005 * FS)] *= np.linspace(0, 1, int(0.005 * FS))
    y[-int(0.05 * FS):] *= np.linspace(1, 0, int(0.05 * FS))
    peak = np.abs(y).max()
    print(f"{base}: {len(y)/FS:.1f} s, peak {peak:.3f} V, noise floor {noise*1e3:.2f} mV rms in 24 kHz "
          f"({20*np.log10(noise*np.sqrt(2)/peak):.0f} dB re peak)")
    g = 1.0 if keep_level else 10 ** (-1 / 20) / peak
    pcm = np.clip(np.round(y * g * 32767), -32768, 32767).astype(np.int16)
    with wave.open(base + ".wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(pcm.tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", base + ".wav", "-codec:a", "libmp3lame", "-q:a", "2",
                    base + ".mp3"], check=True)
    return y


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2], "--keep-level" in sys.argv)
