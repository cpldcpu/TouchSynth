/* Modal drum synthesis for the PWM DAC (CH32V006, hardware multiply). Mirrors sim/behav/dsp.py:
 * each stroke excites a bank of two-pole resonators, one per drum mode (frequency = note * ratio, level, decay),
 * with a raised-cosine mallet pulse. A stroke on a note that is still ringing adds to its bank (a restruck drum);
 * a new note takes a free or the oldest bank. Fixed point: signals Q24, coefficients Q30.
 * Output: 15.625 kHz samples through a cubic soft clipper, linearly interpolated over the DAC_UPS carrier periods of
 * a sample, each period's 8-bit duty code with first-order error feedback (stored twice, see hw.h). */
#include "board.h"
#include "dsp.h"
#include "hw.h"
#include "synth.h"
#include "tables.h"

#if defined(CH32V006)

#define MAXV 2
#define MAXM 18
#define MAXMALLET 128                                 /* 4 ms of mallet contact */

typedef struct {
	int32_t a1[MAXM], a2[MAXM], b[MAXM], y1[MAXM], y2[MAXM];
	int32_t vel;                                    /* Q24 */
	uint16_t k;                                     /* mallet sample index */
	uint8_t note, n, on;
	uint32_t age;
} voice_t;

static const dsp_mode_t modes[] = DSP_MODE_TABLE;
static const dsp_patch_t patches[] = DSP_PATCH_TABLE;
static const dsp_patch_t *cur;
static voice_t voices[MAXV];
static uint16_t mallet[MAXMALLET];                  /* Q20, unit sum */
static uint32_t age;
static int32_t err;                                 /* error feedback, 1/256 code */
static int32_t c8_prev = 32640;                     /* previous sample, for the interpolation */

static inline int32_t mulh(int32_t a, int32_t b) { return (int32_t)(((int64_t)a * b) >> 32); }

static float cos_poly(float w)                      /* |w| <= 1.2 rad: error < 1e-7 */
{
	float w2 = w * w;
	return 1.0f - w2 * (0.5f - w2 * (1.0f / 24 - w2 * (1.0f / 720 - w2 * (1.0f / 40320))));
}

static float sin_poly(float w)
{
	float w2 = w * w;
	return w * (1.0f - w2 * (1.0f / 6 - w2 * (1.0f / 120 - w2 * (1.0f / 5040 - w2 * (1.0f / 362880)))));
}

void dsp_select(int p)
{
	for (int i = 0; i < MAXV; i++)
		voices[i].on = 0;
	cur = (p > 0 && p <= (int)(sizeof patches / sizeof patches[0])) ? &patches[p - 1] : 0;
	if (!cur)
		return;
	int L = cur->mallet < MAXMALLET ? cur->mallet : MAXMALLET;
	float sum = 0;
	for (int pass = 0; pass < 2; pass++)            /* raised cosine 0.5 - 0.5 cos(x) = sin^2(x / 2), unit sum */
		for (int k = 0; k < L; k++) {
			float h = 3.1415927f * (k + 0.5f) / L;  /* x / 2 in (0, pi) */
			float sn = sin_poly(h < 1.5707963f ? h : 3.1415927f - h);
			if (pass == 0)
				sum += sn * sn;
			else
				mallet[k] = (uint16_t)(sn * sn / sum * 1048576.0f);
		}
}

