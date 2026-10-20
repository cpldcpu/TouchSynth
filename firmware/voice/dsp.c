/* Digital voices on the PWM DAC (CH32V006, hardware multiply). Mirrors sim/behav/dsp.py.
 *
 * Modal drum synthesis: each stroke excites a bank of two-pole resonators, one per drum mode (frequency = note * ratio, level, decay),
 * with a raised-cosine mallet pulse. A stroke on a note that is still ringing adds to its bank (a restruck drum);
 * a new note takes a free or the oldest bank. Fixed point: signals Q24, coefficients Q30.
 * Output: 15.625 kHz samples through a cubic soft clipper, linearly interpolated over the DSP_UPS = 12 carrier
 * periods of a sample, one duty code per period (hw.h).
 *
 * Oscillators: up to three saw or pulse oscillators (pitch offsets, levels), one sample per period of the
 * 187.5 kHz carrier (no interpolation: its images would intermodulate in the ladder, sim/s9_osc), band-limited with
 * a 2-point polyBLEP at each wrap; pulse = difference of two saws.
 *
 * Both end in the same output stage: 7-bit duty code (129 levels) with second-order error feedback, NTF
 * (1 - z^-1)^2; the oversampling ratio 4.7 makes 7 bit as clean as an ideal DAC at this rate
 * (sim/s9_osc/s9_moog.py). Dual-PWM build (DAC_DUAL): 7 + 7 bit, high = v >> 8, low = round((v & 255) k / 256)
 * with k = DSP_DUAL_K / 256 low codes per high step (spec.md 3.5), no error feedback. */
#include "board.h"
#include "dsp.h"
#include "hw.h"
#include "synth.h"
#include "tables.h"

#if defined(CH32V006)

#define MAXV 2
#define MAXM 18
#define MAXMALLET 128                                 /* 4 ms of mallet contact */

typedef struct { int32_t a1, a2, b, y[2]; } res_t;  /* [2026-10-20] one resonator, Q30, its last two outputs
                                                       (y[par] the newest: the new one overwrites the older) */
typedef struct {
	res_t md[MAXM];
	int32_t vel, pvel;                              /* Q24; pvel: of a staged strike */
	uint16_t k;                                     /* mallet sample index */
	uint8_t note, n, on;
	uint8_t pnew;                                   /* staged strike of a new note: the bank starts from rest */
	uint8_t par;
	uint32_t age;
} voice_t;

static const dsp_mode_t modes[] = DSP_MODE_TABLE;
static const dsp_osc_t osc_tab[] = DSP_OSC_TABLE;
static const dsp_patch_t patches[] = DSP_PATCH_TABLE;
static const dsp_patch_t *cur;                      /* 0 while a patch is being set up: the renderer is silent */
static voice_t voices[MAXV];
/* the mallet pulse, Q16, unit sum (Q20 overflowed 16 bit below 32 samples). [2026-10-20] In hw_scratch after the DAC
   ring, where the oscillators keep their block buffer (osc_fill): a patch is either kind, and dsp_select sets the
   table up while the renderer is silent */
#define mallet_tab ((uint16_t *)((uint8_t *)hw_scratch + DAC_RING))
_Static_assert(DAC_RING + 2 * MAXMALLET <= HW_SCRATCH_DSP, "the mallet table lies after the DAC ring");
static uint32_t age;
static int32_t sd1 = 128, sd2 = 128;                /* error feedback state, 1/256 code, + 128 (sdm2) */
static int32_t c_prev = 16384;                      /* previous sample (1/256 code), for the interpolation */

/* second-order error feedback: target v (code 0...DSP_ARR in 1/256) -> duty code. [2026-10-20] The state is the
   error plus half a code (f = e + 128): w = v + 2 f1 - f2 is then the rounding sum, q = w >> 8, and unless q clips
   the new error is w's low byte, so one compare does for the four clamps (the same codes as before). sdm_step
   leaves the new error in the older state's place (an unrolled loop alternates them), sdm2 keeps f1 the newest. */
__attribute__((always_inline)) static inline uint8_t sdm_step(int32_t v, int32_t *fa, int32_t *fb)
{
	int32_t w = v + 2 * *fa - *fb;
	int32_t q = w >> 8, f = w & 255;
	if (__builtin_expect((uint32_t)q > DSP_ARR, 0)) {
		q = q < 0 ? 0 : DSP_ARR;
		f = w - (q << 8);
		if (f > 1024 + 128) f = 1024 + 128;         /* clipped: keep the loop stable (|e| <= 1024) */
		if (f < -1024 + 128) f = -1024 + 128;
	}
	*fb = f;
	return (uint8_t)q;
}

