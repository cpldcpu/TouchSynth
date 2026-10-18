/* Digital voices on the PWM DAC (CH32V006, hardware multiply). Mirrors sim/behav/dsp.py.
 *
 * Modal drum synthesis: each stroke excites a bank of two-pole resonators, one per drum mode (frequency = note * ratio, level, decay),
 * with a raised-cosine mallet pulse. A stroke on a note that is still ringing adds to its bank (a restruck drum);
 * a new note takes a free or the oldest bank. Fixed point: signals Q24, coefficients Q30.
 * Output: 15.625 kHz samples through a cubic soft clipper, linearly interpolated over the DSP_UPS = 12 carrier
 * periods of a sample, each period's 7-bit duty code with second-order error feedback (stored twice, hw.h).
 *
 * Oscillators: up to three saw or pulse oscillators (pitch offsets, levels), one sample per period of the
 * 187.5 kHz carrier (no interpolation: its images would intermodulate in the ladder, sim/s9_osc), band-limited with
 * a 2-point polyBLEP at each wrap; pulse = difference of two saws.
 *
 * Both end in the same output stage: 7-bit duty code (129 levels) with second-order error feedback, NTF
 * (1 - z^-1)^2; the oversampling ratio 4.7 makes 7 bit as clean as an ideal DAC at this rate
 * (sim/s9_osc/s9_moog.py). */
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
static const dsp_osc_t osc_tab[] = DSP_OSC_TABLE;
static const dsp_patch_t patches[] = DSP_PATCH_TABLE;
static const dsp_patch_t *cur;
static voice_t voices[MAXV];
static uint16_t mallet[MAXMALLET];                  /* Q20, unit sum */
static uint32_t age;
static int32_t sd1, sd2;                            /* error feedback state, 1/256 code */
static int32_t c_prev = 16384;                      /* previous sample (1/256 code), for the interpolation */

/* second-order error feedback: target v (code 0...DSP_ARR in 1/256) -> duty code */
__attribute__((always_inline)) static inline uint8_t sdm2(int32_t v, int32_t *e1, int32_t *e2)
{
	int32_t w = v + 2 * *e1 - *e2;
	int32_t q = (w + 128) >> 8;
	if (q < 0) q = 0;
	if (q > DSP_ARR) q = DSP_ARR;
	*e2 = *e1;
	int32_t e = w - (q << 8);
	if (e > 1024) e = 1024;                         /* clipped: keep the loop stable */
	if (e < -1024) e = -1024;
	*e1 = e;
	return (uint8_t)q;
}

static inline int32_t mulh(int32_t a, int32_t b) { return (int32_t)(((int64_t)a * b) >> 32); }
static void osc_init(void);

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
	if (cur->kind == DSP_OSC) {
		osc_init();
		return;
	}
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
	if (!cur || cur->kind != DSP_MODAL)
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
__attribute__((noinline, section(".srodata"))) static void modal_fill(uint8_t *dst, int ns)
{
	int32_t e1 = sd1, e2 = sd2;
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
		int32_t c = 16384 + (acc >> 10);            /* (x + 1) / 2 * 128 in 1/256 code (Q24: 2^24 / 16384 = 2^10) */
		int32_t step = ((c - c_prev) * 5461) >> 16; /* linear interpolation over DSP_UPS = 12 periods */
		int32_t v = c_prev;
		for (int u = 0; u < DSP_UPS; u++) {
			v = (u == DSP_UPS - 1) ? c : v + step;
			uint8_t q = sdm2(v, &e1, &e2);
			*dst++ = q;                             /* twice: the update event comes at both ends of the */
			*dst++ = q;                             /* centre-aligned period, the pulse stays symmetric */
		}
		c_prev = c;
	}
	sd1 = e1;
	sd2 = e2;
}

/* ------------------------------------------------------------------ oscillators */
#define MAXO 3
typedef struct { uint32_t ph, inc, inv; int32_t lvl; uint8_t wave; } osc_t;
static osc_t osc[MAXO];
static uint8_t n_osc;
static volatile uint8_t osc_gate;
static uint32_t pw_off;                             /* pulse width as a phase offset */

static void osc_init(void)
{
	n_osc = cur->n_modes < MAXO ? cur->n_modes : MAXO;
	for (int i = 0; i < n_osc; i++) {
		const dsp_osc_t *t = &osc_tab[cur->first + i];
		osc[i].wave = t->wave;
		osc[i].lvl = t->level;
		osc[i].ph = (uint32_t)i * 0x55555555u;      /* spread start phases */
		osc[i].inc = 0;
		osc[i].inv = 0;
	}
	pw_off = (uint32_t)cur->mallet << 24;
	osc_gate = 0;
	sd1 = sd2 = 0;
}

