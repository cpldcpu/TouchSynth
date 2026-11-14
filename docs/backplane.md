# TouchSynth Poly: backplane and controller PCB

Status: 0.3 (2026-10-19; 2026-10-20: the host port fitted, 4.2), drawn in KiCad: `hw/backplane.py` (design), schematic (`docs/schematics/backplane.pdf`),
PCB (`hw/gen_pcb_bp.py`, 4 layers, routed and DRC clean, figures in `docs/figures/backplane_pcb/`). Changes from 0.1,
decided by the user: board
fixed at 100 × 100 mm; an SPI flash (not fitted) on SPI1; the 8 NRST lines through a 74HC595 on the same bus; the
soft start not fitted (0 Ω bypass). Changes from 0.2 while drawing: the 595 drives NRST directly, no pull-downs or
series resistors (user decision, 3.5); the host port not fitted (fitted again on 2026-10-20), its switch a TPS2051C (4.2); VREF from the
controller's +3V3 through two RC stages, no CJ431 and no buffer (user proposal, 5); the per-slot input capacitors
in 0805 (the +5 V rail passes between their pads); the 8 MHz crystal in the 2-pad 5032 package (C115962 is a 2-pad
part); SYNC joins the bus riser between slots 6 and 7 (the east margin carries the +5 V trunk and both 47 µF);
the SWD header J5 vertical beside the flash; no card-guide screw holes yet (the M3 holes only). Requirements:
[design.md](design.md); card connector and backplane summary:
[spec.md](spec.md) sections 3.3 and 4; controller plan: [controller.md](controller.md); voice bus: [bus.md](bus.md);
MIDI: [midi.md](midi.md); mixer values: S12 (`sim/s12_mixer/s12_mixer.py --bus2`,
[results/s12_mixer_2bus.csv](results/s12_mixer_2bus.csv)).

Pin data comes from the WCH CH32V203 datasheet V3.0, Table 3-1-1 (LQFP48 column), Table 2-1 (C8x6 resources),
section 2.5.2 (boot), Figure 2-3 (clock tree) and section 4 (electrical). The datasheet is not in the repository.
Statements marked **unverified** still need a source or a bench test.

## 1. Requirements

| Item | Requirement | Source |
|---|---|---|
| Slots | 8 voice cards, 50 × 50 mm, at 10 mm pitch; any slot may be empty | design C4, F1 |
| PCB | 4 layers (0.3; planned as 2), **100 × 100 mm** (fixed) | design C4, user decisions |
| Controller | CH32V203C8T6 (LQFP-48), 8 MHz crystal, PLL × 18 = 144 MHz; *[2026-10-20]* assembled by JLCPCB (C3001172, Extended, from the user's JLCPCB personal stock; before: hand-soldered from own stock) | design C3, 7.3 |
| USB device | USB-C, full speed, on USBD (PA11/PA12): MIDI + CDC (+ UAC1 later); sink with 5.1 kΩ on CC1/CC2 | design 5.4 |
| USB host | USB-A on USBFS (PB6/PB7) for class-compliant MIDI keyboards, VBUS through a current-limited switch | design F3 |
| Power | USB-C VBUS or an external 5 V header, chosen by a 3-pin jumper (no diode drop); polyfuse, TVS, bulk; 3.3 V LDO for the controller; soft start as an unpopulated option; total within 500 mA | design C1, controller.md |
| Voice bus | USART broadcast (push-pull, 33 Ω), open-drain return (1 kΩ pull-up), SYNC 1 kHz, 8 × NRST through a 74HC595, 8 × SWIO (1 kΩ pull-up each), CLK_IN option | bus.md 2, spec 4 |
| Storage | SPI NOR flash on SPI1, footprint only (W25Q128JVSIQ or BY25D16ASTIG, hand-soldered later) | user decision |
| Audio | two-bus stereo mixer (S12), 3.5 mm stereo line out, ADC tap for USB audio | spec 4, design F7, F10 |
| MIDI DIN in | footprint only (optocoupler circuit), not fitted | controller.md |
| Programming | SWD header (WCH-LinkE), BOOT0 jumper (factory bootloader over USART1 or USB) | controller.md |
| Indicators | status LEDs | controller.md |
| Parts | JLCPCB Basic and Promotional Extended for assembly, plus the MCU (Extended, personal stock, 2026-10-20); connectors, headers and parts missing from the lists hand-soldered | design C2 |

### 1.1 Bench results carried over

- **SWIO pull-up:** every slot's SWIO line needs a 1 kΩ pull-up to 3.3 V on the backplane. The card has none (on
  the bench the WCH-LinkE provides it), and the one-wire protocol samples about 0.6 µs after each edge; without
  the pull-up every read returns 0.
- **Crystal clock:** the V203 runs from its 8 MHz crystal (HSE, PLL × 18 = 144 MHz). SYNC is the pitch reference
  of every voice. A voice V006 measured its HSI within ±0.03 % of the crystal at factory trim (±0.06 % in the bus tests,
  bus.md 9.1), with ±200–250 ppm
  of wander.
- **Pins that worked:** USART3 TX PB10 for the broadcast and RX PB11 for the return; SYNC on PA8 (TIM1 CH1); NRST
  open drain; USART1 PA9/PA10 kept free for the bootloader and a debug UART; SWD on PA13/PA14. Section 3 keeps all
  of them except NRST, which now comes from the 74HC595 (push-pull, direct; section 3.5).
- **Levels:** the bus lines are 3.3 V on both sides. No level shifters.

## 2. Block diagram

```
 USB-C (device) ── ESD ──┬─ D+/D- ─────────────────────────────► PA11/PA12  USBD
   CC1, CC2: 5.1k each   └─ VBUS_C ──┬── 22k/33k ─────────────► PB15 VBUS_DET
                                     │
 ext 5 V (J4) ───────────────────┐   │
                              [JP1: USB | EXT]
                                     │
                              F1 PTC 0.75 A ── D1 SMAJ5.0A ── +5V_IN
                                     │
            ┌────────────────────────┼─────────────────────────────┐
            │                        │                             │
     XC6206 3.3 V           R_BYP 0 Ω (fitted) ∥ Q1 soft      U4 current-limited switch ── VBUS_HOST ── USB-A
     +3V3: MCU, 595, flash,  start (not fitted)                EN ◄ PB8, FLT ► PB9             │
     pull-ups, LEDs                  │                                                 ESD, D+/D- ► PB6/PB7
                                +5V_SLOTS (2 × 47 µF)
                                     │
              ┌──────────────────────┴──────────── 8 sockets, pins 1/2 (10 µF each) ─────────────┐
              │                                                                                   │
 CH32V203C8T6 (Y1 8 MHz, 144 MHz)                                                         voice cards 1..8
   PB10 USART3_TX ─ 33R ─────── BCAST ──────────────────────────────────────► pin 10 (RX)
   PB11 USART3_RX ◄──────────── RETURN (1k to 3V3) ◄──────────────────────── pin 11 (TX, open drain)
   PA8  TIM1_CH1 ── 33R ─────── SYNC 1 kHz ─────────────────────────────────► pin 9
   PB1  TIM3_CH4 ── 33R ─────── CLK 24 MHz (option, off by default) ────────► pin 15
   SPI1 remap 1: PB3 SCK, PB5 MOSI ──┬──► U6 74HC595 ─────────── NRST_k ────► pin 12 of slot k
                 PB4 MISO            │    RCLK ◄ PC13
                 PA15 CS ────────────┴──► U7 SPI flash (not fitted)
                                          OE_N ◄ PC14 (10k pull-up)
   8 GPIO ──────────────────┬── SWIO_k ─────────────────────────────────────► pin 14 of slot k
                       1k to 3V3
   PA0 ADC1_IN0 ◄─ 15k/27k/330p ◄── MIX_L ┐
   PA1 ADC2_IN1 ◄─ 15k/27k/330p ◄── MIX_R ┤
   PA10 USART1_RX ◄─ JP3 (DNP) ◄─ opto ◄─ MIDI in (not fitted; shared with J6)
   PA13/PA14 SWD, PA9/PA10 USART1 (J6),    │       stereo mixer (S12)
   BOOT0 jumper, PB2 LED                   │   MCP6002 inverting sums on VREF 2.41 V (+3V3 / RC)
                                           └── ◄── pins 5 (AUDIO_L), 6 (AUDIO_GND), 7 (AUDIO_R) of every slot
                                               ├─► 220R + 10 µF ─► 3.5 mm line out
                                               └─► ADC taps
```

## 3. Controller pin map

### 3.1 Decisions and conflicts

**Resources (Table 2-1, C8x6):** 37 GPIO, 2 ADC units with 10 channels, 4 USART/UART, 2 SPI, 1 advanced and 3
general-purpose 16-bit timers (TIM1, TIM2–TIM4), USBD and USBFS (listed as USBHD). The bus clocks PB1 and PB2
(APB1/APB2) run up to 144 MHz (section 4.3.1).

**Bench pins re-checked:**

| Bench choice | Datasheet row (LQFP48) | Final |
|---|---|---|
| USART3 TX → broadcast | pin 21, PB10, I/O/A, FT, USART3_TX | kept |
| USART3 RX ← return | pin 22, PB11, I/O/A, FT, USART3_RX | kept |
| SYNC, TIM1 CH1 | pin 29, PA8, I/O, FT, TIM1_CH1, USART1_CK, MCO | kept (see MCO below) |
| NRST open drain, one GPIO per slot | any GPIO | replaced by the 74HC595 (section 3.5) |
| USART1 for the bootloader | pins 30/31, PA9/PA10, FT, USART1_TX/RX | kept, to header J6; PA10 can also take MIDI in (DNP jumper) |
| SWD | pins 34/37, PA13 SWDIO, PA14 SWCLK, FT | kept |

