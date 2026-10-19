# Bench controller (CH32V203 development board)

Stand-in for the backplane's controller on a CH32V203 development board: the master of the voice bus
([docs/bus.md](../../docs/bus.md)) for one voice card (plus up to 7 virtual voices for load tests), a USB-MIDI + CDC
device, and an Ardulink-compatible SWIO programmer through which `minichlink` flashes and debugs the voice card, the
path the backplane will use to update its cards. The full pin and command reference is the header of
`bench_ctrl.c`; as built and measured: bus.md section 9, [docs/controller.md](../../docs/controller.md) section 5.

| Function | Pins | Notes |
|---|---|---|
| SYNC, frame clock | PA8 (TIM1 CH1) | 1 kHz from the 8 MHz crystal (PLL x 18 = 144 MHz); FRAME packet per rising edge |
| Voice bus | PB10 TX, PB11 RX (USART3) | 1 Mbaud, DMA both ways; timed events, enumeration, refreshes |
| SWIO bridge | PB13 | WCH one-wire debug protocol, bit-banged; needs a 1–2.2 kΩ pull-up on the bench |
| PC port | PA9 / PA10 (USART1, 115200) | Ardulink protocol and the bench commands (`e` MIDI, `b` packets, `S` status, `V` voices, `G` load generator, `L` bus load, `U` USB status, ...) |
| USB | PB6 / PB7 (USBFS) | composite USB-MIDI + CDC (the CDC port carries the same commands as USART1); the development board wires its USB-C to USBFS |

## Build and flash (WSL)

```
make                       # USB on USBFS (PB6 / PB7), 1 Mbaud bus
make USB=usbd              # USB on USBD (PA11 / PA12, the backplane's device port; untested on this board)
make BUS_BAUD=2000000      # 2 Mbaud bus (the card must be built with the same BUS_BAUD)
minichlink -w bench_ctrl.bin flash -b     # WCH-LinkE on the V203's SWD
```

The build targets the CH32V203C8T6 (64 KB flash, 20 KB SRAM).

## Tests (lab PC, see `tools/`)

`tools/bustest.py all` (17 bus checks; also `latency`, `load`, `stress`, `counters`) and `tools/usbtest.py all`
(enumeration, CDC, USB-MIDI through ALSA, floods, latency, SYNC jitter, re-plug, reset). The voice card is built
with `make BOARD=card BUS_TX_PP=1` in `firmware/voice` (the bench return line has no pull-up).