/* phase step and its inverse for a pitch (1/256 semitone), from the top-octave tables (as the DCO's timer counts) */
static void osc_rate(int32_t p, osc_t *o)
{
	if (p < (12 << 8)) p = 12 << 8;
	if (p > (131 << 8)) p = 131 << 8;
	int32_t rel = p - (120 << 8);
	int oct = 0;
	while (rel < 0) { rel += 12 << 8; oct++; }
	int i = rel >> 4, f = rel & 15;
	uint32_t inc = osc_inc_top[i] + (((osc_inc_top[i + 1] - osc_inc_top[i]) * f) >> 4);
	uint32_t inv = osc_inv_top[i] - (((osc_inv_top[i] - osc_inv_top[i + 1]) * f) >> 4);
	o->inv = inv << oct;
	o->inc = inc >> oct;
}

void dsp_pitch(int32_t p, int gate)
{
	if (!cur || cur->kind != DSP_OSC)
		return;
	for (int i = 0; i < n_osc; i++)
		osc_rate(p + osc_tab[cur->first + i].offset, &osc[i]);
	osc_gate = gate;
}

static inline uint32_t mulhu(uint32_t a, uint32_t b) { return (uint32_t)(((uint64_t)a * b) >> 32); }

/* rising saw -1...1 (Q31) with a 2-point polyBLEP: the jump at the wrap becomes a band-limited step,
   +(1 - x)^2 one sample after it and -(1 - x)^2 one sample before (x = distance to the wrap in samples) */
__attribute__((always_inline)) static inline int32_t saw_blep(uint32_t ph, uint32_t inc, uint32_t inv)
{
	int32_t s = (int32_t)(ph ^ 0x80000000u);
	if (ph < inc) {
		uint32_t x = mulhu(ph, inv);
		uint32_t r = x < 65535 ? 65535 - x : 0;
		s += (int32_t)((r * r) >> 1);
	} else if (ph > ~inc) {
		uint32_t x = mulhu(-ph, inv);
		uint32_t r = x < 65535 ? 65535 - x : 0;
		s -= (int32_t)((r * r) >> 1);
	}
	return s;
}

/* blocks of OBLK samples: each oscillator runs over the block with its state in registers (RV32E has 16), adding
   into acc[], then the error feedback runs over the block */
#define OBLK 32
__attribute__((noinline, section(".srodata"))) static void osc_fill(uint8_t *dst, int n)
{
	int32_t acc[OBLK];
	int32_t e1 = sd1, e2 = sd2;
	int no = osc_gate ? n_osc : 0;
	while (n > 0) {
		int m = n < OBLK ? n : OBLK;
		for (int k = 0; k < m; k++)
			acc[k] = 0;
		for (int i = 0; i < no; i++) {
			osc_t *o = &osc[i];
			uint32_t ph = o->ph, inc = o->inc, inv = o->inv;
			int32_t lvl = o->lvl;
			if (o->wave == OSC_PULSE) {                 /* pulse = (saw(ph) - saw(ph + pw)) / 2 */
				uint32_t off = pw_off;
				lvl >>= 1;
				for (int k = 0; k < m; k++) {
					ph += inc;
					int32_t s = (saw_blep(ph, inc, inv) >> 16) - (saw_blep(ph + off, inc, inv) >> 16);
					acc[k] += s * lvl;                  /* Q15 * Q15 = Q30 */
				}
			} else {
				for (int k = 0; k < m; k++) {
					ph += inc;
					acc[k] += (saw_blep(ph, inc, inv) >> 16) * lvl;
				}
			}
			o->ph = ph;
		}
		for (int k = 0; k < m; k++) {
			uint8_t q = sdm2(16384 + (acc[k] >> 16), &e1, &e2);   /* Q30 -> code 0...128 in 1/256 */
			*dst++ = q;                             /* twice: both update events of the centre-aligned period */
			*dst++ = q;
		}
		n -= m;
	}
	sd1 = e1;
	sd2 = e2;
}

/* ------------------------------------------------------------------ dispatch */
int dsp_kind(void) { return cur ? cur->kind : -1; }

void dsp_carrier(uint16_t *arr, uint16_t *half)
{
	*arr = DSP_ARR;                                 /* 187.5 kHz, 7 bit */
	*half = (cur && cur->kind == DSP_OSC) ? 1024 : 80 * DSP_UPS;   /* 5.5 ms; modal: 80 samples, 5.1 ms */
}

void dsp_fill(uint8_t *dst, int n)
{
	if (cur && cur->kind == DSP_OSC)
		osc_fill(dst, n);
	else
		modal_fill(dst, n / DSP_UPS);
}

#endif