Other fixed pins: USBD DM/DP on pins 32/33 (PA11 USBDM, PA12 USBDP), USBFS DM/DP on pins 42/43 (PB6 USBFS_DM,
PB7 USBFS_DP), so device and host run at the same time. OSC_IN/OSC_OUT on pins 5/6 (Note 4: on the C8T6 they are
the HSE pins after reset, remappable to PD0/PD1). BOOT0 on pin 44. PB2 is BOOT1 (pin 20).

**SPI1 remap 1** (user decision), checked in Table 3-1-1, remap column: PA15 (pin 38) SPI1_NSS_1, PB3 (pin 39)
SPI1_SCK_1, PB4 (pin 40) SPI1_MISO_1, PB5 (pin 41) SPI1_MOSI_1, all FT. The remap moves all four signals together
(AFIO SPI1 remap bit = 1). NSS is used as a plain GPIO (software chip select for the flash); the 595 has its own
latch pin. The default SPI1 pins PA4–PA7 stay free for SWIO.

**PA8: SYNC or MCO (the CLK_IN conflict).** MCO exists only on PA8. It cannot supply the card's clock anyway:
the MCO multiplexer of Figure 2-3 selects HSI, HSE or PLLCLK/2, i.e. 8, 8 or 72 MHz with an 8 MHz crystal at
144 MHz (the reference manual may also list SYSCLK, 144 MHz; not checked). The card feeds CLK_IN to the V006's
XI pin as an external HSE (3–32 MHz, typically 24 MHz, V006 datasheet 3.3.5), and the V006 PLL is a fixed × 2
(V00X reference manual, clock tree), so the card needs 24 MHz to keep its 48 MHz system clock. **Resolution:**
SYNC stays on PA8 (TIM1_CH1, bench-proven). CLK_IN comes from a timer instead: TIM3_CH4 on PB1 counts at
144 MHz with ARR = 5, CCR = 3 and gives exactly 24.000 MHz with 50 % duty, locked to the crystal. MCO is not
used. Rejected alternative: a 24 MHz crystal (MCO = HSE = 24 MHz, PLL × 6): no 24 MHz crystal on the lists, and
the bench and the ch32fun setup use 8 MHz. Note for spec 6 and design 4.2: "MCO to CLK_IN" becomes "TIM3_CH4
(PB1) to CLK_IN".

**Clock plan:** SYSCLK 144 MHz (USB needs 48, 96 or 144 MHz, Figure 2-3 note), HCLK 144 MHz, PCLK1 = PCLK2 =
72 MHz, so the timers run at 144 MHz (× 2 after a prescaler ≠ 1), USART3 at 72 MHz (BRR 72 = 1 Mbaud exactly),
SPI1 at up to 36 MHz (PCLK2 / 2), the ADC at 12 MHz (PCLK2 / 6; f_ADC ≤ 14 MHz, f_S ≤ 1 MHz, R_AIN ≤ 50 kΩ,
section 4.3.16).

**BOOT1 (PB2).** The bootloader starts with BOOT0 = 1 and BOOT1 = 0 (section 2.5.2: boot from flash, system
memory or SRAM). PB2 must therefore be low at reset. A slot line cannot sit on PB2 (SWIO has a 1 kΩ pull-up), nor
VBUS_DET (high exactly when the bootloader is wanted). PB2 drives the activity LED and has a 10 kΩ pull-down.

**PC13–PC15** (Note 2): only 2 MHz output, at most 30 pF, no current sourcing (supplied through a 3 mA analog
switch). They carry slow logic only: the 595's latch and output enable (short lines to U6).

**MIDI RX.** The USART RX options are USART1_RX PA10 (or PB7 remapped: USB host), USART2_RX PA3 (SWIO), USART3_RX
PB11 (the bus return), USART4_RX PB1 (CLK_OUT) or PB5 remapped (now SPI1 MOSI). None of the freed pins is a USART
RX. MIDI in therefore shares **USART1_RX (PA10)** with J6 through a jumper JP3, not fitted: fit JP3 only when the
DIN input is used, and then the debug and bootloader UART cannot receive (its TX still works). Remove JP3 for
bootloader access over USART1.

**Routing order around the package.** The two USB pairs leave pins 32/33 (right side) and 42/43 (top side) toward
the board edge. The pins between them, 34–41 (SWDIO, VSS_2, VDD_2, SWCLK, PA15, PB3, PB4, PB5), are enclosed by the
two pairs and the edge, so they can only reach parts in that corner without crossing a USB pair. SWD sits there;
the SPI lines leave the corner westward under the USB-A pair (short bottom hops) to the flash and the 595, which
sit together west of the MCU (as drawn in 0.3: a flash in the corner as well left the routing too dense on two
layers). The slot lines (8 SWIO, SYNC, BCAST, RETURN, CLK) come from the other side of the package, ordered from west
to east like the slots: PA2–PA7 (SWIO 1–6), PB1, PB10, PB11 (bus riser), PB12, PB13 (SWIO 7, 8), PA8 (SYNC, east
end). The NRST lines come from U6 as a separate bundle (section 7.3).

### 3.2 Pin table

FT = 5 V tolerant (datasheet: input up to 5.5 V; other pins VDD + 0.3 V, injected current ±5 mA). The functions
column lists the default alternate functions and remaps of Table 3-1-1 that matter here (suffix _1, _2, _3 = AFIO
remap value, Note 8).

| Pin | Name | Type | FT | Datasheet functions (default AF; remap) | Use | Circuit |
|---|---|---|---|---|---|---|
| 1 | VBAT | P | | | supply | +3V3 |
| 2 | PC13-TAMPER-RTC | I/O | | PC13, TAMPER-RTC (Note 2: 2 MHz, no sourcing) | SR_LATCH | → U6 RCLK |
| 3 | PC14-OSC32_IN | I/O/A | | PC14, OSC32_IN | SR_OE_N | → U6 OE_N, 10 kΩ to +3V3 |
| 4 | PC15-OSC32_OUT | I/O/A | | PC15, OSC32_OUT | **free** | test pad |
| 5 | OSC_IN | I/A | | OSC_IN; PD0 | HSE | Y1 8 MHz, 30 pF |
| 6 | OSC_OUT | O/A | | OSC_OUT; PD1 | HSE | Y1, 30 pF |
| 7 | NRST | I | | NRST (30–50 kΩ internal pull-up) | MCU reset | 100 nF, optional button SW1 |
| 8 | VSSA | P | | | GND | |
| 9 | VDDA | P | | | supply | +3V3 through ferrite, 1 µF + 100 nF |
| 10 | PA0-WKUP | I/O/A | | ADC_IN0, TIM2_CH1/ETR, USART2_CTS, WKUP | MIX_L tap | ADC1 IN0; 15k/27k + 330 pF |
| 11 | PA1 | I/O/A | | ADC_IN1, TIM2_CH2, USART2_RTS | MIX_R tap | ADC2 IN1; 15k/27k + 330 pF |
| 12 | PA2 | I/O/A | | ADC_IN2, TIM2_CH3, USART2_TX, OPA2_OUT0 | SWIO_1 | 1 kΩ to +3V3 → slot 1 pin 14 |
| 13 | PA3 | I/O/A | | ADC_IN3, TIM2_CH4, USART2_RX, OPA1_OUT0 | SWIO_2 | as SWIO_1 |
| 14 | PA4 | I/O/A | | ADC_IN4, SPI1_NSS, USART2_CK, OPA2_OUT1 | SWIO_3 | as SWIO_1 |
| 15 | PA5 | I/O/A | | ADC_IN5, SPI1_SCK, OPA2_CH1N; USART4_TX_1 | SWIO_4 | as SWIO_1 |
| 16 | PA6 | I/O/A | | ADC_IN6, TIM3_CH1, SPI1_MISO; TIM1_BKIN_1, USART4_CK_1 | SWIO_5 | as SWIO_1 |
| 17 | PA7 | I/O/A | | ADC_IN7, TIM3_CH2, SPI1_MOSI; TIM1_CH1N_1, USART4_CTS_1 | SWIO_6 | as SWIO_1 |
| 18 | PB0 | I/O/A | | ADC_IN8, TIM3_CH3, USART4_TX; TIM1_CH2N_1, TIM3_CH3_2 | **free** | test pad (between the SWIO ribbon and the riser) |
| 19 | PB1 | I/O/A | | ADC_IN9, TIM3_CH4, USART4_RX; TIM1_CH3N_1, TIM3_CH4_2 | CLK_OUT | TIM3_CH4, 24 MHz, 33 Ω → pin 15 (option) |
| 20 | PB2 | I/O | FT | PB2/BOOT1, USART4_CK | LED_ACT | 10 kΩ pull-down, LED + 1 kΩ |
| 21 | PB10 | I/O/A | FT | USART3_TX, I2C2_SCL; TIM2_CH3_2/_3 | BCAST | 33 Ω → pin 10 |
| 22 | PB11 | I/O/A | FT | USART3_RX, I2C2_SDA; TIM2_CH4_2/_3 | RETURN | 1 kΩ to +3V3 ← pin 11 |
| 23 | VSS_1 | P | | | GND | |
| 24 | VDD_IO_1 | P | | | supply | +3V3, 100 nF |
| 25 | PB12 | I/O/A | FT | SPI2_NSS, I2C2_SMBA, USART3_CK, TIM1_BKIN | SWIO_7 | as SWIO_1 |
| 26 | PB13 | I/O/A | FT | SPI2_SCK, USART3_CTS, TIM1_CH1N | SWIO_8 | as SWIO_1 |
| 27 | PB14 | I/O/A | FT | SPI2_MISO, TIM1_CH2N, USART3_RTS | **free** | test pad |
| 28 | PB15 | I/O/A | FT | SPI2_MOSI, TIM1_CH3N | VBUS_DET | 22k / 33k from VBUS_C |
| 29 | PA8 | I/O | FT | TIM1_CH1, USART1_CK, MCO | SYNC | TIM1_CH1 1 kHz, 33 Ω → pin 9 |
| 30 | PA9 | I/O | FT | USART1_TX, TIM1_CH2 | UART TX | J6 (bootloader, debug) |
| 31 | PA10 | I/O | FT | USART1_RX, TIM1_CH3 | UART RX / MIDI RX | J6; MIDI opto through JP3 (DNP) |
| 32 | PA11 | I/O/A | FT | USBDM, USART1_CTS, CAN1_RX, TIM1_CH4 | USB device D− | J1 USB-C, ESD |
| 33 | PA12 | I/O/A | FT | USBDP, USART1_RTS, CAN1_TX, TIM1_ETR | USB device D+ | J1 USB-C, ESD |
| 34 | PA13 | I/O | FT | SWDIO | SWD | J5 |
| 35 | VSS_2 | P | | | GND | |
| 36 | VDD_2 | P | | | supply | +3V3, 100 nF |
| 37 | PA14 | I/O | FT | SWCLK | SWD | J5 |
| 38 | PA15 | I/O | FT | PA15; TIM2_CH1/ETR_1/_3, SPI1_NSS_1, USART4_RTS_1 | FLASH_CS_N | GPIO chip select, 10 kΩ to +3V3 |
| 39 | PB3 | I/O | FT | USART4_CTS; TIM2_CH2_1/_3, SPI1_SCK_1 | SPI1 SCK | U7 CLK, U6 SRCLK |
| 40 | PB4 | I/O | FT | USART4_RTS; TIM3_CH1_2, SPI1_MISO_1 | SPI1 MISO | U7 DO |
| 41 | PB5 | I/O | FT | I2C1_SMBA; TIM3_CH2_2, SPI1_MOSI_1, USART4_RX_1 | SPI1 MOSI | U7 DI, U6 SER |
| 42 | PB6 | I/O | FT | USBFS_DM, TIM4_CH1, I2C1_SCL; USART1_TX_1 | USB host D− | J2 USB-A, ESD |
| 43 | PB7 | I/O | FT | USBFS_DP, TIM4_CH2, I2C1_SDA; USART1_RX_1 | USB host D+ | J2 USB-A, ESD |
| 44 | BOOT0 | I | | BOOT0 | boot select | JP2, 10 kΩ pull-down |
| 45 | PB8 | I/O/A | FT | TIM4_CH3; I2C1_SCL_1, CAN1_RX_2 | HOST_EN | U4 EN, 100 kΩ pull-down (port off at reset) |
| 46 | PB9 | I/O/A | FT | TIM4_CH4; I2C1_SDA_1, CAN1_TX_2 | HOST_FLT_N | U4 FAULT, 10 kΩ to +3V3, fault LED |
| 47 | VSS_3 | P | | | GND | |
| 48 | VDD_IO_3 | P | | | supply | +3V3, 100 nF |

