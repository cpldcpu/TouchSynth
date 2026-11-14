# TouchSynth Poly: parts to buy for the first build

Status: 2026-10-20, for the boards ordered that day. Everything JLCPCB does not assemble, taken from the design
sources (`hw/voice.py`, `hw/backplane.py`: parts that are neither assembled nor marked not fitted). LCSC numbers and
stock are from JLCPCB's parts search on 2026-10-20: check them again when ordering. Parts marked "not fitted" in the
designs (soft start, MIDI in, SPI flash, the effects slot's 220 Ω and the USB resistor options) are not listed.

## Voice card (per card)

| Ref | Part | Qty | Order as | Note |
|---|---|---|---|---|
| U4 | CH32V006F8P7, TSSOP-20 | 1 | own stock | hand-soldered; check PD4 / PD5 for bridges (board 1 had one) |
| J1 | pin header 2 × 8, 2.54 mm, **right angle**, male | 1 | generic | the backplane connector on the card's bottom edge; pairs with the backplane's vertical 2 × 8 socket (card plane 3.3 mm from the socket row, backplane.md 6.2) |
| J2 | pin header 1 × 3, 2.54 mm, right angle, male | 1 | generic | programming: 5V, SWIO, GND (WCH-LinkE) |
| J3 | pin header 1 × 3, 2.54 mm, right angle, male | 1 | generic | line out: L, R, GND |

## Backplane (per board)

| Ref | Part | Qty | Order as | LCSC (stock 2026-10-20) | Note |
|---|---|---|---|---|---|
| J10–J17 | socket 2 × 8, 2.54 mm, **vertical**, female, about 8.5 mm high | 8 | generic | | the slots; their height sets the card position (backplane.md 6.2) |
| J1 | USB-C receptacle, GCT USB4105 (16 pins, USB 2.0) | 1 | USB4105-GF-A-120 or -060 | C5184243 (3 596) / C3025063 (1 310) | footprint `USB_C_Receptacle_GCT_USB4105-xx-A_16P`; the suffix is the variant, pick it by GCT's datasheet for a 1.6 mm board. **Drop-in alternative:** Korean Hroparts TYPE-C-31-M-12, C165948 (345 982): same pinout, pegs and shell tabs within 25 µm, body at the same edge position; its recommended pads are 0.5 mm longer toward the edge, so on this footprint the lead tips have less fillet: hand-solder with flux |
| J2 | USB-A receptacle, Molex 67643, right angle, THT | 1 | 67643-0910 | C2798029 (4 411) | host port |
| J3 | 3.5 mm stereo jack, CUI SJ1-3523N | 1 | SJ1-3523N | C20182914 (95) | line out; low stock, order early |
| U4 | TPS2051C, SOT-23-5, 0.5 A USB power switch | 1 | TPS2051CDBVR | C129581 (21 450) | host port power |
| F1 | PTC fuse, **1206**, I_hold 0.75 A, I_trip 1.5 A | 1 | Littelfuse 1206L075THYR (8 V per DigiKey; 1206L075/16WR for 16 V) | C99563 (15 863) | the footprint is 1206: the 1812 MF-MSMF075 does **not** fit; Bourns MF-NSMF075-2 (C89653, 1206, 6 V) also fits |
| J5 | pin header 1 × 4, 2.54 mm, vertical | 1 | generic | | SWD: 3V3, SWDIO, SWCLK, GND |
| J6 | pin header 1 × 3, 2.54 mm, vertical | 1 | generic | | UART: GND, TX, RX |
| JP1 | pin header 1 × 3, 2.54 mm, vertical | 1 | generic | | supply select (USB / EXT) |
| JP2 | pin header 1 × 3, 2.54 mm, vertical | 1 | generic | | BOOT0 |
| — | jumper shunts, 2.54 mm | 2 | generic | | JP1 (1-2: USB) and JP2 (2-3: run) |
| J4 | pin header 1 × 2, 2.54 mm, vertical | 1 | generic | | external 5 V, ≥ 1 A adapter (optional) |

The CH32V203C8T6 (U1) is assembled by JLCPCB from the personal stock (C3001172).

## Ordering at DigiKey

DigiKey part numbers and stock from DigiKey's listings on 2026-10-20 (search snapshots: check the live pages). The
WCH MCUs are not listed here (own stock; the CH32V203 is assembled from the JLCPCB personal stock).

| For | Manufacturer part | DigiKey | Note |
|---|---|---|---|
| backplane J10–J17 (8 per backplane) | Sullins PPTC082LFBN-RC, 2 × 8 female, vertical, 2.54 mm | S7076-ND | about 8.5 mm high, tin; gold: PPPC082LFBN-RC, S7111-ND |
| voice card J1 (1 per card) | Sullins PEC08DBAN, 2 × 8 male, right angle | S2112E-08-ND | insulator 6.1 mm; check its row heights against the 3.3 mm card-plane assumption (backplane.md 6.2: rows 1.27 / 3.81 mm above the card): a difference only shifts the cards' spacing |
| backplane J1 (USB-C) | GCT USB4105-GF-A (or -060 / -120) | [product page](https://www.digikey.com/en/products/detail/gct/USB4105-GF-A/11198441) | in stock (about 50 000 on digikey.de), about US$ 0.80 |
| backplane J2 (USB-A) | Molex 0676430910 | WM4993-ND | about US$ 1.70; DigiKey lists an 11-week factory lead time: check stock |
| backplane J3 (jack) | Same Sky (CUI) SJ1-3523N | CP1-3523N-ND | in stock (about 230 000), about US$ 1.12 |
| backplane U4 (host switch) | TI **TPS2051CDBVT** | 296-29759-1-ND | the same part on a small reel, about 3 100 in stock; the DBVR reel is out of stock. Fallback TPS2051BDBVR (296-21265-1-ND, same family and package, in stock); **not** the AP2151WG-7 DigiKey suggests (1 A limit, pinout not confirmed) |
| backplane F1 (PTC) | Littelfuse 1206L075THYR | [product page](https://www.digikey.com/en/products/detail/littelfuse-inc/1206L075THYR/2090973) | about 10 000 in stock, about US$ 0.56; 8 V max per DigiKey (fine on the 5 V rail); 16 V: 1206L075/16WR, F7138CT-ND |
| vertical headers (J4, J5, J6, JP1, JP2) | Sullins PRPC040SAAN-RC, 1 × 40 breakaway, vertical | S1011EC-40-ND | one strip covers a backplane |
| voice card J2, J3 | Sullins PRPC040SBAN-M71RC, 1 × 40 breakaway, right angle | S1111EC-40-ND | one strip covers 6 cards (2 × 1 × 3 each) |
| JP1, JP2 shunts (2 per backplane) | Sullins SPC02SYAN | S9001-ND | |

## Totals

| Item | Per backplane | Per voice card | First build: 1 backplane + n cards |
|---|---|---|---|
| CH32V006F8P7 | – | 1 | n |
| 2 × 8 right-angle header (male) | – | 1 | n |
| 1 × 3 right-angle header (male) | – | 2 | 2 n |
| 2 × 8 vertical socket (female) | 8 | – | 8 |
| USB-C, USB-A, 3.5 mm jack, TPS2051C, PTC 1206 | 1 each | – | 1 each |
| vertical pin headers: 1 × 4, 1 × 3 (× 3), 1 × 2; 2 jumper shunts | 1 set | – | 1 set |

Pin headers come as breakable strips: one 1 × 40 strip covers a backplane's vertical headers; right-angle strips
cover the cards' 1 × 3 headers.