__attribute__((always_inline)) static inline uint8_t sdm2(int32_t v, int32_t *f1, int32_t *f2)
{
	uint8_t q = sdm_step(v, f1, f2);
	int32_t t = *f1;
	*f1 = *f2;
	*f2 = t;
	return q;
}

/* one carrier period into the ring (hw.h): v = target code 0...DSP_ARR in 1/256 */
__attribute__((always_inline)) static inline uint8_t *dac_out(uint8_t *dst, int32_t v, int32_t *e1, int32_t *e2)
{
#if DAC_DUAL
	(void)e1; (void)e2;
	uint32_t h, l;
	if (v <= 0) h = l = 0;
	else if (v >= DSP_ARR << 8) { h = DSP_ARR; l = 0; }
	else { h = (uint32_t)v >> 8; l = (((uint32_t)v & 255) * DSP_DUAL_K + 32768) >> 16; }
	dst[0] = h;
	dst[1] = DSP_ARR / 2;                           /* CH3: the DMA request compare */
	dst[2] = l;
	return dst + 3;
#else
	*dst = sdm2(v, e1, e2);
	return dst + 1;
#endif
}

static inline int32_t mulh(int32_t a, int32_t b) { return (int32_t)(((int64_t)a * b) >> 32); }
static inline uint32_t mulhu(uint32_t a, uint32_t b) { return (uint32_t)(((uint64_t)a * b) >> 32); }
static void osc_init(const dsp_patch_t *p);
static void mallet_init(const dsp_patch_t *p);

/* ------------------------------------------------------------------ voice state queue (dsp.h) */
#define DSP_CYC (2 * DSP_ARR)                       /* HCLK cycles per carrier period */
#define VQ 16                                       /* queued states: D + 2 at most (one per tick) */
enum { VS_GATE = 1, VS_PHASE = 2, VS_STRIKE0 = 4 }; /* strike of bank i: VS_STRIKE0 << i */
typedef struct { uint32_t t; uint16_t pitch; uint8_t flags; } vstate_t;
static vstate_t vq[VQ];
static volatile uint8_t vq_w, vq_r;                 /* written by the tick / by the renderer */
static uint16_t st_pitch;                           /* staged by this tick */
static uint8_t st_flags;
static uint16_t late_n;
static uint32_t clk_scale = 1u << 16;               /* pitch lock, Q16 */
static uint16_t q_pitch;                            /* the last queued state: an unchanged one is not queued again */
static uint8_t q_flags = 0xFF;                      /* (saves the renderer three osc_rate per tick); 0xFF: none */
static void vs_apply(const vstate_t *v);

/* Fixed point for the strike and the mallet table: they run in the control tick (soft float took ~60 k cycles for
   the kettle's 17 modes, longer than a DAC buffer half), and the divisions are reciprocals (-Os would call the
   software divide). sin y and cos y for 0 <= y < 0.79 (w / 2 for the strike, w <= 1.2; half a mallet step) in Q31,
   Taylor to y^7 and y^6 (errors below 1e-6, below 3e-8 for y < 0.61), mulh only: the V006's multiplier takes
   several cycles, and a 64-bit product needs two of them */
#define Q31_ONE 0x7FFFFFFF
static void sincos_half_q31(int32_t y, int32_t *s, int32_t *c)
{
	int32_t y2 = mulh(y, y) << 1;
	int32_t t = Q31_ONE - (mulh(y2, 51130563) << 1);                   /* 1 - y^2 / 42 */
	t = Q31_ONE - (mulh(mulh(y2, t) << 1, 107374182) << 1);            /* 1 - y^2 / 20 t */
	t = Q31_ONE - (mulh(mulh(y2, t) << 1, 357913941) << 1);            /* 1 - y^2 / 6 t */
	*s = mulh(y, t) << 1;
	int32_t u = Q31_ONE - (mulh(y2, 71582788) << 1);                   /* 1 - y^2 / 30 */
	u = Q31_ONE - (mulh(mulh(y2, u) << 1, 178956971) << 1);            /* 1 - y^2 / 12 u */
	*c = Q31_ONE - mulh(y2, u);                                        /* 1 - y^2 / 2 u */
}

static uint32_t ratio_q24(float r)                  /* a mode table ratio (float constant, < 128) in Q24, from its
                                                       bits: no float arithmetic */
{
	union { float f; uint32_t u; } c = { .f = r };
	int e = (int)((c.u >> 23) & 255) - 127;
	uint32_t m = (c.u & 0x7FFFFF) | 0x800000;       /* r = m 2^(e - 23) */
	return e > 6 ? 0xFFFFFFFF : e >= -1 ? m << (e + 1) : e > -25 ? m >> (-1 - e) : 0;
}

