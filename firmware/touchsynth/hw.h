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

/* PWM DAC on the pulse pin ("DAC mode", CH32V006 only): TIM2 centre-aligned (counting up and down over 2 x 256
   ticks: a 93.75 kHz carrier with 8-bit duty and pulses centred in the period, so the signal does not modulate
   the pulse position). The update event comes twice per period; DMA loads the CH2 duty from a ring buffer of
   8-bit codes on every update, so each period's code is stored twice. The DCO is held in reset. The main loop
   refills the half that has played (hw_dac_poll). The ladder filter reconstructs (sim/s8_dac). */
#define DAC_UPS  6                                     /* carrier periods per sample: 15.625 kHz */
#define DAC_EPS  (2 * DAC_UPS)                         /* ring entries per sample (two updates per period) */
#define DAC_HALF 128                                   /* samples per buffer half (8.2 ms) */
void hw_dac_start(void);
void hw_dac_stop(void);
int hw_dac_active(void);
void hw_dac_poll(void (*fill)(uint8_t *dst, int n));   /* fill(dst, n): n samples, DAC_EPS codes each */
uint16_t hw_dac_count(void);                           /* DMA transfers left in the ring (diagnostics) */
void hw_dac_stats(uint16_t *overruns, uint16_t *max_fill_us, uint16_t *max_gap_us);   /* diagnostics */
#if defined(CH32V006)
extern uint16_t hw_scratch[2048];                      /* shared RAM: console capture buffer, or the DAC ring in
                                                          DAC mode (captures are refused while DAC mode is on) */
#endif

/* 74HC595 chain: 16 LEDs (bit i = LED above key i) and the VCA trim DAC */
void hw_leds_dac(uint16_t leds, uint8_t dac);

/* touch pads through the two CD4051: raw[i] for pad i (0...15), higher = more capacitance */
void hw_touch_scan(uint32_t raw[16], int iterations);

/* audio loopback: n ADC samples of PD5, one every period_us microseconds */
uint32_t hw_capture(uint16_t *buf, int n, int period_us);       /* returns the elapsed time of n periods in us */
uint32_t hw_capture_ch(int ch, uint16_t *buf, int n, int period_us);   /* any ADC channel (diagnostics) */

/* MIDI input: returns a received byte or -1 */
int hw_midi_read(void);

/* 1 kHz control tick (called from the SysTick interrupt, defined in main.c) */
void control_tick(void);

#endif
