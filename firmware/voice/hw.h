/* TouchSynth hardware drivers */
#ifndef HW_H
#define HW_H

#include <stdint.h>

enum { CV_AMP, CV_CUT, CV_RES, CV_VCA };

void hw_init(void);

/* control voltages: 12-bit codes (0...4095 = 0...5 V PWM average), dithered 10-bit PWM. With a delay of d > 0
   frames (card: the presentation delay D, bus.md 3.1) hw_cv_set only stages the code; hw_cv_commit, once per
   control tick, stores the staged codes in a delay line and loads those of d ticks ago into the PWM (the card's VCA
   trim, CV channel 0, is not delayed). d = 0 (board 1, default): hw_cv_set loads the PWM at once. */
#define CV_DELAY_MAX 12
void hw_cv_set(int ch, uint16_t code);
uint16_t hw_cv_get(int ch);                            /* the code the PWM outputs now */
void hw_cv_commit(void);
void hw_cv_delay(int d);

/* DCO: timer period psc * arr (48 MHz ticks), pulse width 0...255 (0 = pulse off) */
void hw_dco_set(uint16_t psc, uint16_t arr, uint8_t pw);
void hw_dco_waves(int sub_on, int noise_on);

/* PWM DAC on the pulse pin ("DAC mode", CH32V006 only): TIM2 centre-aligned with CMS = 10 (up 0...arr, down again:
   2 x arr ticks; arr = 128: 187.5 kHz, 7-bit duty), the pulses centred on the bottom of the count, so the signal
   does not modulate the pulse position. The CH3 compare at arr / 2 on the up-count requests DMA1 channel 1 once per
   carrier period; it writes the next period's code from a ring into the CH2 preload, which the update at the top
   loads (spec.md 3.2, format 4). Dual-PWM build (DAC_DUAL = 1, format 3): the same request starts a TIM2 DMA burst
   that writes [high, arr / 2, low] into CH2, CH3 (the request compare) and CH4 (low byte, PC1).
   The ring has two halves of DAC_HALF carrier periods; the DMA half / full transfer interrupt renders the half
   that has just played, at the lowest interrupt priority (touchsynth.c): fill(dst, n) writes n carrier periods.
   The DCO is held in reset meanwhile. The ladder filter reconstructs (sim/s8_dac).
   Time base: TIM2 and SysTick both count HCLK, so the ring entry the DMA loads at any moment follows from the SysTick
   time since the start; fill() gets the SysTick time t of the first period it writes (period k at t + k x 2 arr),
   which places the voice-state changes of the presentation delay on the right carrier period (dsp.c). */
#ifndef DAC_DUAL
#define DAC_DUAL 0                                     /* 1: dual PWM, 3 bytes per carrier period (make DAC_DUAL=1) */
#endif
#define DAC_BPP (DAC_DUAL ? 3 : 1)                     /* ring bytes per carrier period */
#define DAC_HALF 256                                   /* carrier periods per buffer half (1.37 ms, bus.md 3.1) */
#define DAC_RING (2 * DAC_BPP * DAC_HALF)              /* bytes: 512 (single) or 1536 (dual), in hw_scratch */
typedef struct {
	uint32_t renders;                                  /* buffer halves rendered */
	uint32_t fill_max;                                 /* longest render, CPU cycles (budget: half x 2 arr) */
	uint16_t overruns;                                 /* late renders and halves played without a render */
	uint16_t slack_min;                                /* fewest carrier periods left in the playing half */
	uint16_t half;                                     /* carrier periods per buffer half (0: DAC off) */
} dac_stats_t;
void hw_dac_start(uint16_t arr, uint16_t half, void (*fill)(uint8_t *dst, int n, uint32_t t));   /* half <= DAC_HALF */
void hw_dac_stop(void);
int hw_dac_active(void);                               /* 0, or the running carrier's arr */
int hw_dac_rendering(void);                            /* 1 while a buffer half is being rendered (diagnostics) */
uint16_t hw_dac_count(void);                           /* DMA transfers left in the ring (diagnostics) */
void hw_dac_stats(dac_stats_t *s, int clear);          /* diagnostics */
#if defined(CH32V006)
#define HW_SCRATCH (BOARD_CARD ? 3584 : 4096)          /* bytes (card: 512 bytes went to the bus buffers) */
extern uint16_t hw_scratch[HW_SCRATCH / 2];            /* shared RAM: console capture buffer, or the DAC ring in
                                                          DAC mode (captures are refused while DAC mode is on) */
#endif

/* board 1: 74HC595 chain, 16 LEDs (bit i = LED above key i) and the VCA trim DAC;
   card: the PLAY LED (any bit set) and the VCA trim PWM (CV channel 0) */
void hw_leds_dac(uint16_t leds, uint8_t dac);
void hw_led_stat(int on);                              /* card: STAT LED (board 1: nothing) */

/* card: SYNC edges (PD4) since reset, SysTick time of the first and the last (board 1: zeros) */
void hw_sync_get(uint32_t *n, uint32_t *first, uint32_t *last);
#if BOARD_CARD
void sync_tick(uint32_t t);                            /* touchsynth.c: called from the SYNC interrupt, t = SysTick time
                                                          at the edge (interrupt entry) */

/* card: voice bus UART (bus.md 2), USART1 at BUS_BAUD 8N1: RX on PD6 by DMA1 channel 5 into a 256-byte ring,
   TX (return line) on PD5 open drain by DMA1 channel 4 */
void hw_bus_enable(int on);                            /* receiver on (after the HSI trim) / off */
uint16_t hw_bus_mark(void);                            /* the RX ring position now */
int hw_bus_span(uint16_t mark, const uint8_t **p);     /* received bytes before mark, contiguous in the ring: count,
                                                          *p = the first; read in place, then hw_bus_done(count) */
void hw_bus_done(int n);
int hw_bus_rx_error(void);                             /* 1 if a framing / noise / overrun error is flagged (at most
                                                          one count per call) */
int hw_bus_tx_busy(void);                              /* the TX DMA still reads its buffer */
int hw_bus_send(const uint8_t *p, int n);              /* start a reply (p stays valid until sent); 0 if busy */
uint32_t hw_uid(int i);                                /* chip unique ID word 0 / 1 (ESIG, 64 bit) */
#endif
extern volatile uint32_t hw_busy_cycles;               /* cycles spent rendering (DAC), for the CPU load */

/* audio loopback: n ADC samples (board 1: PD5, card: PC4), one every period_us microseconds */
uint32_t hw_capture(uint16_t *buf, int n, int period_us);       /* returns the elapsed time of n periods in us */
uint32_t hw_capture_ch(int ch, uint16_t *buf, int n, int period_us);   /* any ADC channel (diagnostics) */

/* MIDI input (board 1; card: the bus, hw_bus_span): a received byte or -1; byte and error counts since reset */
int hw_midi_read(void);
void hw_rx_stats(uint16_t *bytes, uint16_t *errors);

#endif
