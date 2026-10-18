/* Test console over the SWIO debug channel (minichlink -T), for the verification plan (docs/verification_plan.md).
 *
 *  id                       chip, firmware version
 *  status                   preset, octave, CV codes, touch state
 *  note <midi> | off        play / release a note through the engine
 *  wave <mask> [pw]         waveforms: 1 saw, 2 pulse, 4 sub, 8 noise; pulse width 0...255
 *  preset <i> | tune <i>    load a preset / play a demo tune (-1 stops)
 *  param <k> <v>            UI parameter k (0...11) to value v (0...15)
 *  cv <amp|cut|res|vca> <code>   manual mode: set a 12-bit CV directly (the engine pauses)
 *  dco <midi>               manual mode: set the DCO pitch (and CV_AMP) directly
 *  auto                     leave manual mode
 *  trim <0...255>           VCA offset trim DAC
 *  leds <hex> | leds auto   force the 16 LEDs / normal display
 *  touch                    raw, baseline and threshold of all pads
 *  recal                    re-measure the touch baselines (hands off)
 *  dac                      DAC mode on/off and the DMA ring counter twice, 100 us apart (diagnostics)
 *  keys <0|1>               disable / enable the touch keys (pads still scanned; for unattended recordings)
 *  cap <n> [us]             capture n loopback samples (PD5) every us microseconds, hex dump
 *  adc <ch>                 mean / min / max of 64 conversions of ADC channel ch (diagnostics)
 *  latch <0|1>              hold the 595 latch line PD4 low / high (diagnostics)
 *  wait <ms>                pause up to 5 s (settling between test steps)
 *  capcv <ch> <code> <n> [us]   set CV ch (0 amp, 1 cut, 2 res, 3 vca) and capture at once (step response)
 */
#include <stdio.h>
#include <string.h>
#include "board.h"
#include "hw.h"
#include "synth.h"
#include "ui.h"
#include "dsp.h"

#define FW_VERSION "0.1"

static char line[40];
static volatile uint8_t line_len, line_ready;

void handle_debug_input(int numbytes, uint8_t *data)
{
	for (int i = 0; i < numbytes; i++) {
		char c = data[i];
		if (line_ready)
			return;
		if (c == '\n' || c == '\r') {
			if (line_len) { line[line_len] = 0; line_ready = 1; }
		} else if (line_len < sizeof(line) - 1) {
			line[line_len++] = c;
		}
	}
}

static int parse_int(const char **s)
{
	while (**s == ' ') (*s)++;
	int neg = 0, v = 0, base = 10;
	if (**s == '-') { neg = 1; (*s)++; }
	if ((*s)[0] == '0' && (*s)[1] == 'x') { base = 16; *s += 2; }
	for (;;) {
		char c = **s;
		int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : 99;
		if (d >= base) break;
		v = v * base + d;
		(*s)++;
	}
	return neg ? -v : v;
}

static int starts(const char *s, const char *w, const char **rest)
{
	int n = strlen(w);
	if (strncmp(s, w, n) || (s[n] && s[n] != ' '))
		return 0;
	*rest = s + n;
	return 1;
}

#if defined(CH32V003)
#define CAP_MAX 128                 /* 2 KB RAM */
#elif defined(CH32V006)
#define CAP_MAX 2048                /* 4 KB of 8 KB RAM, shared with the DAC ring buffer (hw.c) */
#define cap_buf hw_scratch
#else
#define CAP_MAX 512                 /* CH32V002: 4 KB RAM */
#endif
#if !defined(CH32V006)
static uint16_t cap_buf[CAP_MAX];
#endif

extern volatile uint32_t tick_count;

