/* TouchSynth Poly voice bus, card side (docs/bus.md).
 *
 * Everything runs in the control tick (the SYNC edge, touchsynth.c), before synth_tick:
 *   1. frame counter + 1; SYNC period filter (pbar), HSITRIM at start-up, SYNC loss (VCA muted after 10 ticks)
 *   2. parse what the RX DMA ring holds: COBS frames on 0x00 delimiters, CRC-8, voice bitmask; untimed messages
 *      act at once (FRAME, CONFIG, ASSIGN, REQUEST, PATCH_PRESET), timed ones go into the event queue
 *   3. run the queued events due at this frame, in arrival order
 * [2026-10-19] The decoder runs over the RX ring in place (hw_bus_span), its state in registers (about twice as
 * fast as a call per byte: 87 bytes 11.1 k -> 5.2 k cycles). Foreign packets (dst without this card's bit) are
 * dropped at their first decoded byte, before the CRC (BUS_EARLY, default on), and the rest up to the next 0x00
 * is skipped at memory speed (71 foreign bytes per frame: 8.8 k -> 3-4 k cycles per tick; bus.md 9.5).
 * Per-voice packets (type | M_MULTI) carry one record per voice in dst; the card takes its own record.
 * Bytes received during frame n are parsed at tick n + 1. The controller stamps an event for its arrival frame + L
 * and sends it in the next frame, so an event sent in frame n is for frame n + L - 1: with L = 2 it is parsed and
 * runs at tick n + 1, with no slack (measured from the transmit frame: L - 1 + D; bus.md 9). What the tick computes appears D frames later
 * (hw_cv_commit, dsp_commit: bus.md 3.1). Replies go out at once on the return line (TX DMA), so a REQUEST is
 * answered in the tick that parses it.
 */
#include <string.h>
#include "board.h"
#include "hw.h"
#include "synth.h"
#include "dsp.h"
#include "bus.h"

#if BOARD_CARD

#ifndef BUS_EARLY
#define BUS_EARLY 1                                 /* drop foreign packets at their dst byte (make BUS_EARLY=0: after
                                                       the CRC, as before) */
#endif

bus_t bus;
static uint16_t dac_over;                           /* the DAC's overrun count at the last look (it restarts with
                                                       the DAC at a patch change) */
static uint8_t tick_sync;                           /* this tick is a SYNC edge (else SysTick bridges a gap) */

/* message types (bus.md 5) */
enum {
	M_FRAME = 0x01, M_CONFIG = 0x02, M_ASSIGN = 0x03,
	M_NOTE_ON = 0x10, M_NOTE_OFF = 0x11, M_PITCH = 0x12, M_VOICE_STATE = 0x13,
	M_CTRL = 0x20, M_PARAM = 0x21, M_PATCH_DATA = 0x22, M_PATCH_SELECT = 0x23, M_PATCH_PRESET = 0x24,
	M_REQUEST = 0x30, M_CALIBRATE = 0x31,
	M_HELLO = 0x80, M_STATUS = 0x81, M_CAL_DATA = 0x82, M_COUNTERS = 0x83,
	M_MULTI = 0x40                                  /* type flag: one record per voice in dst (bus.md 5.1) */
};
enum { R_STATUS, R_CAL_DATA, R_HELLO, R_COUNTERS };    /* REQUEST what */

static int timed(uint8_t type)
{
	return (type >= M_NOTE_ON && type <= M_VOICE_STATE) || type == M_CTRL || type == M_PARAM ||
	       type == M_PATCH_SELECT || type == M_CALIBRATE;
}