/* note frequencies of MIDI octave 0 (8.1758 Hz x 2^(k / 12)), Q16 */
static const uint32_t note_f0[12] = { 535809, 567670, 601425, 637188, 675077, 715219, 757749, 802807, 850544, 901120,
                                      954703, 1011473 };

/* called from the main loop while the renderer (DMA interrupt) may run: cur stays 0 until the patch is set up */
void dsp_select(int p)
{
	const dsp_patch_t *np = (p > 0 && p <= (int)(sizeof patches / sizeof patches[0])) ? &patches[p - 1] : 0;
	cur = 0;
	__asm volatile("" ::: "memory");
	vq_r = vq_w;                                    /* states of the old patch are void */
	st_flags &= VS_GATE;
	q_flags = 0xFF;
	for (int i = 0; i < MAXV; i++)
		voices[i].on = voices[i].pnew = 0;
	if (!np)
		return;
	if (np->kind == DSP_OSC)
		osc_init(np);
	else
		mallet_init(np);
	__asm volatile("" ::: "memory");
	cur = np;
}

/* raised cosine 0.5 - 0.5 cos(x) = sin^2(x / 2) over L samples, unit sum (Q16): sin((k + 1/2) pi / L) by the
   recurrence s(k + 1) = 2 cos(pi / L) s(k) - s(k - 1) in Q29 (2 cos s < 2 fits), started from sin(pi / 2L) */
static void mallet_init(const dsp_patch_t *p)
{
	int L = p->mallet < MAXMALLET ? p->mallet : MAXMALLET;
	if (L < 2) {                                    /* one sample takes the whole unit */
		mallet_tab[0] = 0xFFFF;
		return;
	}
	int32_t s0, c0;
	sincos_half_q31((int32_t)(3373259426u / (uint32_t)L), &s0, &c0);   /* pi / 2L: (pi / 2) 2^31 / L */
	int32_t cstep = Q31_ONE - (mulh(s0, s0) << 2);  /* cos(pi / L) = 1 - 2 sin^2(pi / 2L) */
	uint32_t sum = 0;
	for (int pass = 0; pass < 2; pass++) {
		int32_t prev = -(s0 >> 2), cur = s0 >> 2;
		for (int k = 0; k < L; k++) {
			uint32_t sq = (uint32_t)mulh(cur, cur) >> 4;   /* sin^2, Q22 */
			if (pass == 0)
				sum += sq;
			else
				mallet_tab[k] = (sq << 6) / (sum >> 10);   /* sq / sum in Q16 */
			int32_t next = (mulh(cstep, cur) << 2) - prev;
			prev = cur;
			cur = next;
		}
	}
}

void dsp_strike(uint8_t note, uint8_t vel)
{
	if (!cur || cur->kind != DSP_MODAL)
		return;
	voice_t *v = 0;
	for (int i = 0; i < MAXV && i < cur->voices; i++)
		if ((voices[i].on || voices[i].pnew) && voices[i].note == note)
			v = &voices[i];
	if (v) {                                        /* restrike: more energy into the ringing bank */
		v->pvel = (int32_t)vel << 16;
		st_flags |= VS_STRIKE0 << (v - voices);
		return;
	}
	for (int i = 0; i < MAXV && i < cur->voices; i++) {       /* a free bank, else the oldest */
		int busy = voices[i].on || voices[i].pnew;
		if (!v || ((v->on || v->pnew) && (!busy || voices[i].age < v->age)))
			v = &voices[i];
	}
	v->on = 0;                                      /* a stolen bank stops now; the renderer may still be inside its
	                                                   sample (it runs below the tick): the strike clears y1 / y2 */
	uint32_t f = note_f0[note % 12] << (note / 12); /* Hz, Q16 */
	int n = 0;
	for (int m = 0; m < cur->n_modes && m < MAXM; m++) {
		const dsp_mode_t *md = &modes[cur->first + m];
		uint64_t fr = (uint64_t)f * ratio_q24(md->ratio);      /* mode frequency, Hz Q40 */
		if ((fr >> 40) > 2984)                      /* w > 1.2 (above ~3 kHz): not needed for drums */
			continue;
		int32_t w = (int32_t)(((fr >> 24) * 1768559438ull) >> 30);   /* 2 pi fr / DSP_FS, Q28 */
		int32_t s, c;
		sincos_half_q31(w << 2, &s, &c);            /* of w / 2, Q31 */
		int32_t cosw = Q31_ONE - (mulh(s, s) << 2); /* 1 - 2 sin^2(w / 2) */
		int32_t sinw = mulh(s, c) << 2;             /* 2 sin(w / 2) cos(w / 2) */
		v->md[n].a1 = mulh(md->r, cosw) << 2;       /* 2 r cos w, Q30 (r < 1: no overflow) */
		v->md[n].a2 = mulh(md->r, md->r) << 2;
		v->md[n].b = mulh(md->gain, sinw) << 1;     /* level Q30 * sin(w): impulse amplitude = level */
		v->md[n].y[0] = v->md[n].y[1] = 0;
		n++;
	}
	v->n = n;
	v->note = note;
	v->pvel = (int32_t)vel << 16;
	v->age = ++age;
	v->pnew = 1;
	st_flags |= VS_STRIKE0 << (v - voices);        /* sounds from its V_n on (vs_apply) */
}

