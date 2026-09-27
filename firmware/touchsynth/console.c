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
 *  cap <n> [us]             capture n loopback samples (PD5) every us microseconds, hex dump
 */
#include <stdio.h>
#include <string.h>
#include "board.h"
#include "hw.h"
#include "synth.h"
#include "ui.h"

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
#else
#define CAP_MAX 512
#endif
static uint16_t cap_buf[CAP_MAX];

static void run(const char *s)
{
	const char *r;
	if (starts(s, "id", &r)) {
		printf("touchsynth %s %s\n", FW_VERSION, CHIP_NAME);
	} else if (starts(s, "status", &r)) {
		printf("preset %d %s octave %d tune %d manual %d\n", synth_preset_index(),
		       synth_preset_name(synth_preset_index()), octave, synth_tune_playing(), synth_manual);
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
		else { led_override = parse_int(&r); led_forced = 1; }
	} else if (starts(s, "touch", &r)) {
		for (int i = 0; i < N_PADS; i++)
			printf("%d %lu %lu %lu\n", i, touch_raw[i], touch_base[i], touch_thr[i]);
	} else if (starts(s, "cap", &r)) {
		int n = parse_int(&r), us = *r ? parse_int(&r) : 20;
		if (n < 1 || n > CAP_MAX) n = CAP_MAX;
		if (us < 5) us = 5;
		hw_capture(cap_buf, n, us);
		printf("cap %d %d\n", n, us);
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