/* CRC-8, polynomial 0x07, initial value 0, MSB first, no final XOR: over a whole packet including its CRC = 0 */
static const uint8_t crc_tab[256] = {
	0x00, 0x07, 0x0e, 0x09, 0x1c, 0x1b, 0x12, 0x15, 0x38, 0x3f, 0x36, 0x31, 0x24, 0x23, 0x2a, 0x2d,
	0x70, 0x77, 0x7e, 0x79, 0x6c, 0x6b, 0x62, 0x65, 0x48, 0x4f, 0x46, 0x41, 0x54, 0x53, 0x5a, 0x5d,
	0xe0, 0xe7, 0xee, 0xe9, 0xfc, 0xfb, 0xf2, 0xf5, 0xd8, 0xdf, 0xd6, 0xd1, 0xc4, 0xc3, 0xca, 0xcd,
	0x90, 0x97, 0x9e, 0x99, 0x8c, 0x8b, 0x82, 0x85, 0xa8, 0xaf, 0xa6, 0xa1, 0xb4, 0xb3, 0xba, 0xbd,
	0xc7, 0xc0, 0xc9, 0xce, 0xdb, 0xdc, 0xd5, 0xd2, 0xff, 0xf8, 0xf1, 0xf6, 0xe3, 0xe4, 0xed, 0xea,
	0xb7, 0xb0, 0xb9, 0xbe, 0xab, 0xac, 0xa5, 0xa2, 0x8f, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9d, 0x9a,
	0x27, 0x20, 0x29, 0x2e, 0x3b, 0x3c, 0x35, 0x32, 0x1f, 0x18, 0x11, 0x16, 0x03, 0x04, 0x0d, 0x0a,
	0x57, 0x50, 0x59, 0x5e, 0x4b, 0x4c, 0x45, 0x42, 0x6f, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7d, 0x7a,
	0x89, 0x8e, 0x87, 0x80, 0x95, 0x92, 0x9b, 0x9c, 0xb1, 0xb6, 0xbf, 0xb8, 0xad, 0xaa, 0xa3, 0xa4,
	0xf9, 0xfe, 0xf7, 0xf0, 0xe5, 0xe2, 0xeb, 0xec, 0xc1, 0xc6, 0xcf, 0xc8, 0xdd, 0xda, 0xd3, 0xd4,
	0x69, 0x6e, 0x67, 0x60, 0x75, 0x72, 0x7b, 0x7c, 0x51, 0x56, 0x5f, 0x58, 0x4d, 0x4a, 0x43, 0x44,
	0x19, 0x1e, 0x17, 0x10, 0x05, 0x02, 0x0b, 0x0c, 0x21, 0x26, 0x2f, 0x28, 0x3d, 0x3a, 0x33, 0x34,
	0x4e, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5c, 0x5b, 0x76, 0x71, 0x78, 0x7f, 0x6a, 0x6d, 0x64, 0x63,
	0x3e, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2c, 0x2b, 0x06, 0x01, 0x08, 0x0f, 0x1a, 0x1d, 0x14, 0x13,
	0xae, 0xa9, 0xa0, 0xa7, 0xb2, 0xb5, 0xbc, 0xbb, 0x96, 0x91, 0x98, 0x9f, 0x8a, 0x8d, 0x84, 0x83,
	0xde, 0xd9, 0xd0, 0xd7, 0xc2, 0xc5, 0xcc, 0xcb, 0xe6, 0xe1, 0xe8, 0xef, 0xfa, 0xfd, 0xf4, 0xf3,
};

static uint8_t crc8(const uint8_t *p, int n)
{
	uint8_t c = 0;
	while (n--)
		c = crc_tab[c ^ *p++];
	return c;
}

#define PKT_MAX 64
static uint8_t pkt[PKT_MAX];                        /* the packet being decoded (bus.md 4: up to 64 bytes) */

/* ------------------------------------------------------------------ replies (return line) */
#define TX_MAX 64                                   /* COUNTERS: 61 bytes decoded, 62 encoded, 2 delimiters */
static uint8_t tx_buf[TX_MAX];

