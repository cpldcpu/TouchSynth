/* TouchSynth user interface
 *
 *  keys C ... C'        play (C = C3 + octave)
 *  SHIFT + key C ... B  select a parameter (see param table); SHIFT tapped alone: back to octave mode
 *  - / +                change the selected parameter (or the octave); the LEDs show the value as a bar
 *  SHIFT + - / +        previous / next preset
 *  SHIFT + C'           play the next demo tune (any key stops it)
 */
#include "board.h"
#include "hw.h"
#include "synth.h"
#include "ui.h"

uint32_t touch_raw[N_PADS], touch_base[N_PADS], touch_thr[N_PADS];
uint16_t touch_state;
uint8_t trim_dac = 128;
int8_t octave;
static uint16_t played;             /* keys that started a note (only those send note-off) */

static int key_note(int k) { return 48 + 12 * octave + k; }
volatile uint16_t led_override;
volatile uint8_t led_forced;

#define TOUCH_ITER 4                /* x 3 samples per pad and scan */

static int8_t sel = -1;             /* selected parameter, -1 = octave */
static uint8_t shift_used;
static volatile uint16_t show_ms;   /* value display timer */
static uint8_t show_val;
static volatile uint16_t blink_ms;
static int8_t next_tune;

/* ------------------------------------------------------------------ parameters: UI value 0...15 <-> patch */
static int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

static int param_get(int k)
{
	switch (k) {
	case 0: return patch.wave & 15;
	case 1: return patch.pw >> 4;
	case 2: return clampi((patch.cutoff - 232 + 76) / 153, 0, 15);   /* 30 Hz ... 15 kHz */
	case 3: return clampi((patch.res + 8) / 16, 0, 15);              /* 12.5 = self-oscillation */
	case 4: return clampi((patch.env_amt + 51) / 102, 0, 15);        /* 0 ... 6 octaves */
	case 5: return patch.fenv[1] >> 1;
	case 6: return clampi((patch.keytrack + 8) / 17, 0, 15);
	case 7: return patch.aenv[0] >> 1;
	case 8: return patch.aenv[1] >> 1;
	case 9: return clampi((patch.aenv[2] + 8) / 17, 0, 15);
	case 10: return patch.glide >> 1;
	case 11: return clampi((patch.lfo_pitch + 2) / 4, 0, 15);         /* vibrato 0 ... 60 cent */
	}
	return 0;
}

void ui_param_set(int k, int v)
{
	v = clampi(v, 0, 15);
	__disable_irq();
	switch (k) {
	case 0: patch.wave = v ? v : 1; break;
	case 1: patch.pw = v * 16 + 8; break;
	case 2: patch.cutoff = 232 + v * 153; break;
	case 3: patch.res = v * 16; break;
	case 4: patch.env_amt = patch.acc_env_amt = v * 102; break;
	case 5: patch.fenv[1] = patch.fenv[3] = v * 2; break;
	case 6: patch.keytrack = v * 17; break;
	case 7: patch.aenv[0] = v * 2; break;
	case 8: patch.aenv[1] = patch.aenv[3] = v * 2; break;
	case 9: patch.aenv[2] = v * 17; break;
	case 10: patch.glide = v ? v * 2 : 0; break;
	case 11: patch.lfo_pitch = v * 4; break;
	}
	__enable_irq();
}

static void show(int v)
{
	show_val = v;
	show_ms = 1500;
}