Slot lines by slot (NRST through U6, see 3.5):

| Slot | NRST (pin 12) | SWIO (pin 14) | SWIO FT |
|---|---|---|---|
| 1 | U6 output, direct | PA2 | no |
| 2 | U6 | PA3 | no |
| 3 | U6 | PA4 | no |
| 4 | U6 | PA5 | no |
| 5 | U6 | PA6 | no |
| 6 | U6 | PA7 | no |
| 7 | U6 | PB12 | yes |
| 8 | U6 | PB13 | yes |

The 595 output that drives each slot is chosen in the layout (whatever keeps the NRST bundle in slot order); the
firmware maps slot to bit through a table. SWIO is driven open drain (low or released) and read back, one slot at
a time.

### 3.3 Pin count

| Group | Pins |
|---|---|
| Crystal | 2 |
| USB device, USB host | 4 |
| SWD | 2 |
| USART1 (bootloader, debug; MIDI RX shared on PA10) | 2 |
| Bus: BCAST, RETURN, SYNC | 3 |
| CLK_IN option | 1 |
| SWIO × 8 | 8 |
| SPI1: SCK, MISO, MOSI, flash CS | 4 |
| 595 latch, 595 output enable | 2 |
| ADC taps | 2 |
| VBUS_DET, HOST_EN, HOST_FLT_N | 3 |
| LED_ACT | 1 |
| **Used** | **34 of 37** |
| **Free** | **3: PC15, PB0, PB14** |

The 8 NRST GPIOs of 0.1 became: latch and output enable for U6 (2), the four functions displaced from PA15/PB3/
PB4/PB5 by SPI1 (HOST_EN → PB8, HOST_FLT_N → PB9, VBUS_DET → PB15; MIDI RX moved to the shared PA10), and 3 free
pins. To keep the SWIO ribbon contiguous, SWIO 1–6 moved to PA2–PA7 and SWIO 7–8 to PB12/PB13. The free pins are
hemmed in by other lines: PC15 is weak and can reach the north-west of the strip (an input, e.g. a lid switch),
PB0 and PB14 sit between ribbons (test pads, or local use only).

### 3.4 Where 5 V can appear

| Source | Pins | Protection |
|---|---|---|
| USB-C cable (D± shorted to VBUS) | PA11, PA12 (FT) | SRV05-4 |
| USB-A device | PB6, PB7 (FT) | SRV05-4 |
| VBUS sense | PB15 (FT) | 22k/33k: 3.0 V at 5.0 V, 3.3 V at 5.5 V |
| USART1 header (a 5 V USB-serial adapter) | PA9, PA10 (FT) | none needed |
| SWD header | PA13, PA14 (FT) | none needed |
| MIDI in | PA10 (FT) | opto, pull-up to 3.3 V |
| A card plugged in reversed | slot lines | see below |

A card turned by 180° in its socket maps socket pin p onto card pin 17 − p: socket pin 1 (+5 V) reaches the card's
GND (pin 16), socket pins 4 and 13 (GND) reach card GND too, so +5 V is shorted through the card and F1 trips. While
the contacts make in a bad order, the card's ground can sit at +5 V and drive socket pins 9 (SYNC, from card pin 8),
11 (RETURN, from card pin 6) and 14 (SWIO, from card pin 3). SYNC (PA8) and RETURN (PB11) are FT; SWIO is FT for
slots 7 and 8 only (section 3.2). The NRST lines see the card's AUDIO_L (0 V DC, behind
the card's 10 µF and 100 kΩ: no DC path into U6). An enabled CLK_OUT would drive the card's +5 V net, which is then
grounded: CLK is off by default. The protection against this fault is mechanical: the card guides (section 6.3) do
not accept a reversed card, and the silkscreen marks pin 1 and the part side. Hot-plugging is not supported.

### 3.5 NRST through the 74HC595, enumeration

**Circuit:** U6 74HC595 (C5947, SOIC-16) at +3V3 (74HC: 2–6 V), 100 nF. SER = MOSI (PB5), SRCLK = SCK (PB3),
RCLK = SR_LATCH (PC13), OE_N = SR_OE_N (PC14) with 10 kΩ to +3V3, MR_N tied to +3V3, QH' unused. Each output
drives its slot's pin 12 directly: no series resistors, no pull-downs (user decision, 2026-10-19; 0.2 had 1 kΩ in
series and 4.7 kΩ pull-downs that held the cards in reset until the firmware ran).

**Power-up state:** the 595's storage register (and so its outputs) is undefined at power-up, and MR_N clears only
the shift register, not the outputs. The 10 kΩ on OE_N keeps those undefined outputs off the slots while the V203 is
in reset, booting, in the bootloader or halted: the NRST lines then float, and the card's internal NRST pull-up
lets every card boot and run on its own (standalone, bus.md 6: no SYNC, VCA muted, it never sends unless
addressed). The system accepts this by design: the controller can always take the cards back, through the 595 or
over each card's SWIO line (a debug-interface reset), so nothing depends on the cards staying in reset before the
firmware runs, and a controller reset or watchdog needs no special handling.

**Firmware sequence:**

1. Shift 0x00 (all slots in reset), pulse RCLK, then drive OE_N low: every card is reset and held there.
2. Start SYNC and FRAME (bus.md 6).
3. Enumeration, slot by slot: shift the pattern with bit k set, pulse RCLK. The card in slot k boots, trims to SYNC
   and answers ASSIGN; no HELLO within 300 ms means the slot is empty (bus.md 6). Released slots stay released.
4. A single-voice reset is the same: clear that bit, latch, set it again.
5. A controller reset (power, watchdog, SWD) lets OE_N float high again: the cards keep running (muted without
   SYNC) until the restarted firmware takes them back with step 1; a card that hangs can be reset over SWIO.

**Sharing SPI1 with the flash:** every flash transfer also clocks the 595's shift register, but its outputs change
only on a rising RCLK edge. The firmware therefore always shifts all 8 bits directly before a latch, never relies
on the shift register's previous content, and keeps the flash deselected (CS high) while writing the 595. Both
parts use SPI mode 0 (data sampled on the rising clock edge). The 595 at 3.3 V is specified at 5 MHz (2 V) and
25 MHz (4.5 V), roughly 13 MHz at 3.3 V by interpolation (**unverified**): write it at 9 MHz (PCLK2 / 8), read the
flash up to 36 MHz. Faster flash traffic only scrambles the 595's shift register, which is harmless.

**Against the bench lesson "NRST open drain":** the 595 drives NRST push-pull. The card's NRST is an input with a
pull-up, so that is fine as long as the card's PD7 is configured as NRST (option bytes; **unverified** for the V006
default, set it when the card is programmed). *[2026-10-20]* Verified: the reference manual (V1.4, 18.5) gives
RST_MODE = 10b as the V006's reset value (PD7 is NRST, pin input ignored for 12 ms after enabling; 11b would make it
a GPIO), and the bench V006 reads USER = 0xF7 (RST_MODE = 10b). A push-pull reset works: a V203 GPIO driving the bench V006's reset pin push-pull (10 ms low, then high, as the
595 does) restarted the card, which was enumerated again within 0.5–0.7 s (3 of 3, `bustest.py nrst`). On the
bench EVT's QFN-32 V006 (K8U7) the reset pin is PA7; on the card's TSSOP-20 it is PD7 (datasheet note 5). Without the series resistor nothing limits the current if a card
drives its own NRST low (an internal reset on parts that do that, or PD7 left as a GPIO output): the 74HC595's
output (about 25 mA short-circuit at 3.3 V) and the card pin survive it, and the firmware sees the card as missing.

