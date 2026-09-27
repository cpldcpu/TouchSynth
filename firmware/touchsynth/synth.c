/* TouchSynth voice engine. Mirrors the firmware layer of the behavioural model (sim/behav/behav.py):
 * mono with last-note priority, exponential ADSR envelopes, glide, triangle LFO, key tracking,
 * accent / slide for the demo tunes. All maths in fixed point (the CH32V003 has no multiplier). */
#include "board.h"
#include "hw.h"
#include "synth.h"
#include "tables.h"

patch_t patch;
volatile uint8_t synth_manual;

static const patch_t presets[N_PRESETS] = { PRESET_TABLE };
static const char *const preset_names[N_PRESETS] = { PRESET_NAMES };
static const tune_t tunes[N_TUNES] = { TUNE_TABLE };
static const char *const tune_names[N_TUNES] = { TUNE_NAMES };
static int8_t preset_i;
const uint8_t synth_n_presets = N_PRESETS, synth_n_tunes = N_TUNES;

/* ------------------------------------------------------------------ envelopes (Q15 level) */
typedef struct { uint8_t stage; int32_t level; } env_t;   /* stage: 0 idle, 1 attack, 2 decay/sustain, 3 release */
static env_t fenv, aenv;

static void env_tick(env_t *e, const uint8_t *p)
{
	switch (e->stage) {
	case 1:
		e->level += time_step[p[0]];
		if (e->level >= 32767) { e->level = 32767; e->stage = 2; }
		break;
	case 2: {
		int32_t sus = ((int32_t)p[2] * 32767) / 255;
		e->level = sus + (((e->level - sus) * (int32_t)time_coef[p[1]]) >> 16);
		break; }
	case 3:
		e->level = (e->level * (int32_t)time_coef[p[3]]) >> 16;
		if (e->level < 4) { e->level = 0; e->stage = 0; }
		break;
	}
}

/* ------------------------------------------------------------------ voice state */
static int32_t pitch = -1, target;      /* 1/256 semitone (MIDI * 256) */
static uint8_t cur_flags, glide_idx;
static uint32_t lfo_phase;
static uint16_t boot_ms;
static uint8_t stack[8], n_stack;

static void voice_trigger(uint8_t note, uint8_t flags)
{
	target = (int32_t)note << 8;
	if (pitch < 0)
		pitch = target;
	cur_flags = flags;
	glide_idx = (flags & STEP_SLIDE) ? patch.slide_glide : patch.glide;
	fenv.stage = 1;
	aenv.stage = 1;
}

static void voice_legato(uint8_t note)
{
	target = (int32_t)note << 8;
}

static void voice_release(void)
{
	if (fenv.stage) fenv.stage = 3;
	if (aenv.stage) aenv.stage = 3;
}

/* ------------------------------------------------------------------ pitch -> timer */
static uint32_t pitch_counts(int32_t p)
{
	if (p < (12 << 8)) p = 12 << 8;
	if (p > (131 << 8)) p = 131 << 8;
	int32_t rel = p - (120 << 8);                   /* top_octave_counts starts at MIDI 120 */
	int oct = 0;
	while (rel < 0) { rel += 12 << 8; oct++; }
	int i = rel >> 4, f = rel & 15;
	uint32_t c = top_octave_counts[i] - (((uint32_t)(top_octave_counts[i] - top_octave_counts[i + 1]) * f) >> 4);
	return c << oct;
}

static uint16_t amp_code(uint32_t ticks)
{
	uint32_t c = AMP_K / (ticks - RESET_COUNTS);
	return c > 4095 ? 4095 : c;
}

static uint32_t set_dco(int32_t p, uint8_t pw)
{
	static uint32_t last_counts;
	static uint16_t psc, arr;
	static uint8_t last_pw;
	uint32_t counts = pitch_counts(p);
	if (counts != last_counts || pw != last_pw) {     /* touch the timer only on changes */
		psc = (counts >> 16) + 1;
		arr = counts / psc;
		hw_dco_set(psc, arr, pw);
		last_counts = counts;
		last_pw = pw;
	}
	return (uint32_t)psc * arr;
}

void synth_dco_note(uint16_t pitch256)
{
	uint32_t ticks = set_dco(pitch256, 0);
	hw_cv_set(CV_AMP, amp_code(ticks));
}

/* ------------------------------------------------------------------ tune player */
static int8_t tune_i = -1;
static uint16_t step_i, step_t, step_len, step_gate;

static void tune_tick(void)
{
	if (tune_i < 0)
		return;
	const tune_t *t = &tunes[tune_i];
	if (step_t == 0) {
		if (step_i >= t->n) {                       /* end of tune */
			voice_release();
			tune_i = -1;
			return;
		}
		const tune_step_t *s = &t->steps[step_i];
		step_len = (15000 / t->bpm) * s->len;       /* ms per 16th = 60000 / bpm / 4 */
		step_gate = (s->flags & STEP_SLIDE) ? step_len : step_len * 4 / 5;
		if (s->note)
			voice_trigger(s->note, s->flags);
	}
	if (++step_t == step_gate && t->steps[step_i].note)
		voice_release();
	if (step_t >= step_len) {
		step_t = 0;
		step_i++;
	}
}