/* free ringing of a bank: y = (a1 y[p] - a2 y[p ^ 1]) << 2 into y[p ^ 1], two resonators per loop (in assembly: the
   compiler reloads the end pointer from the stack every resonator; the C loop is the host's) */
#define RING_ASM(Y1, Y2, Y1B, Y2B) \
	__asm volatile( \
		"1:	lw %[t], 0(%[r])\n	lw %[u], " Y1 "(%[r])\n	mulh %[t], %[t], %[u]\n" \
		"	lw %[u], 4(%[r])\n	lw %[w], " Y2 "(%[r])\n	mulh %[u], %[u], %[w]\n" \
		"	sub %[t], %[t], %[u]\n	slli %[t], %[t], 2\n	sw %[t], " Y2 "(%[r])\n	add %[acc], %[acc], %[t]\n" \
		"	lw %[t], 20(%[r])\n	lw %[u], " Y1B "(%[r])\n	mulh %[t], %[t], %[u]\n" \
		"	lw %[u], 24(%[r])\n	lw %[w], " Y2B "(%[r])\n	mulh %[u], %[u], %[w]\n" \
		"	sub %[t], %[t], %[u]\n	slli %[t], %[t], 2\n	sw %[t], " Y2B "(%[r])\n	add %[acc], %[acc], %[t]\n" \
		"	addi %[r], %[r], 40\n	bltu %[r], %[e], 1b\n" \
		: [r] "+r"(r), [acc] "+r"(acc), [t] "=&r"(t), [u] "=&r"(u), [w] "=&r"(w) \
		: [e] "r"(re) \
		: "memory")

__attribute__((always_inline)) static inline int32_t ring(res_t *r, res_t *re, int p, int32_t acc)
{
	_Static_assert(sizeof(res_t) == 20 && __builtin_offsetof(res_t, y) == 12, "RING_ASM offsets");
	if ((re - r) & 1) {
		int32_t y = (mulh(r->a1, r->y[p]) - mulh(r->a2, r->y[p ^ 1])) << 2;
		r->y[p ^ 1] = y;
		acc += y;
		r++;
	}
	if (r >= re)
		return acc;
#if defined(__riscv)
	int32_t t, u, w;
	if (p)
		RING_ASM("16", "12", "36", "32");
	else
		RING_ASM("12", "16", "32", "36");
#else
	for (; r < re; r++) {
		int32_t y = (mulh(r->a1, r->y[p]) - mulh(r->a2, r->y[p ^ 1])) << 2;
		r->y[p ^ 1] = y;
		acc += y;
	}
#endif
	return acc;
}

/* hot loop: own function (registers) and run from RAM (no flash wait states). [2026-10-20] The resonators of a bank
   interleaved (one pointer, the coefficients and both outputs at fixed offsets) and their two outputs alternating
   (one store per resonator and sample instead of two; the V006: lw 2 cycles, sw 3); the interpolation unrolled by
   two (sdm_step). The same codes as before (test/render_test.py) */
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
				res_t *r = v->md, *re = r + v->n;
				int p = v->par;
				v->par = p ^ 1;
				if (v->k < cur->mallet && v->k < MAXMALLET) {          /* mallet contact: excite */
					int32_t x = mulh(v->vel, (int32_t)mallet_tab[v->k++] << 8) << 8;   /* vel Q24 * pulse Q24 */
					for (; r < re; r++) {
						int32_t y = (mulh(r->a1, r->y[p]) - mulh(r->a2, r->y[p ^ 1]) + mulh(r->b, x)) << 2;
						r->y[p ^ 1] = y;
						acc += y;
					}
				} else {                                                   /* free ringing: 2 multiplies */
					acc = ring(r, re, p, acc);
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
#if DAC_DUAL
		for (int u = 0; u < DSP_UPS; u++) {
			v = (u == DSP_UPS - 1) ? c : v + step;
			dst = dac_out(dst, v, &e1, &e2);
		}
#else
		_Static_assert(DSP_UPS % 2 == 0, "pairs of periods");
		for (int u = 0; u < DSP_UPS - 2; u += 2, dst += 2) {
			v += step;
			dst[0] = sdm_step(v, &e1, &e2);         /* (the newest error: e2) */
			v += step;
			dst[1] = sdm_step(v, &e2, &e1);
		}
		dst[0] = sdm_step(v + step, &e1, &e2);
		dst[1] = sdm_step(c, &e2, &e1);             /* the last period: the sample itself */
		dst += 2;
#endif
		c_prev = c;
	}
	sd1 = e1;
	sd2 = e2;
}