## 4. Power

### 4.1 Path and parts

| Ref | Part | Value / note |
|---|---|---|
| J1 | USB-C receptacle, 16 pins (USB 2.0), hand-soldered | CC1, CC2 each 5.1 kΩ to GND (separate resistors); SBU open; shield to GND |
| U3 | SRV05-4 (C7420376, Promotional Extended), on D+, D−, CC1, CC2; VDD pin to VBUS_C | 0.3: the SRV05-4A (C20615829) had 3 in stock on 2026-10-20; the SRV05-4 is the same package and pinout (42 528 in stock); alternative H5VU13U (C20615795, 2 lines) |
| R | 22k / 33k (C31850 / C4216) | VBUS_C → PB15 (VBUS_DET): enables the D+ pull-up only with a computer present |
| J4 | 2-pin 2.54 mm header, external 5 V (≥ 1 A adapter), hand-soldered | |
| JP1 | 1×3 header + jumper: 1 = VBUS_C, 2 = +5V_SEL, 3 = +5V_EXT | no diode: the cards get the full 5 V; with EXT selected, VBUS only feeds VBUS_DET (self-powered) |
| F1 | PTC, **1206** (the footprint), I_hold 0.75 A, I_trip 1.5 A (*[2026-10-20]* Littelfuse 1206L075THYR, C99563, 16 V; the 1812 MF-MSMF075 named before does not fit), hand-soldered | not on the lists |
| D1 | SMAJ5.0A (C2925443) | after F1: an overvoltage or a reversed external supply makes D1 conduct and F1 trip |
| C | 10 µF (C19702) on +5V_IN | |
| U2 | XC6206P332MR (C5446), 1 µF in and out (C15849), 10 µF on +3V3 | fed from +5V_IN; 200 mA, load about 30 mA |
| R_BYP | 0 Ω 1206 (C17888), **fitted** | bridges the soft-start switch: +5V_IN = +5V_SLOTS |
| Q1 | AO3401A (C15127), P-channel soft start, **not fitted** | R_GS 1 MΩ (C22935), gate to GND 220 kΩ (C22961), C_GD 100 nF (C14663), all not fitted |
| C | 2 × 47 µF 10 V 1206 (C96123) on +5V_SLOTS, 10 µF (C19702) at each socket | |

**Inrush and the soft-start option:** each card filters its analog rail with 22 Ω + 3 × 100 µF (about 35 µF each at
5 V, spec 3.1), so each card limits its own inrush to 5 V / 22 Ω ≈ 230 mA peak, decaying with τ ≈ 22 Ω × 105 µF ≈
2.3 ms. With 8 cards that is about 1.8 A for a few milliseconds when the board is plugged in. It exceeds the USB 2.0
attach allowance (10 µF), but most computer ports and hubs tolerate it (their limit trips only after a longer
overload). So the soft start is not fitted by default: R_BYP is fitted, and the Q1 footprint stays.

**If a port or hub drops out at plug-in:** remove R_BYP and fit Q1, R_GS, R_G and C_GD. The drain then ramps at
about I_G / C_GD = (3 V / 220 kΩ − 2 V / 1 MΩ) / 100 nF ≈ 116 V/s, i.e. 5 V in about 40 ms, and the charging current
of about 0.95 mF stays near 110 mA. Final V_GS = −5 V × 220k / 1.22M ≈ −4.1 V; R_DS(on) about 60–65 mΩ gives 30 mV at
0.5 A. Hand estimate; simulate before fitting (proposed S14, ngspice, with the S10 card supply network). With Q1
fitted, the LDO (on +5V_IN) starts before the cards.

### 4.2 Host port

**Fitted** (user decision, 2026-10-20; on 2026-10-19 it was left unfitted because there was nothing to plug in).
JLCPCB assembles the ESD array U5, the capacitors, the HOST_EN pull-down, the fault pull-up and both LEDs (10 parts);
U4 and J2 are hand-soldered. Only the two 15 kΩ pull-down options stay unfitted. Until the host firmware runs, the
100 kΩ pull-down holds HOST_EN low, so the port stays unpowered; the firmware keeps USBFS off until then. The host
driver is being developed on the development board, whose USB-C goes to the same USBFS pins (controller.md).

No current-limited power switch is on the Basic or Promotional lists. The design uses the **TI TPS2051C**
(SOT-23-5, fixed 0.5 A limit, enable active high, open-drain fault output; hand-soldered; KiCad symbol
TPS2051CDBV). The fixed limit needs no R_ILIM, whose value would have depended on an unread datasheet formula
(0.2 proposed the adjustable TPS2553DBVR or SY6280AAC at about 300 mA). Input from +5V_IN, 1 µF; output
VBUS_HOST with 2 × 47 µF (C96123). USB 2.0 asks for 120 µF at a host port; the ceramics give about 40 µF at 5 V
(**risk**, usually harmless for a keyboard). HOST_EN (PB8, 100 kΩ pull-down) keeps the port off until the firmware
has configured the USB device and decided the power budget. HOST_FLT_N (PB9) has a 10 kΩ pull-up and also drives
the red fault LED (LED + 1 kΩ from +3V3 into the open-drain output). A yellow LED on VBUS_HOST (2.2 kΩ) shows that
the port is powered. ESD: a second SRV05-4 on D+/D−, VDD pin on VBUS_HOST. U4 sits on the west side of J2, next to
PB8/PB9.