static void run(const char *s)
{
	const char *r;
	if (starts(s, "id", &r)) {
		printf("touchsynth %s %s\n", FW_VERSION, CHIP_NAME);
	} else if (starts(s, "status", &r)) {
		printf("preset %d %s octave %d tune %d manual %d\n", synth_preset_index(),
		       synth_preset_name(synth_preset_index()), octave, synth_tune_playing(), synth_manual);
		printf("ticks %lu\n", tick_count);
		printf("cv amp %d cut %d res %d vca %d trim %d touch %04x\n", hw_cv_get(CV_AMP), hw_cv_get(CV_CUT),
		       hw_cv_get(CV_RES), hw_cv_get(CV_VCA), trim_dac, touch_state);
	} else if (starts(s, "note", &r)) {
		synth_note_on(parse_int(&r), 0);
	} else if (starts(s, "off", &r)) {
		synth_all_off();
	} else if (starts(s, "wave", &r)) {
		int m = parse_int(&r);
		patch.wave = m & 15;
		if (*r) patch.pw = parse_int(&r);
	} else if (starts(s, "preset", &r)) {
		synth_preset(parse_int(&r));
	} else if (starts(s, "tune", &r)) {
		synth_tune_play(parse_int(&r));
	} else if (starts(s, "param", &r)) {
		int k = parse_int(&r), v = parse_int(&r);
		ui_param_set(k, v);
	} else if (starts(s, "cv", &r)) {
		while (*r == ' ') r++;
		int ch = !strncmp(r, "amp", 3) ? CV_AMP : !strncmp(r, "cut", 3) ? CV_CUT :
		         !strncmp(r, "res", 3) ? CV_RES : !strncmp(r, "vca", 3) ? CV_VCA : -1;
		if (ch < 0) { printf("?cv\n"); return; }
		r += 3;
		synth_manual = 1;
		hw_cv_set(ch, parse_int(&r));
	} else if (starts(s, "dco", &r)) {
		synth_manual = 1;
		synth_dco_note(parse_int(&r) << 8);
	} else if (starts(s, "auto", &r)) {
		synth_manual = 0;
	} else if (starts(s, "trim", &r)) {
		trim_dac = parse_int(&r);
	} else if (starts(s, "leds", &r)) {
		while (*r == ' ') r++;
		if (!strncmp(r, "auto", 4)) led_forced = 0;
		else {                                      /* hex, with or without 0x (decimal parse read "e000" as 0) */
			if (r[0] == '0' && r[1] == 'x') r += 2;
			uint16_t v = 0;
			for (char c; (c = *r) != 0; r++) {
				int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 :
				        c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
				if (d < 0) break;
				v = (uint16_t)(v << 4 | d);
			}
			led_override = v; led_forced = 1;
		}
	} else if (starts(s, "dac", &r)) {                /* dac: DAC mode state, DMA transfers left (must change) */
		uint16_t c0 = hw_dac_count();
		Delay_Us(100);
		uint16_t ov, mx, gp;
		hw_dac_stats(&ov, &mx, &gp);
		printf("dac %d dma %u %u overruns %u fill_max %u us gap_max %u us\n", hw_dac_active(), c0, hw_dac_count(),
		       ov, mx, gp);
	} else if (starts(s, "keys", &r)) {               /* keys <0|1>: disable / enable the touch keys */
		keys_enabled = parse_int(&r) ? 1 : 0;
	} else if (starts(s, "recal", &r)) {
		ui_init();                                  /* re-measure the untouched baselines */
	} else if (starts(s, "touch", &r)) {
		for (int i = 0; i < N_PADS; i++)
			printf("%d %lu %lu %lu\n", i, touch_raw[i], touch_base[i], touch_thr[i]);
	} else if (hw_dac_active() && (starts(s, "capcv", &r) || starts(s, "cap", &r) || starts(s, "adc", &r))) {
		printf("busy: DAC mode uses the capture buffer\n");     /* hw_scratch is the DAC ring buffer now */
	} else if (starts(s, "capcv", &r)) {              /* capcv <ch 0..3> <code> <n> [us]: CV step, then capture */
		int ch = parse_int(&r), code = parse_int(&r), n = parse_int(&r), us = *r ? parse_int(&r) : 20;
		if (ch < 0 || ch > 3) { printf("?ch\n"); return; }
		if (n < 1 || n > CAP_MAX) n = CAP_MAX;
		if (us < 5) us = 5;
		synth_manual = 1;
		hw_cv_set(ch, code);
		uint32_t el = hw_capture(cap_buf, n, us);
		printf("cap %d %d %lu\n", n, us, el);
		for (int i = 0; i < n; i++)
			printf("%03x%c", cap_buf[i], (i % 16 == 15 || i == n - 1) ? '\n' : ' ');
	} else if (starts(s, "wait", &r)) {               /* wait <ms>: settling pause between test steps */
		int ms = parse_int(&r);
		if (ms > 5000) ms = 5000;
		uint32_t t0 = SysTick->CNT;
		while ((SysTick->CNT - t0) / (F_CPU / 1000) < (uint32_t)ms)
#if defined(CH32V006)
			hw_dac_poll(dsp_fill);                  /* keep the DAC fed (DAC mode) */
#else
			;
#endif
	} else if (starts(s, "latch", &r)) {              /* latch <0|1>: hold PD4 (595 RCLK, edge-triggered) - diagnostics */
		funDigitalWrite(PIN_LATCH, parse_int(&r) ? 1 : 0);
		Delay_Us(10);
		printf("PD in %02lx" "%c", GPIOD->INDR & 0xff, 10);
	} else if (starts(s, "adc", &r)) {                /* adc <ch>: mean and min/max of 64 conversions */
		int ch = parse_int(&r);
		if (ch < 0 || ch > 9) { printf("?ch\n"); return; }
		hw_capture_ch(ch, cap_buf, 64, 20);
		uint32_t sum = 0; uint16_t lo = 0xFFFF, hi = 0;
		for (int i = 0; i < 64; i++) {
			sum += cap_buf[i];
			if (cap_buf[i] < lo) lo = cap_buf[i];
			if (cap_buf[i] > hi) hi = cap_buf[i];
		}
		printf("adc %d mean %lu min %u max %u\n", ch, sum / 64, lo, hi);
	} else if (starts(s, "cap", &r)) {
		int n = parse_int(&r), us = *r ? parse_int(&r) : 20;
		if (n < 1 || n > CAP_MAX) n = CAP_MAX;
		if (us < 5) us = 5;
		uint32_t el = hw_capture(cap_buf, n, us);
		printf("cap %d %d %lu\n", n, us, el);       /* el: elapsed us, > n * us if the ADC could not keep up */
		for (int i = 0; i < n; i++)
			printf("%03x%c", cap_buf[i], (i % 16 == 15 || i == n - 1) ? '\n' : ' ');
	} else {
		printf("?\n");
		return;
	}
	printf("ok\n");
}

void console_poll(void)
{
	poll_input();
	if (line_ready) {
		run(line);
		line_len = 0;
		line_ready = 0;
	}
}