/* COBS-encode src type payload crc8 into tx_buf, then 0x00, and start the DMA; n = payload bytes */
static void reply(uint8_t type, const uint8_t *pay, int n)
{
	if (n + 6 > TX_MAX || hw_bus_tx_busy())
		return;
	uint8_t crc = crc_tab[crc_tab[bus.addr] ^ type];
	for (int i = 0; i < n; i++)
		crc = crc_tab[crc ^ pay[i]];
	tx_buf[0] = 0;                                  /* a leading delimiter: the controller's decoder resynchronises
	                                                   at once even after noise on the line */
	int o = 2, c = 1;                               /* COBS: tx_buf[c] = distance to the next zero */
	for (int i = -2; i <= n; i++) {                 /* src, type, payload, crc */
		uint8_t b = i == -2 ? bus.addr : i == -1 ? type : i < n ? pay[i] : crc;
		if (b) {
			tx_buf[o++] = b;
			if (o - c < 0xFF)
				continue;
		}
		tx_buf[c] = o - c;
		c = o++;
	}
	tx_buf[c] = o - c;
	tx_buf[o++] = 0;
	if (hw_bus_send(tx_buf, o))
		bus.st.replies++;
}

static void put16(uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }

static void reply_hello(void)
{
	uint8_t p[11];
	for (int i = 0; i < 2; i++) {
		uint32_t u = hw_uid(i);
		put16(p + 4 * i, u);
		put16(p + 4 * i + 2, u >> 16);
	}
	put16(p + 8, BUS_FW_VERSION);
	p[10] = DAC_DUAL ? 1 : 0;                       /* capabilities: bit 0 dual PWM */
	reply(M_HELLO, p, sizeof p);
}

static uint8_t sat8(uint16_t v) { return v > 255 ? 255 : v; }

static void reply_status(void)
{
	uint8_t p[11];
	int32_t ppm = bus_ppm();
	p[0] = (bus.state == BUS_SYNCED ? 1 : 0) | (bus.state == BUS_STANDALONE ? 8 : 0);   /* synced, standalone */
	p[1] = (RCC->CTLR & RCC_HSITRIM) >> 3;
	put16(p + 2, (uint16_t)(int16_t)(ppm < -32768 ? -32768 : ppm > 32767 ? 32767 : ppm));
	p[4] = sat8(bus.st.crc);
	p[5] = sat8(bus.st.late);
	p[6] = sat8(bus.st.slips);
	p[7] = sat8(bus.st.late_ticks);
	p[8] = sat8(bus.st.underruns);
	p[9] = bus.load;
	p[10] = bus.state;                              /* extension: BUS_* */
	reply(M_STATUS, p, sizeof p);
}

extern volatile uint32_t tick_run_max, tick_core_max;
uint32_t stack_free(void);

/* parser load (COUNTERS extension): cycles per tick (mean over 256 ticks, longest; replies not included), most bytes
   in one tick, packets for other cards */
uint32_t bus_reply_cycles;                          /* this tick's replies (touchsynth.c: tick_core_max) */
static uint32_t parse_sum;
static uint16_t parse_avg, parse_max, rx_max, foreign;