USBFS in host mode needs 15 kΩ pull-downs on D+/D−; whether the V203's USBFS has them inside is **unverified**:
two 15 kΩ footprints, not fitted. *[2026-10-20]* The USBFS host control register has a bit that disables internal
D+/D− pull-downs (`USBOTG_UH_PD_DIS` in ch32fun's `ch32v20xhw.h`), so they exist. Measured on the development board
(same pins): with them on, D+ / D− discharge twice as fast as through a PC's 15 kΩ pull-downs alone, so they are
about 13–15 kΩ (12.8–24.5 kΩ over the USB tolerance of the reference). The 15 kΩ footprints stay unfitted. Likewise the USBD D+ pull-up is expected to be internal and switchable
(**unverified**, reference manual); a 1.5 kΩ footprint from PA12 to +3V3, not fitted.
*[2026-10-19]* Bench (controller.md 5): `EXTEN_USBD_PU_EN` does switch an internal pull-up on PA12 (PA12 rises in
about 80 ns with the bit set and the transceiver powered, never without it), but its strength against a host could
not be shown: the development board has no host on PA11 / PA12 (its USB-C goes to USBFS, PB6 / PB7), and the
powered transceiver itself pulls PA12 low, so the pull-up loses once the 40 kΩ GPIO pull-down is added. Keep the
1.5 kΩ footprint (fit it if the USBD build does not enumerate). USBFS's internal device pull-up works without an
external resistor (the board has none and enumerates). *[2026-10-20]* Shown: with PA11 / PA12 wired to the
development board's own USBFS host (controller.md 6), the USBD device enumerated at full speed in 162 ms on its
internal pull-up alone; the 1.5 kΩ stays unfitted (a computer as the host is still to try on the backplane).

### 4.3 Current budget

| Load | Current | Basis |
|---|---|---|
| 8 voice cards | 80 mA | about 10 mA each (spec 3.1, S10) |
| CH32V203 at 144 MHz | 12–20 mA | datasheet Table 4-6-1: 11.8 mA typ., all peripherals on; plus USB and I/O |
| Mixer | 0.34 mA | S12 (VREF from +3V3, no CJ431) |
| LEDs | about 3 mA | PWR 0.6, ACT 1.3, HOST 1.4 mA (FAULT off) |
| SWIO pull-up held low | 3.3 mA | only while one slot is being programmed |
| SPI flash (if fitted) | µA standby, up to about 25 mA while programming | |
| **Synth** | **about 110–120 mA** | design 4.2: 110 mA |
| Keyboard on USB-A (port not fitted at first) | 50–200 mA, limited at 0.5 A | U4 |
| **Total** | **at most about 425 mA** | inside a USB 2.0 port's 500 mA after configuration |

Before configuration a USB device may draw only 100 mA; the synth draws about 115 mA from power-up because the
cards' supply is not switched (**risk**, section 9; hosts rarely enforce it).

## 5. Mixer

The S12 two-bus circuit, unchanged (`s12_mixer.py --bus2`, spec 4). The pan is on the cards (S13), so every slot
has the same values.

**Per slot (7 parts, 56 for 8 slots):**

| Ref | Value | LCSC | Connection |
|---|---|---|---|
| C_IN_L, C_IN_R | 10 µF X5R 0603 | C19702 | pin 5 (AUDIO_L) / pin 7 (AUDIO_R) → 56k |
| R_IN_L, R_IN_R | 56k 1 % 0603 | C23206 | → L− / R− summing node |
| C_G | 10 µF X5R 0603 | C19702 | pin 6 (AUDIO_GND) → node Y_k |
| R_P_L, R_P_R | 56k 1 % 0603 | C23206 | Y_k → L+ / R+ |

The input capacitors keep the cards' 100 kΩ output bleeders off the 2.5 V summing nodes; C_G is shared by L and R
(each channel sees 5 µF: the card's 10 µF in series with it).

**Common (30 parts):** U_MIX MCP6002 (C7377): unit A sums L, unit B sums R, each inverting with R_F 20 kΩ ∥ C_F
47 pF C0G (C4184, C1671) from output to − input and R_F' 20 kΩ ∥ 47 pF from + input to VREF, so
out = VREF − 0.357 Σ (AUDIO_x_k − AUDIO_GND_k). VREF: a divider from the controller's +3V3 (XC6206), 10 kΩ / 27 kΩ
(C25804, C22967) with 10 µF (C19702), then a second RC stage, 10 kΩ / 10 µF: 2.41 V, corners 2.2 and 1.6 Hz,
unbuffered (user proposal, 2026-10-19; 0.2 had a CJ431 from the 5 V, 10 kΩ / 10 µF and an MCP6002 follower). The
summing amps' + inputs are VREF's only DC load (picoamps: the mirror network is AC coupled), and VREF reaches the
line out about 1:1 (through R_F' to the + input, divided by 3.9, then the noise gain 3.9). The LDO rejects
low-frequency ripple of the 5 V; the two RC stages take out the MCU's own load steps on +3V3 (USB frames and the
SYNC tick at 1 kHz, the activity LED): −72 dB at 100 Hz and −112 dB at 1 kHz from +3V3 to the line out, against
−36 / −56 dB with one stage (S12). The ADC tap's DC now follows the ADC's own 3.3 V. Op-amp rail: 47 Ω (C23182) + 22 µF
(C45783), 100 nF. Line out per channel: 220 Ω (C22962) + 10 µF to the jack, 100 kΩ bleeder
(C25803). ADC tap per channel: 15k / 27k (C22809 / C22967) + 330 pF C0G (C1664) at the ADC pin. Jack: 3.5 mm
stereo, hand-soldered.

**Simulated (S12, two buses):** 0.357 per card; 8 cards hard-panned in phase at the capped level give 3.95 Vpp,
2.0 dB below clipping; 8 centred cards 2.79 Vpp per channel (5.0 dB); flat −0.04 dB at 20 Hz, −0.09 dB at 20 kHz;
mixer noise 6.7 µV (one card) to 17.0 µV (8 slots); ground rejection −65 dB nominal, −45 dB typical and −29 dB worst
case with 1 % resistors (−26 dB at 20 Hz with ±20 % capacitors); L/R crosstalk −110 dB; supply rejection
−71 to −73 dB (the CJ431 reference: −69 to −72 dB, 17.5 µV; at a 4.6 V supply both keep 8 hard-panned cards
undistorted); 0.34 mA. ADC tap: DC 1.55 V, one centred card at −23 dBFS, 8 hard-panned cards at −2.3 dBFS, the
187.5 kHz carrier at −111 dBFS, about 60 dB signal-to-noise for one centred card at 384 kHz dual-mode sampling.

**Placement:** each slot's 7 parts sit in that slot's 10 mm column directly south of its socket, under the card
(section 7.4). The common block (both op-amps, the reference, the rail filter) sits at the west end of the slot
row, beyond slot 1, with at least 4 mm to slot 1's column. The jack sits on the west edge right beside it (0.3,
user decision): sockets → summing band → op-amps → line-out stage → jack, all at the west end, so the line-out run
is about 10 mm; the ADC dividers sit at the MCU, so the long runs carry the op-amps' low-impedance outputs
(electrically the same circuit as S12).

### 5.1 Effects slot *[2026-10-20]*

User decision: slot 1 can hold an **effects card** (reverb and similar, a separate future board in the card
format) instead of a voice. The slot needs a send, the mix into the card; everything else it already has: +5 V,
BCAST and SYNC (control, tempo), NRST, and its AUDIO_L / AUDIO_R / AUDIO_GND pins into the mixer.

| Part | Fitted | Connection |
|---|---|---|
| R79 0 Ω | yes | CLK → slot 1 pin 15 (net FX_P15), as on every other slot |
| R80 220 Ω | no | MIX_L → slot 1 pin 15: send L |
| R81 0 Ω | yes | SWIO_1 → slot 1 pin 14 (net FX_P14) |
| R82 220 Ω | no | MIX_R → slot 1 pin 14: send R |
| R83 220 Ω | no | slot 1 pin 3 (FX_RET_L) → LO_L: loop-through return L |
| R84 220 Ω | no | slot 1 pin 4 (FX_RET_R) → LO_R: loop-through return R |
| R71 / R75 220 Ω | yes | MIX_L / MIX_R → LO_L / LO_R: the normal line-out feed (remove for loop-through) |

Slot 1's pins 3 and 4 are not GND on the backplane (they are on every other slot): they carry the effects card's
loop-through output. A voice card ties them to its ground, which does not matter, since in voice mode they only
reach the not-fitted R83 / R84; slot 1 keeps GND on pins 8, 13 and 16 (and its AUDIO_GND on 6), plenty for a
card's 10 mA, and the mixer reads every card against its own AUDIO_GND.

Converting the slot: remove R79 and R81, fit R80 and R82 (the sends); for loop-through also remove R71 and R75 and
fit R83 and R84. All values are on the board's BOM. The 220 Ω isolate
the summing amps' outputs from the trace and the card's input capacitance. The sends carry the stereo mix at VREF
(2.41 V DC); the effects card AC-couples them. A voice card in slot 1 does not care: its pin 15 goes to a not-fitted
0 Ω link, and with the 0 Ω fitted it sees CLK and SWIO as before.

Two ways to use it, chosen by the effects card's firmware:

- **Mixing in:** the card returns the effect through its AUDIO pins into the mixer like a voice. The send then
  contains the card's own return (one summing stage), so the effect partly feeds back into itself. That is stable
  as long as the loop gain (mixer 0.357 × wet level × the effect's gain) stays below 1; the card measures it at
  start-up, caps the wet level (at about 0.5 loop gain without any cancellation) and may cancel its own return
  digitally (its delay is fixed: one codec clock for ADC and DAC); a limiter in the wet path guards against runaway.
- **Loop-through:** the card mutes its AUDIO pins and drives dry plus effect on pins 3 / 4, which then feed the
  line-out stage instead of the mixer (R83 / R84 fitted, R71 / R75 removed; the 10 µF after them AC-couples the
  card). No loop at all, and the instrument keeps its one line out (user proposal). A voice card in a slot converted
  for loop-through grounds the return: the line out stays silent, nothing is damaged.

In either case slot 1 then holds no voice (7 voices at most), loses CLK (an option, off by default) and SWIO (the
effects card, e.g. a CH32V307 with an ES8388 codec, is programmed over its own interface); the controller finds it
by enumeration like a card (a capability bit in HELLO) and maps MIDI CC 91 (reverb level) to it. Layout and
silkscreen: two labelled blocks of pairs north of the line out, each pair sharing its common pad. Under slot 1 the
sends, rows P15 (R79 | R80) and P14 (R81 | R82); north of the jack the line-out feed, rows L (R71 | R83) and R
(R75 | R84). The left column is headed V (the voice parts, fitted), the right one FX or LOOP, and one line states the
rule: "FX CARD: V OUT, FX/LOOP IN". Slot 1's CLK branch in the socket field is left out (the CLK reaches pin 15
through R79).

## 6. Connectors and mechanics

### 6.1 Coordinates

Board 100 × 100 mm, x to the east, y to the north, origin at the south-west corner, seen from the top (component)
side. The rear edge (y = 100) carries the user connectors. The slot row runs along x: slot k (1 … 8) has its socket
centre at x_k = 20 + 10 (k − 1) mm (20 … 90), y_s = 30 mm. The cards cover y = 5 … 55. The controller strip is
y = 58 … 100 (42 mm, 13 mm more than in 0.1).

Use of the extra room compared with 95 × 85: the analog zone in the west is 16 mm wide (mixer common block,
line-out run) with 4 mm more to slot 1; the east margin beside slot 8 is 6 mm wide (the +5 V trunk, SYNC and the
bus descent no longer squeeze); the strip has room for U6 with its resistor arrays, the flash corner, and the power
entry along the east edge without crowding the USB-C connector.

### 6.2 Slot sockets and orientation

Eight vertical 2×8 female headers, 2.54 mm, about 8.5 mm high, through-hole, hand-soldered (KiCad
`Connector_PinSocket_2.54mm:PinSocket_2x08_P2.54mm_Vertical`). The long axis runs north–south; the cards stand in
y–z planes, their 50 mm width along y, centred on the socket (card edges at y = 5 and y = 55).

The card (spec 3.3, `hw/voice.py` J1): seen from its part side with the connector down, pin 1 is on the right;
pins 1–8 (supply, audio) on the right half, 9–16 (bus) on the left. On the card, the pin-1 row of the right-angle
header is the outer pad row, whose pins bend at the upper level, farther from the card surface.

**On the backplane:**

- **Socket pin 1 is at the south-west corner of each socket** (the end away from the controller strip, on the
  west row). Odd pins 1, 3, …, 15 form the west row from south to north, even pins the east row.
- The cards' **part side faces west** (toward slot 1 and the mixer end). Check: a viewer facing a card's part side
  looks east, and the right hand then points south, to pin 1.
- The card plane lies about 3.3 mm east of the socket centre line, assuming the usual right-angle geometry (pin
  rows 1.27 and 3.81 mm above the card, 1.6 mm board; **check with the actual header**). A card then occupies about
  x_k − 3.5 … x_k + 4.1 mm (6 mm parts on the west face), which leaves about 2.5 mm between neighbours, and
  slots 1 … 8 span x = 16.5 … 94.1 mm.
- Resulting socket field (positions numbered from the south, y = 21.1 + 2.54 (n − 1) mm):

```
            north (controller strip)
         west row        east row
 pos 8   15 CLK_IN       16 GND
 pos 7   13 GND          14 SWIO
 pos 6   11 RETURN       12 NRST
 pos 5    9 SYNC         10 BCAST
 pos 4    7 AUDIO_R       8 GND
 pos 3    5 AUDIO_L       6 AUDIO_GND
 pos 2    3 GND           4 GND
 pos 1    1 +5V           2 +5V      <- pin 1, south-west corner
            south (far edge)
 card: part side faces west, board about 3.3 mm east of the centre line
```

- In KiCad, with pin 2 of `PinSocket_2x08_P2.54mm_Vertical` at x = −2.54 mm and pins counting along +y, this is a
  rotation of 180° (**check** against the library footprint before generating the board).
- So the audio and supply end of every socket faces south, away from the controller, and the bus end faces the
  controller strip.

### 6.3 Card guides, mounting holes

- **Card guides:** two slotted rails along x, one at each card side edge (y = 5 and y = 55; the cards keep 1.5 mm
  along both side edges free of parts), 3D-printed, each fixed by M2.5 screws at its ends (x ≈ 14 and x ≈ 97). The
  grooves sit at the card plane (x_k + 3.3 mm), not at the socket centre: a card turned by 180° would need its plane
  at x_k − 3.3 mm and does not enter the grooves, so the guides also key the orientation. Keep-out on the backplane:
  y = 2.5–6.5 and 53.5–57.5 mm along the slot row. For the first build the headers alone hold the cards (design 7.3);
  the holes are there for later.
- **Mounting holes:** 4 × M3 (3.2 mm, 6 mm keep-out) at (3.5, 3.5), (96.5, 3.5), (3.5, 96.5), (96.5, 96.5) mm.

### 6.4 Other connectors (all hand-soldered)

| Ref | Connector | Position |
|---|---|---|
| J1 | USB-C 16-pin receptacle (e.g. GCT USB4105) | rear edge, east of J2 (0.3; was the east edge) |
| J2 | USB-A receptacle, right-angle, THT | rear edge, x ≈ 66–80, above the MCU |
| J3 | 3.5 mm stereo jack (e.g. CUI SJ1-3523N) | west edge beside the mixer, y ≈ 20–32 (0.3; was the rear edge) |
| J4 | 2-pin header, external 5 V | east edge, y ≈ 74–78 |
| JP1 | 1×3 header + jumper, supply source | east edge, next to J4 |
| JP2 | 1×3 header + jumper, BOOT0 (+3V3 / BOOT0 / GND) | north-west of the MCU, near pin 44 |
| JP3 | 2-pin jumper, MIDI opto → PA10 (not fitted) | at J6 |
| J5 | 1×4 header SWD: +3V3, SWDIO, SWCLK, GND (WCH-LinkE) | rear edge, east of J1 |
| J6 | 1×3 header USART1: GND, TX (PA9), RX (PA10) | east of the MCU |
| J7 | 1×3 header MIDI in: DIN pin 4, DIN pin 5, shield (not fitted) | north-west, with the MIDI option parts |
| J10–J17 | 2×8 sockets | slot row |

**MIDI in (not fitted):** rev 0.1's circuit at 3.3 V: 220 Ω (C22962) into the LTV-817S (C109227) LED, 1N4148W
(C81598) across it, collector with 1 kΩ (C21190) to +3V3, to PA10 through JP3. J7 takes a panel-mount 5-pin DIN or
a TRS jack on wires. The LTV-817S is slow for 31.25 kbaud at a 1 kΩ load and its CTR (≥ 50 %) is marginal at a
3.3 V loop (**unverified**; a 6N138 or H11L1 would meet the MIDI spec but is not on the lists).

**No SWIO header on the backplane** (spec 4 proposed one until the controller programs the cards): every card's
own 3-pin programming header stays reachable at its top edge with the card in the backplane, and the backplane's
1 kΩ pull-up is in parallel with the WCH-LinkE's. The V203 must keep that slot's SWIO pin as an input meanwhile.
Connect only SWIO and GND, or power the backplane: the LinkE's 5 V would otherwise feed the whole slot rail through
the card's B5819W.

**LEDs** (strip, visible beside the cards): PWR red (C2286) from +3V3 through 2.2 kΩ; ACT yellow (C89811, 0603) on PB2
through 1 kΩ; HOST yellow on VBUS_HOST; FAULT red on HOST_FLT_N.

### 6.5 SPI flash (not fitted)

**Parts:** reference W25Q128JVSIQ (Winbond, 128 Mbit = 16 MB, SOIC-8 208 mil, LCSC C97521, Basic, US$ 2.55); the
user's stock is BY25D16ASTIG (Boya, 16 Mbit = 2 MB).

**Package:** the user's BY25D16ASTIG are SOP-8 208 mil (checked on the parts), the same package as the
W25Q128JVSIQ, so the standard KiCad footprint `Package_SO:SOIC-8_5.3x5.3mm_P1.27mm` takes either; no dual-width
footprint needed.

**Circuit:** VCC to +3V3 with 100 nF; CS_N (PA15) with 10 kΩ to +3V3 (deselected while the V203 boots); WP_N and
HOLD_N each with 10 kΩ to +3V3; DI = MOSI (PB5), DO = MISO (PB4), CLK = SCK (PB3). The pull-ups and the capacitor
are fitted (cheap, harmless without the flash); only the flash itself is not fitted. On W25Q128JV variants with the
quad-enable bit set, WP and HOLD act as IO2/IO3; pulled high they are idle in single-SPI use.

**Command set used by the firmware** (single SPI, mode 0, 24-bit addresses, which cover 16 MB exactly):

| Command | Code | W25Q128JV | BY25D16 |
|---|---|---|---|
| Read | 0x03 | yes (up to 50 MHz) | expected |
| Fast read (1 dummy byte) | 0x0B | yes | expected |
| Write enable | 0x06 | yes | expected |
| Read status 1 (busy bit 0) | 0x05 | yes | expected |
| Page program (256 B) | 0x02 | yes | expected |
| Sector erase 4 KB | 0x20 | yes | expected |
| JEDEC ID | 0x9F | EF 40 18 | 68 40 15 expected |

The BY25D16 column is the standard 25-series set that Boya's D parts follow (**unverified**: no BY25D16 datasheet
was read). The firmware reads 0x9F and takes the size from the third byte (2^n bytes: 0x15 = 2 MB, 0x18 = 16 MB).