/* ------------------------------------------------------------------ oscillators */
#define MAXO 3
typedef struct { uint32_t ph, inc, inv, sinv; int32_t lvl; uint8_t wave; } osc_t;   /* sinv: scheduling inverse */
static osc_t osc[MAXO];
static uint8_t n_osc;
static volatile uint8_t osc_gate;
static uint32_t pw_off;                             /* pulse width as a phase offset */
static uint32_t osc_bias;                           /* 16384 << 16 - 32768 x the saws' levels (osc_block) */
static uint8_t n_saw;                               /* saws: the fused runs take two, a third adds (osc_block) */
static osc_t *saw_o[MAXO];

static void osc_init(const dsp_patch_t *p)
{
	n_osc = p->n_modes < MAXO ? p->n_modes : MAXO;
	for (int i = 0; i < n_osc; i++) {
		const dsp_osc_t *t = &osc_tab[p->first + i];
		osc[i].wave = t->wave;
		osc[i].lvl = t->level;
		osc[i].ph = (uint32_t)i * 0x55555555u;      /* spread start phases */
		osc[i].inc = 0;
		osc[i].inv = osc[i].sinv = 0;
	}
	osc_bias = 16384u << 16;
	n_saw = 0;
	for (int i = 0; i < n_osc; i++)
		if (osc[i].wave != OSC_PULSE) {
			osc_bias -= 32768u * (uint32_t)osc[i].lvl;
			saw_o[n_saw++] = &osc[i];
		}
	pw_off = (uint32_t)p->mallet << 24;
	osc_gate = 0;
	sd1 = sd2 = 128;
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
	o->inc = (uint32_t)(((uint64_t)(inc >> oct) * clk_scale) >> 16);   /* pitch lock to the controller's crystal */
	inv = (uint32_t)(((uint64_t)o->inv * (131072 - clk_scale)) >> 16);   /* / clk_scale: x (2 - s) < 1 / s */
	o->sinv = inv - (inv >> 10);                    /* below 2^48 / inc (the tables' error is about 1e-5): osc_run */
}

void dsp_pitch(int32_t p, int gate)                 /* staged: applied with the state (vs_apply) */
{
	st_pitch = p < 0 ? 0 : p > 0xFFFF ? 0xFFFF : p;
	st_flags = gate ? st_flags | VS_GATE : st_flags & ~VS_GATE;
}

void dsp_phase_reset(void) { st_flags |= VS_PHASE; }

void dsp_clock(uint32_t q8)
{
	int32_t dq = (int32_t)q8 - (FRAME_CYCLES << 8); /* scale = 1 / (1 + dq / N) ~ 1 - dq / q8 (|dq / N| < 1/32) */
	if (dq > -(FRAME_CYCLES << 3) && dq < (FRAME_CYCLES << 3)) {
		clk_scale = 65536 - (dq << 8) / (int32_t)(q8 >> 8);
		q_flags = 0xFF;                             /* the next state applies the new scale */
	}
}

uint16_t dsp_late(void) { return late_n; }

/* the state V_n takes effect: oscillator rates and gate, staged strikes (renderer, or the tick when immediate) */
static void vs_apply(const vstate_t *v)
{
	if (!cur)
		return;
	if (cur->kind == DSP_OSC) {
		for (int i = 0; i < n_osc; i++) {
			osc_rate((int32_t)v->pitch + osc_tab[cur->first + i].offset, &osc[i]);
			if (v->flags & VS_PHASE)
				osc[i].ph = (uint32_t)i * 0x55555555u;
		}
		osc_gate = v->flags & VS_GATE;
		return;
	}
	for (int i = 0; i < MAXV; i++) {
		if (!(v->flags & (VS_STRIKE0 << i)))
			continue;
		voice_t *b = &voices[i];
		if (b->pnew) {
			for (int m = 0; m < MAXM; m++)
				b->md[m].y[0] = b->md[m].y[1] = 0;
			b->pnew = 0;
		}
		b->k = 0;
		b->vel = b->pvel;
		b->on = 1;
	}
}

