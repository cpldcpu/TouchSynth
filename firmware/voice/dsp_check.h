/* [2026-10-20] Render check: a fixed scenario through the DAC renderer's public API (dsp.h) and the FNV-1a hash of its
 * duty codes. The console's `check <patch>` runs it on the card, test/render_test.py on the host against the current
 * and the reference sources (the same hash: the card renders what the host test compared). Included by console.c and
 * test/render_test.c only. Changes the patch, the pitch lock and the queue: the console's next preset restores them. */
#ifndef DSP_CHECK_H
#define DSP_CHECK_H

#include "dsp.h"

static uint32_t dsp_check(int patch, uint8_t *buf)  /* buf: DAC_HALF x DAC_BPP bytes */
{
	static const uint8_t notes[] = { 28, 48, 72, 96, 120 };
	uint32_t h = 2166136261u;
	uint16_t arr, half;
	dsp_clock((uint32_t)FRAME_CYCLES << 8);
	dsp_select(patch);
	dsp_rest();
	dsp_carrier(&arr, &half);
	for (unsigned i = 0; i < 4 * sizeof notes; i++) {
		int n = notes[i % sizeof notes];
		if (dsp_kind() == DSP_MODAL) {
			dsp_strike(n, 60 + 50 * (i % 4));
		} else {
			if (i % 3 == 0)
				dsp_phase_reset();
			dsp_pitch((n << 8) + 37 * i, i % 7 != 6);
		}
		dsp_commit(0);
		for (int k = 0; k < 3; k++) {
			dsp_fill(buf, half - 36 * k, 0);        /* uneven lengths (modal: whole samples of 12 periods) */
			for (int j = 0; j < (half - 36 * k) * DAC_BPP; j++)
				h = (h ^ buf[j]) * 16777619u;
		}
	}
	return h;
}

#endif