**Use:** patch library and setups beyond the V203's 64 KB, voice-card firmware images for SWIO programming
without the computer, logs. Optional.

### 6.6 Board outline and placement

100 × 100 mm, 2 mm corner radius. Sketch at 1 mm per character east–west and about 3 mm per line north–south (rough;
the slot row and the strip boundary are to scale):

```
+---------------------------------------------------------------------------------------------------+  y = 100 rear
| o    LED PWR ACT   [RESET]   U4 (DNP)  [    J2 USB-A (DNP)   ]  [ J1 USB-C ]  J5 SWD             o  |
|                                                                   USB-C passives, ESD               |
| MIDI in (DNP)       U7 flash     JP2 BOOT0                                                   JP1     |
|  J7, opto           (DNP)              Y1  +-------+                                   F1  supply  |
|                     ADC dividers           |  U1   |    J6 UART      test points       D1  J4 5V   |
|                  U6 595                    | V203  |                          LDO, bulk  R_BYP      |
|                                            +-------+                                           #  |
|                SWIO pull-ups          (fan-out zone)     bus resistors, bus test points        #  |
|. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .#.|  y = 58
|               ==================================================================================# |  north guide rail
|                 bus tracks in the socket field gaps: SYNC 4|5, BCAST 5|6, RETURN 6|7, CLK 7|8   # |
|line-out          S1        S2        S3        S4        S5        S6        S7        S8       # |
|stage+-+          +---+     +---+     +---+     +---+     +---+     +---+     +---+     +---+     # |  y = 40
|  J3   |          |   |     |   |     |   |     |   |     |   |     |   |     |   |     |   |     # |
|<LINE  |          |   |     |   |     |   |     |   |     |   |     |   |     |   |     |   |     # |
| OUT   |          |   |     |   |     |   |     |   |     |   |     |   |     |   |     |   |     # |
|+------+          |   |     |   |     |   |     |   |     |   |     |   |     |   |     |   |     # |
|VREF filter       |   |     |   |     |   |     |   |     |   |     |   |     |   |     |   |     # |
|feedback R/C      |1  |     |1  |     |1  |     |1  |     |1  |     |1  |     |1  |     |1  |     # |
|U8 MCP6002        +---+     +---+     +---+     +---+     +---+     +---+     +---+     +---+     # |  y = 20
|47R/22u       #################################################################################### |  +5V rail
|               per-slot mixer parts (7 per slot), caps across the +5 V rail                        |
|               summing band L-/L+  R+/R-  (bottom layer)  ===> to U8                               |
|                                                                                                   |
| o             ==================================================================================  |  south guide rail
+---------------------------------------------------------------------------------------------------+  y = 0
 x = 0            x = 20 (slot 1)                              x = 70 (6)  80 (7)  90 (8)           x = 100
```

`#` = the +5 V trunk from the power entry down the east margin (x ≈ 98) and the +5 V rail along the south ends of
the sockets. The cards cover y = 5 … 55 over the whole slot row; everything there is low (≤ 8 mm under the card
edges). The controller strip (y = 58 … 100) is not covered.

Main positions as drawn in 0.3 (user decision: spread out, nothing crowded into one corner): U1 (MCU) in the middle
of the strip near (52, 76), so the bus riser drops between slots 4 and 5; on the rear edge from west to east the
MIDI option, the LEDs and the reset button, J2 (USB-A) above the MCU's host pins, J1 (USB-C) and J5 (SWD); Y1
west of U1; U7 (flash) and U6 (595) west of U1; J6 (UART) east of U1; power entry (J4, JP1, F1, D1, R_BYP/Q1,
bulk) on the east edge, y ≈ 58–75; mixer common block and the line-out jack J3 on the west edge, x = 0 … 15
(KiCad y = 100 − y).

Zones: analog in the west (mixer common, the line-out run up the west margin to J3, the ADC taps along y ≈ 80 to the
MCU); USB and power in the east; the MCU in between. Digital parts keep at least 15 mm from J3 and the mixer block
(U6 is the closest, at about 20 mm from J3).

## 7. Layout rules (4 layers as drawn; written for 2)

### 7.1 Stack and general rules