void dsp_commit(uint32_t t)                         /* control tick */
{
	vstate_t v = { t, st_pitch, st_flags };
	st_flags &= VS_GATE;                            /* strikes and the phase reset are one-shot */
	if (!t || !hw_dac_active() || !cur) {           /* nothing renders a queue: now */
		vq_r = vq_w;
		vs_apply(&v);
		q_flags = 0xFF;
		return;
	}
	if (v.pitch == q_pitch && v.flags == q_flags && !(v.flags & ~VS_GATE))   /* unchanged: nothing to switch */
		return;
	q_pitch = v.pitch;
	q_flags = v.flags;
	uint8_t w = vq_w, nw = (w + 1) % VQ;
	if (nw == vq_r) {                               /* full (D too large for VQ): dropped */
		late_n++;
		return;
	}
	vq[w] = v;
	vq_w = nw;
}

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

/* [2026-10-20] Blocks of OBLK samples: the oscillators add up into acc[] (in hw_scratch after the DAC ring, not on
   the stack), then the error feedback runs over the block. The oscillators run together between their polyBLEP
   regions (the samples within one step of a wrap, phase in [-inc, inc)), whose distance blep_run bounds from below
   with the scheduling inverse sinv: there a saw is (ph >> 16) - 32768 and a pulse a constant (pw_off has no low 16
   bits, so the two saws' difference only changes at a wrap), so a run is one loop over at most two saws and a
   constant, with one store per sample (the V006: lw 2 cycles, sw 3, a taken branch 3, mul 1). The saws' -32768 lvl
   and the output's offset of 16384 codes (<< 16) are in the constant; the sum stays below 2^30 in magnitude as the
   levels of a patch add up to at most 1 (gen_tables.py). A sample with an oscillator in its region takes the full
   saw_blep (osc_edge); a third saw (no preset has one) adds in a second pass. The same codes as the
   former sample-by-sample loop (test/render_test.py), in a fifth of the cycles (docs/bus.md 9.3). */
#define OBLK 64
#define acc_blk ((uint32_t *)((uint8_t *)hw_scratch + DAC_RING))
_Static_assert(DAC_RING + 4 * OBLK <= HW_SCRATCH_DSP, "the block accumulator lies after the DAC ring");

static inline uint32_t blep_run(uint32_t p, uint32_t inc, uint32_t sinv)   /* samples from p (outside its region)
                                                                            on before the region: >= 1 */
{
	uint32_t n = (mulhu(-inc - p, sinv) >> 16) + 1; /* (2^32 - inc - p) / inc rounded down, + 1 <= the exact count */
	uint32_t q = p + n * inc;                       /* often one short: is the sample after the run outside too? */
	return q + inc < 2 * inc ? n : n + 1;
}

/* rising saw (Q15) with the polyBLEP, any phase */
__attribute__((noinline, section(".srodata"), optimize("O2"))) static int32_t saw_blep16(uint32_t ph, uint32_t inc,
                                                                                          uint32_t inv)
{
	return saw_blep(ph, inc, inv) >> 16;
}

/* one sample of all oscillators, exact: one of them is within one step of a wrap */
__attribute__((noinline, section(".srodata"), optimize("O2"))) static uint32_t osc_edge(void)
{
	uint32_t v = osc_bias;
	for (osc_t *o = osc, *oe = osc + n_osc; o < oe; o++) {
		uint32_t inc = o->inc, p = o->ph + inc;
		int32_t x = saw_blep16(p, inc, o->inv);
		o->ph = p;
		if (o->wave == OSC_PULSE)               /* pulse = (saw(ph) - saw(ph + pw)) / 2; Q15 * Q15 = Q30 */
			v += (uint32_t)(x - saw_blep16(p + pw_off, inc, o->inv)) * (uint32_t)(o->lvl >> 1);
		else
			v += (uint32_t)(x + 32768) * (uint32_t)o->lvl;
	}
	return v;
}

/* a run of two saws and a constant: a[k] = s + (ph0 >> 16) l0 + (ph1 >> 16) l1, two samples per loop. In assembly:
   the compiler cannot keep the eleven values in RV32E's registers here and reloads three of them every sample (the
   C loop is the host's, test/render_test.py) */