static void reply_counters(int clear)                /* extension (bus.md 5.2): all counters, 16 bit */
{
	uint8_t *p = pkt;                               /* the REQUEST in it is read: 58 bytes off the stack (the reply
	                                                   runs in the tick, possibly over a DAC render) */
	_Static_assert(2 * (sizeof(bus_stats_t) / 2 + 4) + 20 <= PKT_MAX, "COUNTERS payload");
	uint16_t rxb, rxe;
	hw_rx_stats(&rxb, &rxe);
	const uint16_t *s = (const uint16_t *)&bus.st;
	int n = 0;
	put16(p + n, rxb); n += 2;
	for (unsigned i = 0; i < sizeof(bus_stats_t) / 2; i++, n += 2)
		put16(p + n, s[i]);
	put16(p + n, bus.frame); n += 2;
	put16(p + n, tick_run_max > 0xFFFF ? 0xFFFF : tick_run_max); n += 2;
	put16(p + n, stack_free()); n += 2;
	p[n++] = synth_gate();                          /* voice state: gate, preset, active slot, D, pitch */
	p[n++] = synth_preset_index();
	p[n++] = bus.slot;
	p[n++] = bus.delay;
	int32_t pm = synth_pitch();
	put16(p + n, pm < 0 ? 0 : pm > 0xFFFF ? 0xFFFF : pm); n += 2;
	dac_stats_t ds;                                 /* DAC render: longest (cycles), least slack (periods) */
	hw_dac_stats(&ds, 0);
	put16(p + n, ds.fill_max > 0xFFFF ? 0xFFFF : ds.fill_max); n += 2;
	put16(p + n, ds.slack_min); n += 2;
	put16(p + n, parse_avg); n += 2;                /* parser: mean, longest (cycles), most bytes, foreign packets */
	put16(p + n, parse_max); n += 2;
	put16(p + n, rx_max); n += 2;
	put16(p + n, foreign); n += 2;
	put16(p + n, tick_core_max > 0xFFFF ? 0xFFFF : tick_core_max); n += 2;   /* longest tick without replies */
	reply(M_COUNTERS, p, n);
	if (clear) {
		tick_run_max = tick_core_max = 0;
		parse_max = rx_max = 0;
		hw_dac_stats(0, 1);                         /* the DAC's maxima too (its overruns are counted already) */
		dac_over = 0;
	}
}

/* ------------------------------------------------------------------ timed events */
#define EVQ 16
typedef struct { uint16_t frame; uint8_t type, len; uint8_t d[4]; } bus_ev_t;
static bus_ev_t evq[EVQ];                           /* in arrival order */
static uint8_t n_ev;

static int16_t get16(const uint8_t *p) { return (int16_t)(p[0] | p[1] << 8); }

static void ev_run(const bus_ev_t *e)
{
	const uint8_t *d = e->d;
	switch (e->type) {
	case M_NOTE_ON:
		if (e->len >= 4) synth_bus_note_on((uint16_t)get16(d), d[2], d[3]);
		break;
	case M_NOTE_OFF:
		synth_bus_note_off();
		break;
	case M_PITCH:
		if (e->len >= 2) synth_bus_pitch((uint16_t)get16(d));
		break;
	case M_VOICE_STATE:
		if (e->len >= 3 && synth_bus_state(d[0], (uint16_t)get16(d + 1)))
			bus.st.repairs++;
		break;
	case M_CTRL:
		if (e->len >= 3) synth_bus_ctrl(d[0], get16(d + 1));
		break;
	case M_PARAM:
		if (e->len >= 3 && !synth_bus_param(d[0], get16(d + 1)))
			bus.st.other++;
		break;
	case M_PATCH_SELECT:
		if (e->len >= 1) {
			bus.slot = d[0] & 3;
			synth_bus_preset(bus.slots[bus.slot]);
		}
		break;
	}                                               /* CALIBRATE: not yet (no loopback routine on the bus) */
}

static void ev_queue(uint8_t type, const uint8_t *p, int n)
{
	if (n < 1) { bus.st.other++; return; }
	int8_t dt = (int8_t)(p[0] - (uint8_t)bus.frame);   /* execution frame, relative: -128...127 */
	if (dt > 32) { bus.st.far++; return; }
	if (dt < 0) { bus.st.late++; dt = 0; }          /* late: runs in this tick */
	if (n_ev >= EVQ) { bus.st.qfull++; return; }
	bus_ev_t *e = &evq[n_ev++];
	e->frame = bus.frame + dt;
	e->type = type;
	e->len = n - 1 > 4 ? 4 : n - 1;
	memcpy(e->d, p + 1, e->len);
}

static void ev_due(void)
{
	int w = 0;
	for (int i = 0; i < n_ev; i++) {
		if ((int16_t)(evq[i].frame - bus.frame) <= 0)
			ev_run(&evq[i]);
		else
			evq[w++] = evq[i];
	}
	n_ev = w;
}

