# TouchSynth Poly: controller plan

Status: plan 0.1 (2026-10-18). The controller is the CH32V203C8T6 on the backplane. Requirements:
[design.md](design.md) (F1–F4, F6, F10, P8–P11); backplane hardware: [spec.md](spec.md) section 4; voice bus:
[bus.md](bus.md); MIDI and patches: [midi.md](midi.md).

## 1. Hardware

| Block | Plan |
|---|---|
| MCU | CH32V203C8T6 (LQFP-48, 64 KB flash, 20 KB SRAM, 144 MHz), 8 MHz crystal; XC6206 3.3 V |
| USB device | USB-C (sink: 5.1 kΩ on CC1 / CC2), ESD protection, USBD on PA11 / PA12. The computer sees a class-compliant USB-MIDI device plus a CDC serial port: the computer plays and edits the synth over MIDI, no separate MIDI connection needed |
| USB host | USB-A on USBFS (PB6 / PB7) for class-compliant MIDI keyboards; VBUS through a current-limited switch (part to choose from the JLCPCB lists) |
| MIDI DIN in (not fitted) | footprint only: 3.5 mm TRS (MIDI type A) or a pin header, optocoupler with its resistors and diode (as rev 0.1's DNP MIDI input), into a free USART RX; for old hardware without USB |
| Power | USB-C VBUS, or an external 5 V on a 2-pin header (cleaner than a computer's USB 5 V). A 3-pin jumper selects the source (no diode drop: the cards' analog core wants the full 5 V). VBUS goes to a GPIO through a divider (the device enables its USB pull-up only when a computer is connected). Polyfuse and TVS on the 5 V rail. The cards filter their own analog rail (22 Ω + 3 × 100 µF, CJ431: supply rejection 66–77 dB) |
| Voice bus | USART TX (broadcast), USART RX (return, 1 kΩ pull-up), SYNC (timer output, 1 kHz), 8 × NRST, 8 × SWIO (GPIOs, each with a 1 kΩ pull-up to 3.3 V: the cards have none), MCO to CLK_IN (option) |
| Mixer, ADC tap | S12 (to be revised for L / R outputs per card if S13 adds a pan stage); ADC1 / ADC2 for USB audio |
| Programming | SWD header (SWDIO PA13, SWCLK PA14, 3.3 V, GND) for the WCH-LinkE: development and debugging (minichlink, as for the voice cards). BOOT0 jumper: the factory bootloader then reprograms the flash over USB (wchisp or WCH's ISP tool) without a programmer, the path for firmware updates in the field |
| Indicators | power LED, activity LED (MIDI / bus) |

Pin numbers come with the backplane schematic, from the datasheet's LQFP-48 table. Known: USBD PA11 / PA12, USBFS
PB6 / PB7, SWD PA13 / PA14, crystal on PD0 / PD1, BOOT0 pin. GPIO budget about 30 of 37 (design.md 4.2).

## 2. Firmware

```
 USB device (MIDI, CDC)   USB host (MIDI)   UART MIDI (option)
          │                     │                 │
          └──────────► MIDI router: channel → parts ◄──── CDC commands, SysEx
                                  │
                 parts, voice allocator (poly / mono / legato / unison / kit), sustain
                                  │
                 bus scheduler: frame clock, timed events (lead 2 frames), refreshes
                                  │
          USART TX DMA ◄── frame queue        SYNC timer 1 kHz        USART RX ◄── replies
```

| Module | Content |
|---|---|
| Frame clock | a timer outputs SYNC (1 kHz) and interrupts at each frame start: FRAME packet, then the packets due in this frame, sent by DMA |
| USB device | composite MIDI + CDC (UAC1 audio input later); ch32fun's USB code or a TinyUSB port, to decide on the development board |
| USB host | class-compliant MIDI on USBFS; a small host driver or TinyUSB host |
| MIDI router, parts | midi.md: 8 parts, channel and key ranges, CCs, NRPN, program change, MIDI clock |
| Voice allocator | free voice, else oldest released, else oldest held, within a part's slot mask; patch slots on the cards (PATCH_SELECT) |
| Bus scheduler | bus.md: timed events, the bus lead, bandwidth per frame, VOICE_STATE and patch refreshes, requests and replies |
| Enumeration, calibration | slot by slot over NRST at power-up; calibration on request; results stored by chip ID |
| Storage | patch library (64 × 144 bytes) and setups in the V203's flash (wear-levelled pages); working copies in SRAM |
| Card programming | SWIO on each slot's line (the WCH-LinkE protocol), image streamed from the computer over CDC |
| CDC commands | patches, setups, part settings, card status, calibration, firmware update, a bridge to a card's console |

Memory estimate: USB device + host stacks 15–25 KB, application 15–20 KB, patch library and setups about 12 KB:
inside 64 KB flash; 20 KB SRAM holds the working copies, the frame queue and the USB buffers.

## 3. Development path

1. **Development board + board 1:** a V203 development board as controller, board 1 as one voice, wired by hand
   (UART TX → board 1 RX (PD6), board 1 TX (PD5) → board RX with a pull-up, SYNC → board 1 PD4, a GPIO → board 1
   NRST, GND). Board 1's PD4 / PD5 are its 74HC595 latch and loopback ADC today; the voice firmware's card build
   (with the card's pin map) runs on board 1 with those functions given up. First: SYNC frame clock and HSITRIM
   locking, then the bus receiver, then USB-MIDI → notes.
2. **USB:** MIDI + CDC device on the development board, then the host port.
3. **Backplane:** schematic and layout once the card and the mixer (S12 / S13) are settled; then 1–2 cards, then 8.

## 4. Open points

- The bootloader's USB port on the V203 (USBD on PA11 / PA12 or USBFS) and whether wchisp supports it; until then
  the WCH-LinkE over SWD.
- USB stack choice; isochronous audio support.
- The current-limited switch for the host port and the USB-C ESD part from the JLCPCB lists.
- MIDI DIN: TRS or 5-pin DIN footprint.
- SWIO programming timing from the V203 (bit-banged one-wire protocol at 144 MHz).
