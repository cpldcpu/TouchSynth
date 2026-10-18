# TouchSynth Poly

A polyphonic analog synthesizer with up to 8 voices, played and edited from a computer over USB. Each voice is a
small plug-in card: a CH32V006 generates the oscillators digitally on a PWM DAC (187.5 kHz, sigma-delta) and
controls an analog transistor-ladder filter and VCA. A backplane with a CH32V203 holds the USB interface
(USB-MIDI), the voice bus, the 5 V supply and the stereo mixer.

**Status (2026-10-18):** architecture and simulations; nothing of the new hardware is built yet. The voice
firmware's oscillator engine runs on TouchSynth board 1 (rev 0.1), which served as the test bed.

This project is a fork of [TouchSynth](https://github.com/cpldcpu/TouchSynth) (rev 0.1: a monophonic touch synth
with an analog DCO), whose history is on `master`. The digital oscillators were developed and measured on its
board 1; the analog filter and VCA are its circuits, redesigned for a single 5 V supply.

Design: cpldcpu & Claude Opus 5.5.

## Documents

| Document | Content |
|---|---|
| [docs/design.md](docs/design.md) | requirements, architecture, budgets, verification plan, open points |
| [docs/midi.md](docs/midi.md) | MIDI implementation, parts and patches (proposal) |
| [docs/bus.md](docs/bus.md) | voice bus protocol (proposal) |
| [docs/spec.md](docs/spec.md) | architecture: voice card, backplane, voice bus, clock synchronisation, decisions, open points |
| [docs/devlog.md](docs/devlog.md) | development log since the fork |
| [docs/README.md](docs/README.md) | index of the documents, results, figures and audio |

## Repository layout

```
docs/        specification, devlog, results (CSV), figures, audio examples
sim/         ngspice studies (S8 PWM DAC, S9 oscillators, S10 5 V analog core, S11 reconstruction filter) and the
             behavioural model
firmware/    voice/: CH32V006 voice firmware (from TouchSynth rev 0.1); ch32fun (git submodule)
hw/          schematic / PCB generator scripts (still the rev 0.1 description, to be replaced by the new boards)
parts/       JLCPCB Basic / Promotional Extended part lists
tools/       bench tools: SWIO console, oscilloscope recording, hardware tests, multitrack mixing
```

Constraints: JLCPCB Basic and Promotional Extended parts only; MCUs (own stock), headers and connectors
hand-soldered.