/* ------------------------------------------------------------------ packets */
static void config(const uint8_t *p, int n)
{
	if (n < 5) { bus.st.other++; return; }
	int d = p[0] < 1 ? 1 : p[0] > CV_DELAY_MAX ? CV_DELAY_MAX : p[0];
	bus.delay = d;
	bus.lead = p[1];
	hw_cv_delay(d);
	synth_bus_tuning(get16(p + 2));                 /* flags p[4]: none defined yet */
}

static inline int for_me(uint8_t dst)               /* unaddressed: 0x00 (enumeration) and 0xFF */
{
	return dst == 0xFF || (bus.addr > 7 ? dst == 0 : (dst >> bus.addr) & 1);
}

/* type | M_MULTI: payload frame, [ID (CTRL, PARAM)], one record per voice in dst in address order; this card's
   record -> the plain message in e (frame, [ID], record); returns its length, 0 if none */
static int record(uint8_t type, uint8_t dst, const uint8_t *q, int n, uint8_t *e)
{
	static const uint8_t len_of[] = { 4, 1, 2, 3 };     /* NOTE_ON, NOTE_OFF, PITCH, VOICE_STATE */
	int ctl = type == M_CTRL || type == M_PARAM;
	int len = type >= M_NOTE_ON && type <= M_VOICE_STATE ? len_of[type - M_NOTE_ON] : ctl ? 2 : 0;
	int pre = 1 + ctl, k = 0;                       /* the frame byte, the ID */
	if (!len || bus.addr > 7)
		return 0;
	for (int a = 0; a < bus.addr; a++)
		k += (dst >> a) & 1;
	int o = pre + k * len;
	if (n < o + len)
		return 0;
	memcpy(e, q, pre);
	memcpy(e + pre, q + o, len);
	return pre + len;
}

static void request(uint8_t dst, const uint8_t *q, int n, uint8_t type);

static __attribute__((noinline)) void packet(uint8_t *p, int n)   /* noinline: keeps parse()'s loop in registers */
{
	if (n < 3) { bus.st.framing++; return; }
	if (crc8(p, n)) { bus.st.crc++; return; }
	n -= 3;                                         /* payload bytes after dst, type */
	uint8_t dst = p[0], type = p[1], e[7];
	const uint8_t *q = p + 2;
	if (!for_me(dst)) {
		foreign++;
		return;
	}
	bus.st.packets++;
	if (type & M_MULTI) {                           /* this card's record, as the plain message */
		int k = record(type & ~M_MULTI, dst, q, n, e);
		if (!k) { bus.st.other++; return; }
		type &= ~M_MULTI;
		q = e;
		n = k;
	}
	if (type == M_ASSIGN || type == M_REQUEST) {    /* replies: not counted as parser time */
		uint32_t t0 = SysTick->CNT;
		request(dst, q, n, type);
		bus_reply_cycles += SysTick->CNT - t0;
		return;
	}
	if (timed(type)) {
		if (bus.state == BUS_SYNCED || bus.state == BUS_LOST)
			ev_queue(type, q, n);
		return;
	}
	switch (type) {
	case M_FRAME: {                                 /* sent in frame f, parsed at f + 1; a SysTick tick that
		                                                   bridges a missing edge runs 0.25 ms after it, when the
		                                                   frame's own FRAME is already in */
		if (n < 2) break;
		uint16_t f = (uint16_t)get16(q);
		if (bus.state == BUS_LISTEN) {
			bus.state = BUS_SYNCED;
		} else if ((uint16_t)(f + 1) == bus.frame || (!tick_sync && f == bus.frame)) {
			return;                                 /* consistent (a bridging tick also sees the last frame's) */
		} else {
			bus.st.slips++;                         /* queued events hold absolute frames: they stay */
		}
		bus.frame = f + (tick_sync ? 1 : 0);
		return; }
	case M_CONFIG:
		config(q, n);
		return;
	case M_PATCH_PRESET:                            /* interim (bus.md 5.1): a firmware preset into a slot */
		if (n < 2) break;
		bus.slots[q[0] & 3] = q[1];
		return;
	}
	bus.st.other++;                                 /* too short, unknown, or PATCH_DATA (not yet) */
}

