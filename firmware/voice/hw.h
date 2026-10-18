/* TouchSynth hardware drivers */
#ifndef HW_H
#define HW_H

#include <stdint.h>

enum { CV_AMP, CV_CUT, CV_RES, CV_VCA };

void hw_init(void);

/* control voltages: 12-bit codes (0...4095 = 0...5 V PWM average), dithered 10-bit PWM */
void hw_cv_set(int ch, uint16_t code);
uint16_t hw_cv_get(int ch);

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
   The DCO is held in reset meanwhile. The ladder filter reconstructs (sim/s8_dac). */
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
void hw_dac_start(uint16_t arr, uint16_t half, void (*fill)(uint8_t *dst, int n));   /* half <= DAC_HALF */
void hw_dac_stop(void);
int hw_dac_active(void);                               /* 0, or the running carrier's arr */
int hw_dac_rendering(void);                            /* 1 while a buffer half is being rendered (diagnostics) */
uint16_t hw_dac_count(void);                           /* DMA transfers left in the ring (diagnostics) */
void hw_dac_stats(dac_stats_t *s, int clear);          /* diagnostics */
#if defined(CH32V006)
#define HW_SCRATCH 4096                                /* bytes */
extern uint16_t hw_scratch[HW_SCRATCH / 2];            /* shared RAM: console capture buffer, or the DAC ring in
                                                          DAC mode (captures are refused while DAC mode is on) */
#endif

/* 74HC595 chain: 16 LEDs (bit i = LED above key i) and the VCA trim DAC */
void hw_leds_dac(uint16_t leds, uint8_t dac);

/* audio loopback: n ADC samples of PD5, one every period_us microseconds */
uint32_t hw_capture(uint16_t *buf, int n, int period_us);       /* returns the elapsed time of n periods in us */
uint32_t hw_capture_ch(int ch, uint16_t *buf, int n, int period_us);   /* any ADC channel (diagnostics) */

/* MIDI input: returns a received byte or -1 */
int hw_midi_read(void);

#endif