/* ------------------------------------------------------------------ keys */
static void key_down(int k, uint16_t held)
{
	int shift = held & (1 << PAD_SHIFT);
	if (k == PAD_SHIFT) {
		shift_used = 0;
		return;
	}
	if (shift)
		shift_used = 1;
	if (k < 13) {
		if (!shift) {
			synth_note_on(key_note(k), 0);
			played |= 1 << k;
		} else if (k == 12) {                       /* SHIFT + C': demo tune */
			synth_tune_play(next_tune);
			next_tune = (next_tune + 1) % synth_n_tunes;
		} else {                                    /* SHIFT + key: select parameter */
			sel = k;
			show(param_get(k));
		}
		return;
	}
	int d = (k == PAD_PLUS) ? 1 : -1;
	if (shift) {                                    /* preset */
		int p = (synth_preset_index() + d + synth_n_presets) % synth_n_presets;
		synth_preset(p);
		show(p);
	} else if (sel < 0) {                           /* octave -2 ... +2 */
		octave = clampi(octave + d, -2, 2);
		show(7 + 2 * octave);
	} else {
		ui_param_set(sel, param_get(sel) + d);
		show(param_get(sel));
	}
}

static void key_up(int k)
{
	if (k < 13 && (played & (1 << k))) {
		played &= ~(1 << k);
		synth_note_off(key_note(k));
	}
	else if (k == PAD_SHIFT && !shift_used)
		sel = -1;                                   /* SHIFT tapped alone: octave mode */
}

/* ------------------------------------------------------------------ touch processing */
void ui_init(void)
{
	uint32_t sum[N_PADS] = { 0 }, sq[N_PADS] = { 0 };
	const int n = 16;
	for (int s = 0; s < n; s++) {
		hw_touch_scan(touch_raw, TOUCH_ITER);
		for (int i = 0; i < N_PADS; i++) {
			sum[i] += touch_raw[i];
			sq[i] += (touch_raw[i] >> 2) * (touch_raw[i] >> 2);
		}
	}
	for (int i = 0; i < N_PADS; i++) {
		touch_base[i] = sum[i] / n;
		uint32_t m = touch_base[i] >> 2;
		uint32_t var = sq[i] / n - m * m;           /* variance of raw/4 */
		uint32_t sd = 1;
		while (sd * sd < var) sd++;
		/* threshold: 8 sigma, at least 3 LSB per sample (S5: a 5 pF touch gives >= 14.8 LSB/sample on V003) */
		uint32_t thr = 8 * 4 * sd, min = 3 * 3 * TOUCH_ITER;
		touch_thr[i] = thr > min ? thr : min;
	}
}

void ui_poll(void)
{
	hw_touch_scan(touch_raw, TOUCH_ITER);
	uint16_t st = touch_state;
	for (int i = 0; i < N_PADS; i++) {
		int32_t d = (int32_t)(touch_raw[i] - touch_base[i]);
		if (st & (1 << i)) {
			if (d < (int32_t)touch_thr[i] / 2)      /* hysteresis */
				st &= ~(1 << i);
		} else {
			if (d > (int32_t)touch_thr[i])
				st |= 1 << i;
			else                                    /* track slow drift while untouched */
				touch_base[i] += d / 64;
		}
	}
	uint16_t chg = st ^ touch_state;
	for (int i = 0; i < N_PADS; i++) {
		if (!(chg & (1 << i)))
			continue;
		if (st & (1 << i))
			key_down(i, st);
		else
			key_up(i);
	}
	touch_state = st;

	/* LEDs: value bar while editing, otherwise held notes; selected parameter blinks; SHIFT LED in edit mode */
	uint16_t leds;
	if (led_forced)
		leds = led_override;
	else if (show_ms)
		leds = (uint16_t)((2u << show_val) - 1);
	else {
		leds = synth_held_mask(key_note(0));
		if (sel >= 0 && (blink_ms & 256))
			leds |= 1 << sel;
		if (sel >= 0)
			leds |= 1 << PAD_SHIFT;
		if (synth_tune_playing() >= 0 && (blink_ms & 128))
			leds |= 1 << 12;
	}
	static uint16_t last_leds = 0xFFFF;
	static uint8_t last_dac;
	if (leds != last_leds || trim_dac != last_dac) {
		hw_leds_dac(leds, trim_dac);
		last_leds = leds;
		last_dac = trim_dac;
	}
}

void ui_tick(void)
{
	if (show_ms)
		show_ms--;
	blink_ms++;
}