static void request(uint8_t dst, const uint8_t *q, int n, uint8_t type)
{
	int un = bus.addr > 7;
	if (type == M_ASSIGN) {                         /* only to dst 0x00: the released, unaddressed card */
		if (n < 1 || dst || !un) { bus.st.other++; return; }
		bus.addr = q[0] & 7;
		reply_hello();
		return;
	}                                               /* REQUEST: to this card alone (or to the unaddressed one) */
	if (n < 1 || (un ? dst != 0 : dst != (1u << bus.addr))) { bus.st.other++; return; }
	if (q[0] == R_STATUS) reply_status();
	else if (q[0] == R_HELLO) reply_hello();
	else if (q[0] == R_COUNTERS) reply_counters(n > 1 && q[1]);   /* arg 1: then clear the maxima */
	else bus.st.other++;                            /* CAL_DATA: no calibration data yet */
}

/* COBS decoder: a packet ends at 0x00; after any error (and at start-up) everything up to the next 0x00 is
   skipped (bus.md 4). It runs over the bytes received before mark, in the ring itself, one contiguous span at a
   time; the state lives in locals (registers) within a span. */
static uint8_t plen, cobs_left, cobs_code = 0xFF, cobs_skip = 1;

static __attribute__((noinline)) void parse(uint16_t mark)   /* noinline: its own registers (RV32E: 16) */
{
	const uint8_t *p;
	int len;
	while ((len = hw_bus_span(mark, &p)) > 0) {
		uint8_t left = cobs_left, code = cobs_code, skip = cobs_skip, n = plen;
		for (const uint8_t *q = p, *end = p + len; q < end; ) {
			uint8_t b = *q++;
			if (b && skip) {                        /* to the next 0x00 */
				while (q < end && *q)
					q++;
				continue;
			}
			if (!b) {
				if (!skip) {
					if (left) bus.st.framing++;     /* a code group cut short */
					else if (n) packet(pkt, n);
				}
				skip = 0;
				n = left = 0;
				code = 0xFF;                        /* no implied zero before the first group */
				continue;
			}
			if (left) {
				left--;
			} else {                                /* a code byte: the previous group ended in an implied zero */
				uint8_t c = code;
				code = b;
				left = b - 1;
				if (c == 0xFF)
					continue;
				b = 0;
			}
			if (n >= PKT_MAX) {
				bus.st.framing++;
				skip = 1;
				continue;
			}
			pkt[n++] = b;
#if BUS_EARLY
			if (n == 1 && !for_me(b)) {             /* dst: for another card, skip the rest (no CRC: a damaged dst
				                                       loses the packet, as a CRC error would) */
				foreign++;
				skip = 1;
			}
#endif
		}
		cobs_left = left;
		cobs_code = code;
		cobs_skip = skip;
		plen = n;
		hw_bus_done(len);
	}
}

/* ------------------------------------------------------------------ control tick */
#define TRIM_FRAMES 100                             /* HSI measurement at start-up (bus.md 6) */
#define TRIM_STEP (TRIM_FRAMES * FRAME_CYCLES * 21 / 10000)   /* one HSITRIM step: about 0.21 % (spec.md 6) */
static uint32_t t_last, trim_t0, busy_t0;
static uint16_t trim_n, n_tick;
static uint8_t gap;                                 /* SysTick ticks since the last SYNC edge */

static void hsi_lock(uint32_t t)
{
	if (trim_n++ == 0) {
		trim_t0 = t;
		return;
	}
	if (trim_n <= TRIM_FRAMES)
		return;
	int32_t err = (int32_t)(t - trim_t0) - TRIM_FRAMES * FRAME_CYCLES;   /* > 0: HSI fast */
	int32_t steps = (err + (err < 0 ? -TRIM_STEP / 2 : TRIM_STEP / 2)) / TRIM_STEP;
	int trim = (RCC->CTLR & RCC_HSITRIM) >> 3;
	if (steps && bus.trims < 4 && trim - steps >= 0 && trim - steps <= 31) {
		RCC->CTLR = (RCC->CTLR & ~RCC_HSITRIM) | ((uint32_t)(trim - steps) << 3);
		bus.trims++;
		trim_n = 0;                                 /* measure again */
		bus.pbar = FRAME_CYCLES << 8;
		return;
	}
	bus.state = BUS_LISTEN;                         /* within half a step: listen (from the next 0x00 on) */
	cobs_skip = 1;
	hw_bus_enable(1);
}