__attribute__((always_inline)) static inline uint32_t *run2(uint32_t *a, uint32_t *e, uint32_t s, osc_t *o0, osc_t *o1)
{
	uint32_t p0 = o0->ph, i0 = o0->inc, l0 = o0->lvl, p1 = o1->ph, i1 = o1->inc, l1 = o1->lvl;
	if ((e - a) & 1) {
		p0 += i0;
		p1 += i1;
		*a++ = s + (p0 >> 16) * l0 + (p1 >> 16) * l1;
	}
#if defined(__riscv)
	uint32_t t, u;
	if (a < e)
		__asm volatile(
			"1:	add %[p0], %[p0], %[i0]\n"
			"	add %[p1], %[p1], %[i1]\n"
			"	srli %[t], %[p0], 16\n"
			"	mul %[t], %[t], %[l0]\n"
			"	srli %[u], %[p1], 16\n"
			"	mul %[u], %[u], %[l1]\n"
			"	add %[t], %[t], %[u]\n"
			"	add %[t], %[t], %[s]\n"
			"	sw %[t], 0(%[a])\n"
			"	add %[p0], %[p0], %[i0]\n"
			"	add %[p1], %[p1], %[i1]\n"
			"	srli %[t], %[p0], 16\n"
			"	mul %[t], %[t], %[l0]\n"
			"	srli %[u], %[p1], 16\n"
			"	mul %[u], %[u], %[l1]\n"
			"	add %[t], %[t], %[u]\n"
			"	add %[t], %[t], %[s]\n"
			"	sw %[t], 4(%[a])\n"
			"	addi %[a], %[a], 8\n"
			"	bltu %[a], %[e], 1b\n"
			: [a] "+r"(a), [p0] "+r"(p0), [p1] "+r"(p1), [t] "=&r"(t), [u] "=&r"(u)
			: [e] "r"(e), [s] "r"(s), [i0] "r"(i0), [l0] "r"(l0), [i1] "r"(i1), [l1] "r"(l1)
			: "memory");
#else
	for (; a < e; a++) {
		p0 += i0;
		p1 += i1;
		*a = s + (p0 >> 16) * l0 + (p1 >> 16) * l1;
	}
#endif
	o0->ph = p0;
	o1->ph = p1;
	return a;
}

__attribute__((always_inline)) static inline uint32_t *run1(uint32_t *a, uint32_t *e, uint32_t s, osc_t *o0)
{
	uint32_t p0 = o0->ph, i0 = o0->inc, l0 = o0->lvl;
	if ((e - a) & 1) {
		p0 += i0;
		*a++ = s + (p0 >> 16) * l0;
	}
#if defined(__riscv)
	uint32_t t;
	if (a < e)
		__asm volatile(
			"1:	add %[p0], %[p0], %[i0]\n"
			"	srli %[t], %[p0], 16\n"
			"	mul %[t], %[t], %[l0]\n"
			"	add %[t], %[t], %[s]\n"
			"	sw %[t], 0(%[a])\n"
			"	add %[p0], %[p0], %[i0]\n"
			"	srli %[t], %[p0], 16\n"
			"	mul %[t], %[t], %[l0]\n"
			"	add %[t], %[t], %[s]\n"
			"	sw %[t], 4(%[a])\n"
			"	addi %[a], %[a], 8\n"
			"	bltu %[a], %[e], 1b\n"
			: [a] "+r"(a), [p0] "+r"(p0), [t] "=&r"(t)
			: [e] "r"(e), [s] "r"(s), [i0] "r"(i0), [l0] "r"(l0)
			: "memory");
#else
	for (; a < e; a++) {
		p0 += i0;
		*a = s + (p0 >> 16) * l0;
	}
#endif
	o0->ph = p0;
	return a;
}

__attribute__((noinline, section(".srodata"), optimize("O2"))) static void osc_block(uint32_t *a, uint32_t *end)
{
	while (a < end) {
		uint32_t r = end - a, s = osc_bias;         /* run length, constant */
		for (int i = 0; i < n_osc && r; i++) {
			osc_t *o = &osc[i];
			uint32_t inc = o->inc, p = o->ph + inc, k;
			if (p + inc < 2 * inc) {
				r = 0;
				break;
			}
			k = blep_run(p, inc, o->sinv);
			if (o->wave == OSC_PULSE) {
				uint32_t p2 = p + pw_off;
				if (p2 + inc < 2 * inc) {
					r = 0;
					break;
				}
				uint32_t k2 = blep_run(p2, inc, o->sinv);
				if (k2 < k) k = k2;
				s += ((p >> 16) - (p2 >> 16)) * (uint32_t)(o->lvl >> 1);
			}
			if (k < r) r = k;
		}
		if (!r) {
			*a++ = osc_edge();
			continue;
		}
		uint32_t *e = a + r;
		if (n_saw >= 2) {
			uint32_t *b = a;
			a = run2(a, e, s, saw_o[0], saw_o[1]);
			if (n_saw == 3) {                       /* (no preset yet) a third saw: one more pass, lw / add / sw */
				osc_t *o2 = saw_o[2];
				uint32_t p2 = o2->ph, i2 = o2->inc, l2 = o2->lvl;
				for (; b < e; b++) {
					p2 += i2;
					*b += (p2 >> 16) * l2;
				}
				o2->ph = p2;
			}
		} else if (n_saw == 1)
			a = run1(a, e, s, saw_o[0]);
		else
			do *a++ = s; while (a < e);
		for (int i = 0; i < n_osc; i++)
			if (osc[i].wave == OSC_PULSE)
				osc[i].ph += r * osc[i].inc;
	}
}