- **As drawn (0.3): JLCPCB 4-layer, 1.6 mm** (user decision, 2026-10-19). F.Cu: all parts and signals; In1: GND,
  solid; In2: +3V3 under the controller strip (y < 42 mm in KiCad coordinates) and GND under the slot area; B.Cu:
  signals, the summing band (7.4) directly against the In2 ground. Ground pours on both outer layers, stitched to
  the planes on a grid. +5V stays on its pre-routed trunk and rail (7.2). Routed: 0 DRC violations, 0 unconnected,
  no isolated copper; 2.8 m of track on F.Cu and 1.8 m on B.Cu, 1783 vias (1629 of them GND stitching).
- **Why not 2 layers:** this document planned a 2-layer board (the rules below were written for it). Routed on two
  layers, the MCU area left a few nets open in every run (+3V3 to the VDD pins, the SPI and SWD lines; the bottom
  pour broke into islands around the MCU), and a local ground star and keep-outs did not fix it. With the In1 / In2
  planes every supply and ground pin is one via, and the rest routes cleanly. `BP_LAYERS=2` routes the same
  placement on two layers as a check (`hw/gen_pcb_bp.py`).
- 0.2 mm tracks and 0.2 mm clearance by default; supplies 0.3–1.0 mm; vias 0.3/0.6 mm, tented. Passives 0603 (the
  47 µF and the 0 Ω bypass in 1206, 22 µF and the input capacitors in 0805).
- 2-layer plan, kept for reference: bottom ground pour over the whole board, breaks only for short crossings
  (7.6) and the summing band; top: all parts, long tracks, ground fill.

### 7.2 Supplies

- +5V_SLOTS on top: from the power entry (through R_BYP or Q1) down the east margin (x ≈ 98, 1.0 mm) to the south
  end of the slot row, then as a rail along y ≈ 17.5 mm (0.4 mm is enough for 110 mA, under 10 mV drop over the row)
  with one stub per socket to pins 1/2 and a 10 µF from pin 2 to the ground pins 3/4. Its return runs in the bottom
  pour directly under it, which is continuous with the sockets' ground pins.
- The rail continues west to the mixer's 47 Ω / 22 µF.
- +3V3 reaches the MCU's VDD pins through a top copper island under the LQFP body (VSS pins to a ground island with
  vias to the pour); VDDA through the ferrite with its own 1 µF + 100 nF at pin 9. U2 sits east of the MCU near the
  power entry. U6, U7 and the pull-ups tap +3V3 with short hops where they are cut off by a bundle.
- +5V_IN to U4 (west of J2): along the rear edge, with short bottom hops under the USB-C and USB-A pairs.

### 7.3 Voice bus and slot fan-out

- **Bus tracks run inside the socket field**, one per gap between pin positions, so each reaches its pin with a
  short jog and no crossing: SYNC in gap 4|5 (jog north to pin 9), BCAST in gap 5|6 (jog south to pin 10), RETURN in
  gap 6|7 (jog south to pin 11), CLK in gap 7|8 (jog north to pin 15). 0.2 mm tracks pass between the 1.7 mm socket
  pads with 0.32 mm clearance. Between sockets they run straight along x.
- SYNC enters the row from the east end (PA8 is the easternmost slot-side pin; it descends at x ≈ 95, between
  socket 8 and the +5 V trunk). BCAST, RETURN and CLK come down as a riser between slots 6 and 7 and branch both
  ways. Where the riser passes the NRST bundle, the CLK branch and the RETURN branch it takes short bottom hops.
- Series resistors (33 Ω on BCAST, SYNC, CLK) and the RETURN pull-up (1 kΩ) sit at the MCU.
- **SWIO** leaves each socket on the bottom layer (pin 14 is through-hole), along the outside of the east row,
  north under the RETURN, CLK and NRST tracks to a via about 2 mm north of the NRST bundle (y ≈ 48). From there the
  8 SWIO lines run on top as a ribbon in slot order to the MCU (SWIO 1–6 from PA2–PA7, SWIO 7–8 from PB12/PB13),
  with the 1 kΩ pull-up arrays (C20197) at the MCU. Keep them at least 0.4 mm from CLK and from each other over long
  runs; they idle at 1 kΩ.
- **NRST bundle:** U6 sits north-west of the MCU (its outputs drive the slots directly). The 8
  static NRST lines run south-west through the strip, down the east edge of slot 1's column (x ≈ 21–24, still 5 mm
  from the analog margin), then east along the north edge of the socket field (y ≈ 42–46, 8 tracks at 0.45 mm
  pitch). Each slot's pin 12 leaves the socket on the bottom (in the gap between the two pad rows), runs north under
  the field tracks, and vias up onto its own bundle track. The bundle tapers as it drops one line per slot and
  ends at slot 8, west of the SYNC descent.
- **SPI:** pins 38–41 sit in the corner between the USB pairs; all four SPI lines leave it westward with short
  bottom hops under the USB-A pair, to U7 (flash) and U6 (595) west of the MCU. The latch and output enable come from
  PC13/PC14 at
  the MCU's north-west corner, so they need no hop. Keep SCK at least 5 mm from the ADC taps and 15 mm from J3.

### 7.4 Mixer feeds

- From each socket, AUDIO_L (pin 5), AUDIO_GND (pin 6) and AUDIO_R (pin 7) run south on top, side by side
  (pin 6 in the gap between the pad rows, pins 5 and 7 outside the west row). The three input capacitors (C_IN_L,
  C_IN_R, C_G) sit across the +5 V rail, which passes between their pads (0603 pad gap 0.65 mm, rail 0.25 mm there
  with 0.2 mm clearance; or 0805 capacitors). No hop is needed.
- **Summing band:** the four summing nodes run along the whole row as two pairs, L−/L+ and R+/R−, each pair side
  by side so that pickup is common to − and + (S12: common pickup cancels, out = 20 kΩ × (i₊ − i₋)). A planar top
  route is impossible because every slot must tap all four tracks, so the band runs on the **bottom** layer under the
  per-slot resistors (y ≈ 9–13; guard ground tracks between the pairs and outside, 0.2/0.2 mm, about 2.6 mm wide),
  and each 56k resistor drops onto its track through a via. The top above the band is ground fill. This is the one
  long break of the bottom pour. It carries no ground current: the cards return through the pour north of it, under
  the +5 V rail. The south strip of pour (y < 9 mm) connects only at the mixer end.
  Alternative if the pour must stay unbroken: the band on top, with the resistors bridging the nearer tracks (0603
  over one, 0805 over two, 1206 over three).
- The summing nodes end at the op-amp inputs at the west end with R_F, C_F, R_F' and C_F' right at the pins. The VREF
  divider and its 10 µF stay inside the mixer block (+3V3 reaches it as a thin, static track).
- Line out L/R from the op-amps: a few mm north to J3 on the west edge, 220 Ω + 10 µF + 100 kΩ between them. ADC
  taps: from the op-amp outputs up the west margin and along the strip to PA0/PA1; 15k/27k/330 pF at the pins. They
  cross the NRST bundle's descent with two short bottom hops on the low-impedance section.

### 7.5 USB, crystal, separation

- USB-C pair (PA11/PA12 → J1) and USB-A pair (PB6/PB7 → J2): short (≤ 25 mm), side by side (0.3 mm tracks,
  0.2 mm gap), no vias, ESD part at the connector. Full speed does not need controlled impedance at this length. The
  bottom hops of SCK/MOSI and +5V_IN under them are 1–2 mm each; the reference plane under a pair is broken only
  there.
