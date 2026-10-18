/* TouchSynth user interface: touch keys, SHIFT / - / + editing, LEDs */
#ifndef UI_H
#define UI_H

#include <stdint.h>

#define N_PADS 16
enum { PAD_SHIFT = 13, PAD_MINUS = 14, PAD_PLUS = 15 };

extern uint32_t touch_raw[N_PADS], touch_base[N_PADS], touch_thr[N_PADS];
extern uint16_t touch_state;        /* bit i: pad i touched */
extern uint8_t trim_dac;            /* VCA offset trim (74HC595 #3) */
extern int8_t octave;               /* keyboard transpose -2 ... +2 octaves (C = C3 + 12 * octave) */
extern volatile uint16_t led_override;   /* console: LEDs forced (0 = normal display) */
extern volatile uint8_t led_forced;
extern volatile uint8_t keys_enabled;   /* 0: touch pads are scanned but play nothing (unattended recordings) */

void ui_init(void);                 /* measures the untouched baselines: keep hands off at power-up */
void ui_poll(void);                 /* scan, handle keys, refresh LEDs; call from the main loop */
void ui_tick(void);                 /* 1 kHz: display timers */
void ui_param_set(int k, int v);    /* UI parameter k (0...11) to value 0...15 */

#endif
