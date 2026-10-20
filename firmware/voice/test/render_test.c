/* Host driver of the DAC renderer (dsp.c) for test/render_test.py: plays scenarios through the public API (dsp.h)
 * as the card does, a control tick every 48000 cycles that queues its state D = 4 ticks ahead and a render per
 * buffer half, and writes each scenario's duty codes (ring bytes) to <outdir>/<name>.bin.
 *
 *   render_test <outdir> <osc patches, comma-separated> <modal patches>     (patch numbers as for dsp_select) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board.h"
#include "dsp.h"
#include "hw.h"
void dsp_rest(void);                                /* (not in the reference revision's dsp.h) */
#include "dsp_check.h"

uint16_t hw_scratch[HW_SCRATCH / 2];                /* hw.c */
__attribute__((weak)) void dsp_rest(void) {}        /* the reference revision has none (its checks are not printed) */
static int dac_on;
int hw_dac_active(void) { return dac_on ? DSP_ARR : 0; }

#define TICK 48000
static FILE *out;
static uint32_t T = 1, tick_t = 1;                  /* SysTick time of the next half / the next tick (never 0) */
static uint8_t buf[DAC_HALF * DAC_BPP];
static int note, vib;

typedef void (*tick_fn)(int k);

static void run(const char *dir, const char *name, int ticks, tick_fn fn)
{
	char path[512];
	snprintf(path, sizeof path, "%s/%s.bin", dir, name);
	out = fopen(path, "wb");
	if (!out) { perror(path); exit(1); }
	for (int k = 0; k < ticks; ) {
		uint16_t arr, half;
		dsp_carrier(&arr, &half);
		uint32_t end = T + (uint32_t)half * 2 * arr;
		while ((int32_t)(tick_t - end) < 0 && k < ticks) {
			fn(k++);
			dsp_commit(dac_on ? tick_t + 4 * TICK : 0);
			tick_t += TICK;
		}
		dsp_fill(buf, half, T);
		fwrite(buf, DAC_BPP, half, out);
		T = end;
	}
	fclose(out);
}

static void t_note(int k)                           /* a held note, phases reset at the start; vib: a vibrato */
{
	if (k == 0)
		dsp_phase_reset();
	int v = vib ? ((k * 9) % 64 < 32 ? (k * 9) % 32 : 32 - (k * 9) % 32) * vib - 16 * vib : 0;
	dsp_pitch((note << 8) + v, 1);
}

static void t_sweep(int k)                          /* glide over 6 octaves, gate on / off, phase resets */
{
	if (k % 100 == 0)
		dsp_phase_reset();
	int tri = (k * 37) % 64 < 32 ? (k * 37) % 32 : 32 - (k * 37) % 32;
	dsp_pitch((24 << 8) + k * 19 + 3 * tri, (k % 50) < 40);
}

static void t_modal(int k)                          /* strikes, restrikes of the ringing note, stolen banks */
{
	static int last = 48;
	if (k % 23 == 0) {
		int n = (k / 23) % 5 == 4 ? last : 30 + (k * 7) % 50;
		dsp_strike(n, 40 + (k * 13) % 216);
		last = n;
	}
}

static void t_none(int k) { (void)k; }

static int in_list(const char *l, int p)            /* p in a comma-separated list */
{
	for (const char *s = l; *s; ) {
		if (atoi(s) == p)
			return 1;
		while (*s && *s != ',') s++;
		if (*s) s++;
	}
	return 0;
}

int main(int argc, char **argv)
{
	if (argc < 4) {
		fprintf(stderr, "usage: render_test <outdir> <osc patches> <modal patches>\n");
		return 2;
	}
	const char *dir = argv[1];
	char name[64];
	static const int notes[] = { 24, 36, 48, 57, 60, 72, 84, 96, 108, 119, 127 };
	dsp_clock((uint32_t)TICK << 8);
	char *ol = strdup(argv[2]);
	for (char *s = strtok(ol, ","); s; s = strtok(0, ",")) {
		int p = atoi(s);
		dac_on = 0;
		dsp_select(p);
		dsp_pitch(60 << 8, 0);
		snprintf(name, sizeof name, "osc%d_gate_off", p);
		run(dir, name, 30, t_none);
		dac_on = 1;
		for (unsigned i = 0; i < sizeof notes / sizeof notes[0]; i++) {
			note = notes[i];
			vib = 0;
			snprintf(name, sizeof name, "osc%d_note%d", p, note);
			run(dir, name, note < 40 ? 80 : 40, t_note);
		}
		note = 45;
		vib = 3;
		snprintf(name, sizeof name, "osc%d_vibrato", p);
		run(dir, name, 200, t_note);
		dsp_clock(((uint32_t)TICK << 8) + 5000);    /* pitch lock: a slow controller crystal (+0.04 %) */
		snprintf(name, sizeof name, "osc%d_sweep", p);
		run(dir, name, 400, t_sweep);
		dsp_clock((uint32_t)TICK << 8);
		dac_on = 0;                                 /* immediate states (board 1) */
		note = 50;
		vib = 5;
		snprintf(name, sizeof name, "osc%d_immediate", p);
		run(dir, name, 60, t_note);
	}
	char *ml = strdup(argv[3]);
	for (char *s = strtok(ml, ","); s; s = strtok(0, ",")) {
		int p = atoi(s);
		dac_on = 1;
		dsp_select(p);
		snprintf(name, sizeof name, "modal%d", p);
		run(dir, name, 600, t_modal);
	}
	dsp_select(0);
	run(dir, "none", 20, t_none);
	for (int p = 1; p <= 64; p++) {                 /* the console's render check (dsp_check.h) of every patch */
		if (in_list(argv[2], p) || in_list(argv[3], p))
			printf("check %d %08x\n", p, dsp_check(p, buf));
	}
	return 0;
}