- Crystal Y1 within 5 mm of pins 5/6, load capacitors at the crystal, ground fill around it, no tracks under it.
- **Separation:** no digital track west of x = 16 mm or within 5 mm of the summing band, the mixer block or the
  line-out run (the static NRST bundle keeps 5 mm). CLK only in its gap 7|8 track and the riser. USB pairs, the
  power entry and U2 stay in the east part of the strip. Bus tracks are at least 10 mm from the summing band (the
  socket's pin positions 1–4 lie between).

### 7.6 Bottom-layer breaks (expected)

| Where | Count | Length |
|---|---|---|
| SWIO exits per socket (under RETURN, CLK, NRST bundle) | 8 | 10–12 mm, inside and just north of the socket footprint |
| NRST exits per socket (under the field tracks) | 8 | 6–10 mm, inside the socket footprint |
| Riser past the NRST bundle, CLK and RETURN | 3 | 2–5 mm |
| ADC taps past the NRST bundle | 2 | 4–5 mm |
| SCK, MOSI past the USB-A pair | 2 | 1–2 mm |
| +5V_IN past the USB-C and USB-A pairs | 2 | 2–3 mm |
| VBUS_DET (PB15) past SYNC | 1 | 1–2 mm |
| Summing band (section 7.4) | 1 | 70 mm, deliberate |

## 8. BOM

Prices are the unit prices in `parts/jlcpcb_basic_and_promotional_parts.csv`; P = Promotional Extended, B = Basic,
E = Extended, H = hand-soldered, DNP = not fitted.

### 8.1 Assembled (JLCPCB)

| Group | Part | LCSC | Lib | Qty |
|---|---|---|---|---|
| Controller | crystal 8 MHz, 20 pF, ±10 ppm, 5032 (X50328MSB2GI) | C115962 | B | 1 |
| | 30 pF C0G 0603 (crystal) | C1658 | B | 2 |
| | 100 nF X7R 0603 (VDD × 3, VDDA, NRST) | C14663 | B | 5 |
| | 1 µF 0603 (VDDA) | C15849 | B | 1 |
| | 10 µF 0603 (+3V3) | C19702 | B | 1 |
| | ferrite BLM18PG121SN1D (VDDA) | C14709 | B | 1 |
| | 10 kΩ (BOOT0, PB2, HOST_FLT_N) | C25804 | B | 3 |
| LDO | XC6206P332MR | C5446 | B | 1 |
| | 1 µF 0603 | C15849 | B | 2 |
| USB-C | 5.1 kΩ (CC1, CC2) | C23186 | B | 2 |
| | SRV05-4 ESD | C7420376 | P | 1 |
| | 22 kΩ / 33 kΩ (VBUS_DET) | C31850 / C4216 | B | 1 + 1 |
| | 0 Ω (D± series positions) | C21189 | B | 2 |
| Power | SMAJ5.0A | C2925443 | P | 1 |
| | 10 µF 0603 (+5V_IN) | C19702 | B | 1 |
| | 0 Ω 1206 (R_BYP, soft-start bypass) | C17888 | B | 1 |
| | AO3401A, 1 MΩ, 220 kΩ, 100 nF (soft start) | C15127, C22935, C22961, C14663 | B | DNP (4) |
| | 47 µF 10 V 1206 (+5V_SLOTS) | C96123 | B | 2 |
| | 10 µF 0603 (one per socket) | C19702 | B | 8 |
| Host port | 1 µF (U4 input), 2 × 47 µF 1206 (VBUS_HOST) | C15849, C96123 | B | 3 |
| | SRV05-4 ESD (host) | C7420376 | P | 1 |
| | 100 kΩ (HOST_EN), 10 kΩ (HOST_FLT_N pull-up) | C25803, C25804 | B | 2 |
| | LED yellow 0603 + 2.2 kΩ (host on), LED red 0603 + 1 kΩ (fault) | C89811, C4190, C2286, C21190 | P / B | 4 |
| Status | LED red 0603 + 2.2 kΩ (PWR), LED yellow 0603 + 1 kΩ (ACT) | C2286, C4190, C89811, C21190 | B / P | 4 |
| Bus | 33 Ω (BCAST, SYNC, CLK) | C23140 | B | 3 |
| | 1 kΩ (RETURN pull-up) | C21190 | B | 1 |
| | 4 × 1 kΩ array 0603x4 (SWIO pull-ups) | C20197 | B | 2 |
| NRST driver | 74HC595D (U6), 100 nF | C5947, C14663 | B | 1 + 1 |
| | 10 kΩ (OE_N pull-up) | C25804 | B | 1 |
| SPI flash | 10 kΩ (CS_N, WP_N, HOLD_N), 100 nF | C25804, C14663 | B | 3 + 1 |
| | W25Q128JVSIQ (U7) | C97521 | B | DNP (1) |
| Mixer, per slot | 10 µF 0603 (C_IN_L, C_IN_R, C_G) | C19702 | B | 24 |
| | 56k 1 % (R_IN_L, R_IN_R, R_P_L, R_P_R) | C23206 | B | 32 |
| Mixer, common | 20k (R_F, R_F'), 47 pF C0G (C_F, C_F') | C4184, C1671 | B | 4 + 4 |
| | 220 Ω, 100k, 15k, 27k (per channel) | C22962, C25803, C22809, C22967 | B | 2 each |
| | 330 pF C0G (ADC), 10 µF (C_OUT × 2, C_REF × 2) | C1664, C19702 | B | 2 + 4 |
| | 10k × 2, 27k (VREF), 47 Ω, 22 µF 0805, 100 nF | C25804, C22967, C23182, C45783, C14663 | B | 6 |
| | MCP6002T-I/SN | C7377 | P | 1 |
| MCU | CH32V203C8T6 (U1), *[2026-10-20]* from the user's JLCPCB personal stock | C3001172 | E | 1 |
| MIDI | 220 Ω, 1N4148W, LTV-817S, 1 kΩ; JP3 0 Ω or 2-pin jumper | C22962, C81598, C109227, C21190, C21189 | B | DNP (5) |

**Totals (as drawn, 0.3; host port, effects slot and the assembled MCU 2026-10-20):** 153 assembled SMD parts (85
of them the mixer: 56 per slot + 29 common, i.e. section 5's 30 without the hand-soldered jack; ADC dividers
included), 37 distinct LCSC numbers, all Basic except four Promotional Extended (C7377, C2925443, C7420376, the
yellow LED C89811) and one Extended, the MCU (C3001172, E; JLCPCB may charge its loading fee even from personal
stock). Parts cost at the list prices: **about US$ 6.2 per board** (mixer 2.7; the host port 0.7; the MCU 0.88). Not fitted at first: the soft start, MIDI in, the flash, the USB pull-up / pull-down options. The
flash adds US$ 2.55 when a W25Q128JVSIQ is fitted (the BY25D16ASTIG is own stock).

### 8.2 Hand-soldered

| Ref | Part | Note | Rough price (**unverified**) |
|---|---|---|---|
| U4 | TPS2051C (DBV, SOT-23-5) | not on the lists; fitted since 2026-10-20 | 0.3–1.0 |
| U7 | BY25D16ASTIG (own stock) or W25Q128JVSIQ | not fitted at first; SOIC-8 208 mil (`SOIC-8_5.3x5.3mm_P1.27mm`) | – / 2.55 |
| F1 | PTC 0.75 A, 1206 (1206L075THYR) | not on the lists | 0.1–0.2 |
| J1 | USB-C 16-pin | | 0.3–0.6 |
| J2 | USB-A, THT | | 0.2–0.4 |
| J3 | 3.5 mm stereo jack | | 0.2–0.5 |
| J10–J17 | 8 × 2×8 female header, 2.54 mm, vertical | | 1.2–3.0 |
| J4, J5, J6, JP1, JP2, (J7, JP3) | pin headers, jumpers | | 0.3 |
| SW1 | reset button (optional): TS-1187A-B-A-B, C318884 (Basic, could also be assembled) | | 0.02 |

About US$ 3–6 per board without the MCU and the flash. **Per board: about US$ 8–11 in parts**, plus the PCB
(100 × 100 mm, still in JLCPCB's smallest price class) and the order-level assembly fees, which dominate at a
quantity of a few.

## 9. Open points and risks

| Topic | Issue | Proposal |
|---|---|---|
| Inrush | without the soft start, about 1.8 A for a few ms at plug-in (8 × 230 mA through the cards' 22 Ω) | accept; if a port or hub drops out, remove R_BYP and fit Q1 + RC (values to simulate first, S14) |
| USB unit load | about 115 mA before configuration (limit 100 mA); the cards' supply is not switched | accept (hosts rarely enforce it) |
| 595 power-up | the cards run freely until the controller firmware resets them (no NRST pull-downs, by design); PD7 must be configured as NRST on every card (V006 option-byte default unverified; *[2026-10-20]* verified: RST_MODE = 10b by default, 3.5) | card programming sets the reset function; bench-check a 595-driven reset on the first card |
| 595 speed at 3.3 V | about 13 MHz by interpolation (unverified) | write it at 9 MHz |
| SPI remap 1 layout | SCK and MOSI must leave the corner between the USB pairs: two short hops under the USB-A pair | accepted (user decision); SPI1 default pins (PA5–PA7) would avoid the hops but take three SWIO pins |
| Flash commands | BY25D16 command set and JEDEC ID (68 40 15) assumed, no datasheet read | read 0x9F at bring-up; firmware sizes the part from the ID |
| MIDI on USART1 | MIDI in and the UART bootloader / debug RX share PA10 | JP3 not fitted by default; fit only for DIN MIDI |
| Host switch | none on the lists | TPS2051C (fixed 0.5 A), hand-soldered; the port was not fitted at first, fitted since 2026-10-20 |
| Host VBUS capacitance | 120 µF asked by USB 2.0; ceramics give about 40 µF | accept for keyboards; a 100 µF electrolytic footprint if trouble shows |
| USB pull-ups | internal D+ pull-up of USBD and host pull-downs of USBFS unverified. *[2026-10-19]* USBD: the pull-up exists and is switchable (`EXTEN_USBD_PU_EN`), its strength against a host is not shown (no host on PA11 / PA12 on the bench board, 4.2); USBFS device pull-up: works without a resistor. *[2026-10-20]* Both shown: USBD enumerates on its internal pull-up (against the V203's own USBFS host), the USBFS host pull-downs measure about 13–15 kΩ (4.2) | DNP footprints (1.5 kΩ, 2 × 15 kΩ); enumerate the USBD build once (a cable to PA11 / PA12, `make USB=usbd`) before deciding the 1.5 kΩ |
| Bootloader port | datasheet 2.5.2: USART1 and USB, which USB not stated. *[2026-10-19]* a software jump into the system flash made a device appear on USBFS that did not take an address (inconclusive; not tested with BOOT0 = 1) | keep USART1 (J6) free (JP3 out); test with the BOOT0 jumper and wchisp on the development board |
| 5 V on slot lines | SWIO 1–6 on non-FT pins; only a reversed card can stress them | keyed card guides, silkscreen; FT for SYNC, RETURN, SWIO 7/8 |
| Socket geometry | card-plane offset (3.3 mm) and the KiCad rotation (180°) assume standard parts | check with the chosen header and socket before generating the board |
| CLK_IN | 24 MHz over about 100 mm and 8 stubs (Table 4-21: 30 MHz into 50 pF in 50 MHz mode); the V006's input level for an external clock unverified; EMI near the ADC (PB1 is 8 pins from PA0) | option only, off by default; measure on 1–2 cards first |
| Summing band | the one long break in the bottom pour | justified in 7.4; alternative: top band with bridging resistors |
| Pin budget | 34 of 37 used, 3 free (PC15, PB0, PB14), all hemmed in by ribbons | test pads; PC15 as a slow input if needed |
| SWIO from the V203 | bit-banged one-wire timing at 144 MHz not yet shown (controller.md 4) | develop on the V203 board + board 1 first |
| ESD part stock | 2026-10-20: SRV05-4A (C20615829) 3 in stock, so the design uses the SRV05-4 (C7420376, 42 528) | check at order time; H5VU13U (C20615795) as fallback |
| Crystal | C115962 has 80 Ω ESR, the datasheet's recommended maximum (Table 4-11); gain margin about 30 (estimate: start-up g_m 17 mA/V against about 0.6 mA/V needed) | fine; C12674 (HC-49S, 70 Ω) as alternative |
| MIDI DIN | LTV-817S speed and CTR at 3.3 V | not fitted; test if wanted, or a 6N138 by hand |
| Docs to update | done in 0.3 (spec, design, controller.md, midi.md now match this document) | - |
