/* Digital voices on the PWM DAC (CH32V006): modal drum synthesis, mirrors sim/behav/dsp.py */
#ifndef DSP_H
#define DSP_H

#include <stdint.h>

#define DSP_FS 15625                                   /* sample rate: 187.5 kHz carrier / DAC_UPS (12) */

typedef struct { float ratio; int32_t gain, r; } dsp_mode_t;   /* mode frequency / note, level and pole radius (Q30) */
typedef struct { uint8_t first, n_modes, mallet, voices; uint16_t gain; } dsp_patch_t;   /* mallet: contact samples,
                                                                                     gain: output gain Q8 */

void dsp_select(int patch);                            /* 1... = DSP_PATCH_TABLE entry, 0 = none */
void dsp_strike(uint8_t note, uint8_t vel);            /* vel 0...255 */
void dsp_fill(uint8_t *dst, int n);                    /* n samples -> DAC_UPS duty codes each */

#endif
