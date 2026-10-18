/* Digital voices on the PWM DAC (CH32V006), mirror sim/behav/dsp.py. One carrier for both: TIM2 centre-aligned
 * over 2 x 128 ticks, 187.5 kHz, 7-bit duty (129 levels), second-order error feedback.
 *   modal  drum synthesis (resonator banks), 15.625 kHz samples interpolated over DSP_UPS carrier periods
 *   osc    up to three band-limited oscillators (saw / pulse, polyBLEP), one sample per carrier period */
#ifndef DSP_H
#define DSP_H

#include <stdint.h>

#define DSP_ARR 128                                    /* TIM2: 48 MHz / (2 x 128) = 187.5 kHz carrier */
#define DSP_FS 15625                                   /* modal: sample rate, carrier / DSP_UPS */
#define DSP_UPS 12                                     /* modal: carrier periods per sample */
#define DSP_OSC_FS 187500                              /* osc: sample rate = carrier */
#define DSP_DUAL_K 31309                               /* dual PWM: low codes per high step x 256 (k = 122.3) */
enum { DSP_MODAL, DSP_OSC };
enum { OSC_SAW, OSC_PULSE };

typedef struct { float ratio; int32_t gain, r; } dsp_mode_t;   /* mode frequency / note, level and pole radius (Q30) */
typedef struct { uint8_t wave; int16_t level, offset; } dsp_osc_t;   /* OSC_*, level Q15, pitch offset 1/256 semitone */
/* modal: first mode, n_modes, mallet = contact samples, voices, gain = output gain Q8;
   osc: first oscillator, n_modes = number of oscillators, mallet = pulse width 0...255 */
typedef struct { uint8_t first, n_modes, mallet, voices; uint16_t gain; uint8_t kind; } dsp_patch_t;

void dsp_select(int patch);                            /* 1... = DSP_PATCH_TABLE entry, 0 = none */
void dsp_strike(uint8_t note, uint8_t vel);            /* modal: vel 0...255 */
void dsp_pitch(int32_t pitch, int gate);               /* osc, 1 kHz: pitch in 1/256 semitone, gate 0 = silent */
void dsp_carrier(uint16_t *arr, uint16_t *half);       /* DAC carrier (TIM2 arr) and buffer half for the patch */
void dsp_fill(uint8_t *dst, int n);                    /* n carrier periods -> n ring entries (hw.h) */
int dsp_kind(void);                                    /* DSP_MODAL / DSP_OSC, -1 = none */

#endif