void synth_tune_play(int i)
{
	__disable_irq();
	if (i >= 0 && i < N_TUNES) {
		synth_preset(tunes[i].preset);
		tune_i = i;
		step_i = step_t = 0;
	} else {
		tune_i = -1;
		voice_release();
	}
	__enable_irq();
}

int synth_tune_playing(void) { return tune_i; }
const char *synth_tune_name(int i) { return (i >= 0 && i < N_TUNES) ? tune_names[i] : "?"; }

/* ------------------------------------------------------------------ control tick (1 kHz) */
void synth_tick(void)
{
	if (boot_ms < 1000)
		boot_ms++;
	tune_tick();
	env_tick(&fenv, patch.fenv);
	env_tick(&aenv, patch.aenv);
	if (synth_manual || pitch < 0)
		return;

	/* pitch: glide, vibrato */
	if (glide_idx) {
		pitch = target + (((pitch - target) * (int32_t)time_coef[glide_idx]) >> 16);
		if (pitch - target < 3 && target - pitch < 3)
			pitch = target;
	} else {
		pitch = target;
	}
	lfo_phase += (uint32_t)patch.lfo_rate * 42950u;  /* 2^32 / 100 000 per 0.01 Hz and ms */
	uint16_t ph = lfo_phase >> 16;
	int32_t tri = ph < 32768 ? (int32_t)ph * 2 - 32768 : 32767 - ((int32_t)ph - 32768) * 2;   /* Q15 */
	int32_t pm = pitch + (((int32_t)patch.lfo_pitch * tri / 100) * 256 >> 15);

	/* oscillator */
	int32_t pw = patch.pw + (((int32_t)patch.lfo_pw * tri) >> 15);
	if (pw < 8) pw = 8;
	if (pw > 247) pw = 247;
	uint32_t ticks = set_dco(pm, (patch.wave & WAVE_PULSE) ? pw : 0);
	hw_dco_waves(patch.wave & WAVE_SUB, patch.wave & WAVE_NOISE);
	hw_cv_set(CV_AMP, (patch.wave & WAVE_SAW) ? amp_code(ticks) : 0);

	/* filter: base + envelope + key tracking (around C4), in 1/256 octave */
	int32_t amt = (cur_flags & STEP_ACCENT) ? patch.acc_env_amt : patch.env_amt;
	int32_t cut = patch.cutoff + ((amt * fenv.level) >> 15) +
	              ((int32_t)patch.keytrack * (pm - (60 << 8))) / (12 * 255);
	if (cut < 0) cut = 0;
	if (cut > (CUT_TAB_N - 2) * 16) cut = (CUT_TAB_N - 2) * 16;
	int i = cut >> 4, f = cut & 15;
	hw_cv_set(CV_CUT, cut_code[i] + (((int32_t)(cut_code[i + 1] - cut_code[i]) * f) >> 4));
	uint32_t res = (uint32_t)patch.res * RES_THR_CODE / 200;
	hw_cv_set(CV_RES, res);

	/* amplifier (VCA held closed for 0.5 s after boot while the coupling capacitors settle) */
	int32_t vol = (cur_flags & STEP_ACCENT) ? patch.acc_vol : patch.vol;
	int32_t a = (vol * aenv.level) >> 11;           /* 0...4079 */
	i = a >> 6; f = a & 63;
	uint16_t vc = vca_code[i] + (((int32_t)(vca_code[i + 1] - vca_code[i]) * f) >> 6);
	hw_cv_set(CV_VCA, boot_ms < 500 ? 0 : vc);
}

/* ------------------------------------------------------------------ notes (called from the main loop) */
void synth_note_on(uint8_t note, uint8_t flags)
{
	__disable_irq();
	if (tune_i >= 0)
		tune_i = -1;
	for (int k = 0; k < n_stack; k++)               /* remove if already held, then push */
		if (stack[k] == note) { for (; k < n_stack - 1; k++) stack[k] = stack[k + 1]; n_stack--; break; }
	if (n_stack < sizeof(stack))
		stack[n_stack++] = note;
	voice_trigger(note, flags);
	__enable_irq();
}

void synth_note_off(uint8_t note)
{
	__disable_irq();
	for (int k = 0; k < n_stack; k++)
		if (stack[k] == note) { for (; k < n_stack - 1; k++) stack[k] = stack[k + 1]; n_stack--; break; }
	if (n_stack)
		voice_legato(stack[n_stack - 1]);           /* back to the previous held note */
	else
		voice_release();
	__enable_irq();
}

void synth_all_off(void)
{
	__disable_irq();
	n_stack = 0;
	tune_i = -1;
	voice_release();
	__enable_irq();
}

uint16_t synth_held_mask(int base)
{
	uint16_t m = 0;
	for (int k = 0; k < n_stack; k++) {
		int b = stack[k] - base;
		if (b >= 0 && b < 13) m |= 1 << b;
	}
	return m;
}

void synth_preset(int i)
{
	if (i < 0 || i >= N_PRESETS)
		return;
	__disable_irq();
	patch = presets[i];
	preset_i = i;
	__enable_irq();
}

int synth_preset_index(void) { return preset_i; }
const char *synth_preset_name(int i) { return (i >= 0 && i < N_PRESETS) ? preset_names[i] : "?"; }

void synth_init(void)
{
	synth_preset(0);
}