__attribute__((noinline, section(".srodata"), optimize("O2"))) static void osc_fill(uint8_t *dst, int n)
{
	int32_t f1 = sd1, f2 = sd2;
	int on = osc_gate && n_osc;
	while (n > 0) {
		int m = n < OBLK ? n : OBLK;
		uint32_t *a = acc_blk, *e = a + m;
		if (on)
			osc_block(a, e);
#if DAC_DUAL
		for (; a < e; a++)
			dst = dac_out(dst, on ? (int32_t)*a >> 16 : DSP_ARR << 7, &f1, &f2);
#else
		if (!on && f1 == f2 && (uint32_t)f1 < 256) {   /* silent and settled (f1 = f2 < 256): mid-scale codes */
			for (uint8_t *de = dst + m; dst < de; )
				*dst++ = DSP_ARR / 2;
		} else {
			if (!on)                                /* silent: mid-scale (Q30 + bias), until it has settled */
				for (uint32_t *b = a; b < e; b++)
					*b = 16384u << 16;
			for (uint32_t *e2 = a + (m & ~1); a < e2; a += 2, dst += 2) {   /* Q30 + bias -> code 0...128 / 256 */
				dst[0] = sdm_step((int32_t)a[0] >> 16, &f1, &f2);           /* (the newest error: f2) */
				dst[1] = sdm_step((int32_t)a[1] >> 16, &f2, &f1);           /* (f1) */
			}
			if (m & 1)
				*dst++ = sdm2((int32_t)*a >> 16, &f1, &f2);
		}
#endif
		n -= m;
	}
	sd1 = f1;
	sd2 = f2;
}

/* ------------------------------------------------------------------ dispatch */
int dsp_kind(void) { return cur ? cur->kind : -1; }

void dsp_rest(void)                                 /* not while the renderer runs */
{
	sd1 = sd2 = 128;
	c_prev = 16384;
}

void dsp_carrier(uint16_t *arr, uint16_t *half)
{
	*arr = DSP_ARR;                                 /* 187.5 kHz, 7 bit */
	*half = (cur && cur->kind == DSP_OSC) ? DAC_HALF : DAC_HALF / DSP_UPS * DSP_UPS;   /* modal: 21 samples */
}

static void fill_seg(uint8_t *dst, int n)
{
	if (cur && cur->kind == DSP_OSC) {
		osc_fill(dst, n);
	} else if (cur) {
		modal_fill(dst, n / DSP_UPS);
	} else {                                        /* no patch (being set up): mid-scale */
		for (int k = 0; k < n; k++)
			dst = dac_out(dst, DSP_ARR << 7, &sd1, &sd2);
	}
}

/* render n periods from time t, switching to each queued V_n at its period (modal: the nearest sample boundary) */
void dsp_fill(uint8_t *dst, int n, uint32_t t)
{
	uint32_t t_start = t;
	while (n > 0) {
		int m = n;
		while (vq_r != vq_w) {
			const vstate_t *v = &vq[vq_r];
			int32_t d = (int32_t)(v->t - t);
			if (d > 0) {
				int k = (d + DSP_CYC - 1) / DSP_CYC;         /* the first period at or after v->t */
				if (cur && cur->kind == DSP_MODAL)
					k = (k + DSP_UPS / 2) / DSP_UPS * DSP_UPS;
				if (k > 0) {
					if (k < m)
						m = k;
					break;
				}
			}
			if ((int32_t)(v->t - t_start) < -DSP_UPS * DSP_CYC)   /* more than a sample before this half: missed */
				late_n++;                        /* by the last render (one at the very end of a half rounds up to
				                                    the next half's first period: not late) */
			vs_apply(v);
			vq_r = (vq_r + 1) % VQ;
		}
		fill_seg(dst, m);
		dst += m * DAC_BPP;
		t += (uint32_t)m * DSP_CYC;
		n -= m;
	}
}

#endif