void dsp_strike(uint8_t note, uint8_t vel)
{
	if (!cur)
		return;
	voice_t *v = 0;
	for (int i = 0; i < MAXV && i < cur->voices; i++)
		if (voices[i].on && voices[i].note == note)
			v = &voices[i];
	if (v) {                                        /* restrike: more energy into the ringing bank */
		v->k = 0;
		v->vel = (int32_t)vel << 16;
		return;
	}
	for (int i = 0; i < MAXV && i < cur->voices; i++)         /* a free bank, else the oldest */
		if (!v || (v->on && (!voices[i].on || voices[i].age < v->age)))
			v = &voices[i];
	float f = 8.1757989f;                           /* MIDI 0 */
	for (int i = 0; i < note / 12; i++)
		f *= 2;
	static const float semi[12] = { 1.0f, 1.0594631f, 1.1224620f, 1.1892071f, 1.2599210f, 1.3348399f, 1.4142136f,
	                                1.4983071f, 1.5874011f, 1.6817929f, 1.7817974f, 1.8877486f };
	f *= semi[note % 12];
	int n = 0;
	for (int m = 0; m < cur->n_modes && m < MAXM; m++) {
		const dsp_mode_t *md = &modes[cur->first + m];
		float w = 6.2831853f * f * md->ratio / DSP_FS;
		if (w > 1.2f)                               /* above ~6 kHz: not needed for drums */
			continue;
		float r = md->r / 1073741824.0f;
		v->a1[n] = (int32_t)(2 * r * cos_poly(w) * 1073741824.0f);
		v->a2[n] = mulh(md->r, md->r) << 2;
		v->b[n] = (int32_t)(md->gain * sin_poly(w));   /* level Q30 * sin(w): impulse amplitude = level */
		v->y1[n] = v->y2[n] = 0;
		n++;
	}
	v->n = n;
	v->note = note;
	v->vel = (int32_t)vel << 16;
	v->k = 0;
	v->age = ++age;
	v->on = 1;
}

/* hot loop: own function (registers) and run from RAM (no flash wait states), like the TIM1 interrupt */
__attribute__((noinline, section(".srodata"))) void dsp_fill(uint8_t *dst, int ns)
{
	for (int s = 0; s < ns; s++) {
		int32_t acc = 0;
		if (cur) {
			for (int i = 0; i < MAXV; i++) {
				voice_t *v = &voices[i];
				if (!v->on)
					continue;
				if (v->k < cur->mallet && v->k < MAXMALLET) {          /* mallet contact: excite */
					int32_t x = mulh(v->vel, (int32_t)mallet[v->k++] << 4) << 8;   /* vel Q24 * pulse Q24 */
					for (int m = 0; m < v->n; m++) {
						int32_t y = (mulh(v->a1[m], v->y1[m]) - mulh(v->a2[m], v->y2[m]) + mulh(v->b[m], x)) << 2;
						v->y2[m] = v->y1[m];
						v->y1[m] = y;
						acc += y;
					}
				} else {                                                   /* free ringing: 2 multiplies */
					int32_t *a1 = v->a1, *a2 = v->a2, *y1 = v->y1, *y2 = v->y2;
					for (int m = 0; m < v->n; m++) {
						int32_t y = (mulh(a1[m], y1[m]) - mulh(a2[m], y2[m])) << 2;
						y2[m] = y1[m];
						y1[m] = y;
						acc += y;
					}
				}
			}
			acc = (acc >> 8) * cur->gain;           /* Q24 */
		}
		if (acc > 16777215) acc = 16777215;         /* cubic soft clipper: 1.5 x - 0.5 x^3, |x| <= 1 */
		if (acc < -16777215) acc = -16777215;
		int32_t x2 = mulh(acc << 4, acc << 4);      /* Q24 */
		int32_t x3 = mulh(x2 << 4, acc << 4);
		acc = acc + (acc >> 1) - (x3 >> 1);
		int32_t c8 = 32640 + (acc >> 9);            /* (x + 1) / 2 * 255 in 1/256 code (2^24 / 32640 ~ 2^9) */
		int32_t step = ((c8 - c8_prev) * 10923) >> 16;   /* linear interpolation over DAC_UPS = 6 periods */
		int32_t v = c8_prev;
		for (int u = 0; u < DAC_UPS; u++) {
			v = (u == DAC_UPS - 1) ? c8 : v + step;
			int32_t q = (v + err + 128) >> 8;      /* first-order error feedback (noise shaping) */
			if (q < 0) q = 0;
			if (q > 255) q = 255;
			err += v - (q << 8);
			*dst++ = (uint8_t)q;                    /* twice: the update event comes at both ends of the */
			*dst++ = (uint8_t)q;                    /* centre-aligned period, the pulse stays symmetric */
		}
		c8_prev = c8;
	}
}

#endif