void bus_tick(uint32_t t, int sync)
{
	uint16_t rx_mark = hw_bus_mark();               /* parse only what arrived before this tick: a slow tick (a
	                                                   reply) must not reach into the next frame's FRAME */
	bus.frame++;
	tick_sync = sync;
	if (sync) {
		uint32_t per = t - t_last;
		t_last = t;
		if (!gap && per > FRAME_CYCLES - FRAME_CYCLES / 32 && per < FRAME_CYCLES + FRAME_CYCLES / 32)
			bus.pbar += ((int32_t)(per << 8) - bus.pbar) >> 6;   /* about 64 frames */
		gap = 0;
		if (bus.state == BUS_STANDALONE) {
			bus.state = BUS_TRIM;
			trim_n = 0;
		}
		if (bus.state == BUS_TRIM)
			hsi_lock(t);
		if (bus.state == BUS_LOST) {                /* SYNC is back; FRAME corrects the counter */
			bus.state = BUS_SYNCED;
			synth_mute = 0;
		}
	} else if (bus.state != BUS_STANDALONE) {
		bus.st.sync_gaps++;
		if (++gap >= 10 && bus.state == BUS_SYNCED) {
			bus.state = BUS_LOST;
			synth_mute = 1;
		}
		if (bus.state == BUS_TRIM)
			trim_n = 0;
	}
	if (bus.state >= BUS_LISTEN) {
		if (hw_bus_rx_error())
			bus.st.uart++;
		uint32_t p0 = SysTick->CNT;
		uint16_t nb, nb0, err;
		hw_rx_stats(&nb0, &err);
		bus_reply_cycles = 0;
		parse(rx_mark);
		uint32_t pc = SysTick->CNT - p0 - bus_reply_cycles;
		hw_rx_stats(&nb, &err);
		nb -= nb0;
		parse_sum += pc;
		if (pc > parse_max)
			parse_max = pc;
		if (nb > rx_max)
			rx_max = nb;
		ev_due();
	}
	bus.st.late_ticks = dsp_late();
	hw_bus_tx_busy();                               /* BUS_TX_PP: releases the line after a reply */
	if (++n_tick == 256) {                          /* CPU load over 256 frames (render + tick) */
		uint32_t busy = hw_busy_cycles;
		bus.load = (busy - busy_t0) / (256u * FRAME_CYCLES / 100);
		busy_t0 = busy;
		parse_avg = parse_sum >> 8;
		parse_sum = 0;
		n_tick = 0;
		dsp_clock(bus.pbar);
		dac_stats_t s;
		hw_dac_stats(&s, 0);
		if (s.overruns < dac_over)
			dac_over = 0;
		bus.st.underruns += s.overruns - dac_over;
		dac_over = s.overruns;
	}
}

uint32_t bus_present(uint32_t t)
{
	return t + (uint32_t)bus.delay * (uint32_t)(bus.pbar >> 8);
}

int32_t bus_ppm(void)
{
	return ((bus.pbar - (FRAME_CYCLES << 8)) * 625) / 7680;   /* 1e6 / (48000 x 256) = 625 / 7680 */
}

void bus_init(void)
{
	bus.addr = 0xFF;
	bus.delay = 4;
	bus.lead = 2;
	bus.pbar = FRAME_CYCLES << 8;
	hw_cv_delay(bus.delay);
	for (int i = 0; i < 4; i++)
		bus.slots[i] = 0;
}

#endif
