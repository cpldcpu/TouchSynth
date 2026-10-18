# Devlog

The TouchSynth rev 0.1 log (concept to board 1 bring-up, demo pieces, PWM DAC and the kettle) is on `master`
(`docs/devlog.md`). This log starts where the polyphonic design split off.

## 1. From TouchSynth to a polyphonic synth (2026-10-18)

Starting point: TouchSynth rev 0.1, a monophonic synth with an analog DCO, a transistor ladder and a
differential-pair VCA, controlled by a CH32V006. The idea: use that voice as one card and put 4–8 of them, each
with its own MCU, on a backplane.

Steps on the way (all on branch `polyphonic_hw`, commit 17536f3 holds the state before this fork):

- **Voice bus:** UART broadcast plus a SYNC line, not SPI (pin and DMA constraints of the V006's TSSOP-20);
  per-slot resets for enumeration. The voices synchronise their HSI to the controller: board 1 measured
  0.21 % per HSITRIM step and an HSI flicker of about 2e-4 (0.35 cent rms), unaffected by the LDO settings.
- **DCO or DAC:** in the model, the existing DAC (15.6 kHz, 8 bit) aliased badly with an open filter. One sample
  per carrier period removes the interpolation images; at 187.5 kHz with second-order sigma-delta, 7 bit reach
  the quality of an ideal DAC. Implemented on board 1: three oscillators (saw / pulse, polyBLEP) at 184 cycles
  per sample, after moving the pitch conversion from soft-float to tables and running the loop in blocks from
  SRAM. The kettle moved to the same carrier. On board 1 the DAC saw and the DCO saw measure the same (C2–C7,
  inharmonic content within ±2 dB, same closed-VCA floor). Decision: DAC only.
- **5 V:** S10 redesigned the analog core for a single 5 V supply: MCP6002 for the TL072s, a CJ431 reference
  (VREF, buffered VBIAS), the MCU on a 3.3 V LDO (the PWM outputs are duty × VDD), a new ladder bias chain and
  10 nF ladder capacitors. With Microchip's MCP6002 model it matches rev 0.1 within about 1–2 dB, at 3.6 mA
  instead of 9.1 mA.
- **Controller:** played from a computer over USB (USB-MIDI, CDC); CH32V203 for its crystal (USB and master
  clock) and two ADCs (USB audio of the mix as an option).
- **Model fix:** the behavioural model's saw had its polyBLEP at the start of the reset pulse instead of its end
  (high notes aliased at about −21 dB in every rev 0.1 render).

Decisions after the fork: 8 slots on the backplane, populated as cards are built; small voice cards with the
backplane connector on one edge and LEDs plus debug connectors on the opposite edge; the voice MCU is the
CH32V006 in QFN-32 (own stock; the board 1 pin map carries over, 13 GPIO spare). The dual-PWM DAC becomes an
assembly option (93.75 kHz at the quality of the 187.5 kHz single PWM, half the CPU load). Slot addresses come
from the enumeration over the per-slot resets. Not used: the V006's internal op-amp, an expo temperature sensor,
a separate UART console, a voltage-controlled reconstruction filter (the firmware shapes everything below
Nyquist; the filter only removes carrier and images, so its cutoff is fixed to the sample rate).

The rev 0.1 tree (report, S1–S7, KiCad project, tools for the report) is kept locally in `archive/`
(gitignored) and on `master`.
