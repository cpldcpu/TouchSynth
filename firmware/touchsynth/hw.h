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
