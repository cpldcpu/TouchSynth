/* TouchSynth Poly bench controller (CH32V203 development board): an Ardulink-compatible SWIO programmer and the
 * controller side of the voice bus (docs/bus.md) for one voice card, a stand-in for the backplane's controller.
 * [2026-10-19] Load tests: up to 8 voices, voice 0 the card and 1-7 virtual (their packets go out, nobody answers),
 * with a load generator (bus.md 9.5).
 *
 * minichlink on the lab PC flashes and debugs a CH32V006 through the V203, the path the backplane will use to
 * update the voice cards:   minichlink -C ardulink -c /dev/ttyACMx -w voice.bin flash -b
 *
 *   USART1  PA9 TX, PA10 RX   115200 8N1, Ardulink: '?' sync -> '!', 'w' reg val32 -> '+', 'r' reg -> val32,
 *                             'p' / 'P' (target power, not switchable here) -> '+'; values little-endian.
 *                             Bus commands (below) share the port; the V203 never sends unasked. RX by DMA (ch5)
 *                             into a ring: the load generator runs while the main loop waits for bytes.
 *   SWIO    PB13              open drain, external pull-up: WCH one-wire debug protocol, bit-banged
 *   NRST    PB12              open drain, released (the V006 runs; not wired on the bench)
 *   SYNC    PA8               TIM1 CH1, 1 kHz square: the frame clock of the voice bus, from the 8 MHz crystal
 *                             (HSE, PLL x18: 144 MHz); the rising edge starts a frame
 *   BUS     PB10 TX, PB11 RX  USART3 at 1 Mbaud 8N1 (make BUS_BAUD=2000000: 2 Mbaud): broadcast to the cards (TX
 *                             DMA, DMA1 ch2), return line from the addressed card (RX DMA ring, DMA1 ch3; PB11
 *                             with the internal pull-up)
 *
 * Frame engine (TIM1 update interrupt = the SYNC rising edge of frame f): FRAME(f) first, then the enumeration
 * packets, the queued packets up to a budget of 95 bytes per frame (less if the interrupt came late: the last stop
 * bit must leave before the next edge), the refreshes in the room left; one DMA transfer per frame. Timed events are
 * stamped with the frame in which the cards run them: the frame of their arrival + L (bus.md 3.2). [2026-10-19] Two
 * queues: with V_PRIO, CTRL and PARAM wait in the second one, behind notes and refreshes; per packet the frame
 * counts whether it leaves too late for its execution frame ('L').
 * Enumeration (bus.md 6, one slot, address 0, NRST not wired): from 120 ms on REQUEST HELLO to address 0 (a card
 * that is already addressed answers), else ASSIGN 0 to the unaddressed card every 10 ms for up to 300 ms; then
 * CONFIG to all. Bench addition: ASSIGN to dst 0x00 every 500 ms while running, so a card reset over SWIO (no
 * NRST) is found and configured again. Refreshes: VOICE_STATE of one voice every 50 / voices frames (V_MULTI: of
 * all voices in one packet every 50), one patch slot (PATCH_PRESET) every 200 frames ('T'); a refresh never
 * overtakes a queued note.
 *
 * Bus commands on USART1 (replies are binary, little-endian):
 *   'm' n bytes        raw bytes onto the bus (sent as one unit in the next frame) -> '+' when sent
 *   'e' n bytes        MIDI messages (note on / off, program change, pitch bend, CC 1 / 7 / 11 / 71 / 74) ->
 *                      bus packets, timed for frame + L -> '+' exec_frame u16; one voice: voice 0; 'V': allocated
 *                      over the voices
 *   'b' n flags body   a packet body (dst type payload): CRC and COBS added; flags bit 7: timed, the frame byte
 *                      (frame + (flags & 0x3F)) inserted after type; bit 6: corrupt the CRC -> '+' exec_frame u16
 *   'R' what arg       REQUEST to voice 0 (bus.md 5.2), wait up to 6 frames -> n u8 + reply (src type payload),
 *                      n = 0: no reply
 *   'S'                status as one text line, '\n'-terminated
 *   'c' D L            CONFIG to all (presentation delay D, lead L) and use L -> '+'
 *   'k' mode           SYNC marker (scope): 0 off, 1 the execution frame of 'e' / 'b' events, 2 the frame that
 *                      transmits them: that frame's SYNC pulse is 0.2 ms instead of 0.5 ms (rising edges unchanged)
 *                      -> '+'
 *   'v' 0 / 1          VOICE_STATE and patch refreshes off / on -> '+'
 *   'f' n              corrupt the CRC of the next n packets made by 'e' (lost-packet test) -> '+'
 *   'n'                restart the enumeration -> '+'
 *   'g' n u16          SYNC gap test: the next n rising edges are left out (FRAME packets continue) -> '+'
 *   'V' n flags        [2026-10-19] n voices (1-8; voice 0 = the card), flags V_*: 1 parts (MIDI channel k ->
 *                      voice k, else one poly part over all), 2 reserve (the card outside the load), 4 NOTE_ON
 *                      with phase reset, 8 per-voice records (M_MULTI), 16 notes ahead of controllers; all notes
 *                      off -> '+'
 *   'T' vs pp u16 pd u16  refresh periods in frames: VOICE_STATE (0: auto), PATCH_PRESET (0: off), PATCH_DATA to the
 *                      virtual voices (8 values; 0: off) -> '+'
 *   'G' chord every u16 hold u16 ctrl cevery u16   load generator: a chord of `chord` notes every `every` frames,
 *                      released after `hold` (0: legato), controllers `ctrl` (G_*) every `cevery` frames; 0: off -> '+'
 *   'L' clear          bus load since the last clear as one text line: bytes per frame, frames at the budget, late
 *                      packets, backlog, generator lag, a histogram of bytes per frame
 *   'U' clear          [2026-10-19] USB status and counters since the last clear as one text line (usbdev.h; the
 *                      latency of USB-MIDI packets, lat_*, and of 'e' over CDC, elat_*: arrival -> execution frame
 *                      edge, arrival -> publish, us; stack_free, the reset flags)
 *   'u' n              [2026-10-19] USB D+ pull-up: 0 off (detached), 1 on, n >= 2 off for n x 10 ms, then on
 *                      (a re-plug) -> '+' (sent before the change)
 *   'Q' n bytes        [2026-10-19] USB-MIDI event packets into the USB-MIDI path as if received -> '+'
 * Pin checks: 'x' SWIO level, 'q' PB10 level, 'y' PB10 while sending 0x00, 'z' PB10 low for 4 s (these disturb the
 * bus while they run). [2026-10-19] 'X' the USB pins and the USBD pull-up (usbdev.h usb_pin_check; USB detached for
 * about 20 ms, interrupts off for up to 20 us at a time) -> one text line; 'J' '+', then a jump into the factory
 * bootloader (no return: minichlink -b).
 *
 * [2026-10-19] USB (usbdev.h): a composite of USB-MIDI and a CDC serial port; on USBFS, PB6 / PB7 (usbdev_fs.c, the
 * development board's USB-C, the default build) or USBD, PA11 / PA12 (usbdev.c, the backplane's port, make USB=usbd).
 *   USB-MIDI   OUT packets enter the MIDI -> bus path where 'e' enters: one USB packet (up to 16 events) = one
 *              command, all its events for the frame of the publish + L (running status of its own; SysEx: the
 *              universal identity request is answered on the MIDI IN endpoint, the rest is ignored)
 *   CDC        a second command port with the same commands as USART1 (the Ardulink bridge included); a command
 *              runs to its end on the port it came from, replies go back there. A command cut off by a closed
 *              port is abandoned; output to a closed port is dropped.
 * The USB interrupt has a lower priority than the frame interrupt; flow control by NAK (usb_common.h).
 *
 * [2026-10-20] USB host (make USBH=1, usbhost.h): a USB-MIDI host on USBFS (PB6 / PB7, the backplane's host port;
 * HOST_EN PB8, HOST_FLT_N PB9), the USB device then on USBD (PA11 / PA12). Root port only, full / low speed; the
 * received USB-MIDI packets enter the same MIDI -> bus path as the device's (one packet = one command, frame of the
 * publish + L, a running status of their own; SysEx only counted). All host work runs in the main loop (idle()).
 *   'H' clear          host status and counters as one text line (usbhost.h; hlat_*: host packet arrival ->
 *                      execution frame edge and -> publish, us; dlat_*: 'I' -> its arrival at the host, us)
 *   'h' op             0 port power off, 1 on, 2 re-enumerate -> '+'; 3 the D+ / D- pull-down probe (usbhost.c
 *                      usbh_pd_probe) -> one text line; 4 the device's descriptors as hex -> one text line;
 *                      5 n bytes: a USB-MIDI packet to the device's MIDI OUT endpoint -> '+' or '-'
 *   'I' n bytes        USB-MIDI event packets sent on this controller's own USB-MIDI IN endpoint (the device on
 *                      USBD; bench: PA11 / PA12 wired to PB6 / PB7, the host receives them) -> '+' or '-' (not
 *                      taken within 100 ms)
 *
 * One-wire protocol (as PicoRVD's singlewire.pio), T = 125 ns = the target's 8 MHz debug clock: every bit is a low
 * pulse of 2 T (raw 0) or 8 T (raw 1), then 3 T released. A frame is a start pulse (2 T low, 3 T released), the
 * header ((~reg) << 1 | read) as 8 bits MSB first, then 32 data bits: a write sends ~value; a read pulls the line
 * low for 1 T per bit and samples at 5 T (the target holds the line low for a 0), 11 T per bit. Then at least 18 T
 * released. minichlink itself writes the debug-module setup (DMSHDWCFGR, DMCFGR, DMCONTROL) after the sync.
 */
#include "ch32fun.h"
#include <stdio.h>
#include <string.h>
#include "usbdev.h"
#ifdef USBH
#include "usbhost.h"
#endif

#if FUNCONF_SYSTEM_CORE_CLOCK != 144000000
#error "the SWIO timing assumes HCLK = 144 MHz"
#endif

#define T        (FUNCONF_SYSTEM_CORE_CLOCK / 8000000)   /* 125 ns in SysTick (HCLK) ticks */
#define SWIO     (1u << 13)                               /* PB13 */
#define NRST     (1u << 12)                               /* PB12 */

static uint32_t t_;                                       /* running deadline: the bit timing does not accumulate jitter */

static inline uint32_t now(void) { return *(volatile uint32_t *)&SysTick->CNT; }
static inline void until(uint32_t t) { while ((int32_t)(now() - t) < 0) ; }
static inline void low_for(int n) { GPIOB->BCR = SWIO; t_ += n * T; until(t_); }
static inline void rel_for(int n) { GPIOB->BSHR = SWIO; t_ += n * T; until(t_); }

static void send_bits(uint32_t v, int n)
{
	for (int i = n - 1; i >= 0; i--) {
		low_for(((v >> i) & 1) ? 8 : 2);
		rel_for(3);
	}
}

static void frame_start(uint8_t header)
{
	t_ = now() + T;
	until(t_);
	low_for(2);                                       /* start */
	rel_for(3);
	send_bits(header, 8);
}

static void swio_write(uint8_t reg, uint32_t v)
{
	__disable_irq();
	frame_start((uint8_t)((~reg) << 1));
	send_bits(~v, 32);
	rel_for(18);
	__enable_irq();
}

static uint32_t swio_read(uint8_t reg)
{
	uint32_t v = 0;
	__disable_irq();
	frame_start((uint8_t)(((~reg) << 1) | 1));
	for (int i = 0; i < 32; i++) {
		uint32_t t0 = t_;
		GPIOB->BCR = SWIO;
		t_ = t0 + T;      until(t_);
		GPIOB->BSHR = SWIO;
		t_ = t0 + 5 * T;  until(t_);
		v = (v << 1) | ((GPIOB->INDR & SWIO) ? 1 : 0);
		t_ = t0 + 11 * T; until(t_);
	}
	rel_for(18);
	__enable_irq();
	return v;
}

static void swio_line_reset(void)                         /* about 8 us low, then idle (PicoRVD's reset) */
{
	GPIOB->BCR = SWIO;
	Delay_Us(8);
	GPIOB->BSHR = SWIO;
	Delay_Us(100);
}

static void idle(void);                                   /* the main loop's background work (load generator) */

/* [2026-10-19] USART1 RX into a DMA ring (DMA1 ch5): the main loop may be busy for a while between two bytes (the
   load generator runs while it waits for them; the USART holds only one byte, 87 us at 115200 Bd) */
#define U1R 256
static uint8_t u1_ring[U1R];
static uint8_t u1_rd;

/* [2026-10-19] Two command ports: USART1 and the USB CDC port. A command is read from and answered on the port of
   its first byte (src); a CDC command whose port closes before it is complete is abandoned (longjmp to the main
   loop: every command reads all its bytes before it changes any state). */
static uint8_t src;                                       /* 0: USART1, 1: CDC */
static void *cmd_jmp[5];                                  /* __builtin_setjmp buffer */

static int u1_avail(void) { return (uint8_t)(U1R - DMA1_Channel5->CNTR) != u1_rd; }

static int uart_getc(void)
{
	if (src) {
		int c;
		while ((c = usb_cdc_getc()) < 0) {
			if (!usb_cdc_ready())
				__builtin_longjmp(cmd_jmp, 1);
			idle();
		}
		return c;
	}
#ifdef UART_DIAG                                          /* wiring check: '#' every second, received bytes on the console */
	uint32_t t = now();
	while (!(USART1->STATR & USART_STATR_RXNE))
		if ((int32_t)(now() - t) > (int32_t)FUNCONF_SYSTEM_CORE_CLOCK) {
			USART1->DATAR = '#';
			t = now();
		}
	int c = USART1->DATAR & 0xff;
	printf("rx %02x\n", c);
	return c;
#else
	while (!u1_avail())
		idle();
	return u1_ring[u1_rd++];
#endif
}

static int next_command(void)                             /* the first byte of a command, from either port */
{
	for (;;) {
#ifndef UART_DIAG
		if (u1_avail()) {
			src = 0;
			return u1_ring[u1_rd++];
		}
#endif
		int c = usb_cdc_getc();
		if (c >= 0) {
			src = 1;
			return c;
		}
#ifdef UART_DIAG
		if (USART1->STATR & USART_STATR_RXNE) {
			src = 0;
			return uart_getc();
		}
#endif
		idle();
	}
}

static void uart_putc(int c)
{
	if (src) {                                            /* CDC: wait at most 100 ms for room (the host reads) */
		uint32_t t = now();
		while (usb_cdc_putc(c) < 0) {
			idle();
			if ((int32_t)(now() - t) > (int32_t)(FUNCONF_SYSTEM_CORE_CLOCK / 10)) {
				usb_st.cdc_drop++;
				return;
			}
		}
		return;
	}
	while (!(USART1->STATR & USART_STATR_TXE))
		idle();                                           /* a status line takes 30 ms at 115200 Bd */
	USART1->DATAR = (uint8_t)c;
}

/* ------------------------------------------------------------------ voice bus: packets (bus.md 4, 5) */
#ifndef BUS_BAUD
#define BUS_BAUD 1000000
#endif
#define BUDGET (BUS_BAUD / 10000 - 5)                     /* bytes per frame (1 Mbaud: 100 minus margin) */
enum {
	M_FRAME = 0x01, M_CONFIG = 0x02, M_ASSIGN = 0x03,
	M_NOTE_ON = 0x10, M_NOTE_OFF = 0x11, M_PITCH = 0x12, M_VOICE_STATE = 0x13,
	M_CTRL = 0x20, M_PARAM = 0x21, M_PATCH_DATA = 0x22, M_PATCH_SELECT = 0x23, M_PATCH_PRESET = 0x24,
	M_REQUEST = 0x30, M_HELLO = 0x80,
	M_MULTI = 0x40                                        /* [2026-10-19] type flag: one record per voice in dst */
};
enum { R_STATUS, R_CAL_DATA, R_HELLO, R_COUNTERS };

static uint8_t crc8(const uint8_t *p, int n)              /* polynomial 0x07, initial 0, MSB first */
{
	uint8_t c = 0;
	while (n--) {
		c ^= *p++;
		for (int i = 0; i < 8; i++)
			c = (c & 0x80) ? (uint8_t)(c << 1) ^ 0x07 : (uint8_t)(c << 1);
	}
	return c;
}

/* body (dst type [frame] payload) -> COBS(body crc8) 0x00 into out; returns the length (at most n + 3) */
static int encode(uint8_t *out, const uint8_t *body, int n, int corrupt)
{
	uint8_t c = crc8(body, n) ^ (corrupt ? 0x5A : 0);
	int o = 1, k = 0;                                     /* out[k]: distance to the next zero */
	for (int i = 0; i <= n; i++) {
		uint8_t b = i < n ? body[i] : c;
		if (b) {
			out[o++] = b;
			if (o - k < 0xFF)
				continue;
		}
		out[k] = o - k;
		k = o++;
	}
	out[k] = o - k;
	out[o++] = 0;
	return o;
}

/* a message: dst, type, execution frame (timed) or -1, payload */
static int message(uint8_t *out, uint8_t dst, uint8_t type, int frame, const uint8_t *pay, int n, int corrupt)
{
	uint8_t body[64];
	int k = 0;
	body[k++] = dst;
	body[k++] = type;
	if (frame >= 0)
		body[k++] = (uint8_t)frame;
	memcpy(body + k, pay, n);
	return encode(out, body, k + n, corrupt);
}

/* ------------------------------------------------------------------ statistics */
static struct {
	uint32_t tx_over, fifo_late, hellos, replies, rx_crc, rx_framing, rx_bytes, sent;
} st;

/* bus load ('L'): bytes per frame by origin, frames that reached the budget, timed packets sent too late */
#define HIST 11                                           /* bytes per frame in steps of 10, the last: 100 and more */
static struct {
	uint32_t frames, bytes, b_fixed, b_events, b_refresh;   /* frames sent; bytes: all, FRAME + enumeration, queued
	                                                           packets, refreshes */
	uint32_t full;                                        /* frames after which queued packets had to wait */
	uint32_t packets, late, late_card;                    /* queued packets sent; timed ones the cards parse only after
	                                                           their execution frame; of them, to the card */
	uint32_t late_hi;                                     /* of the late ones, from queue 0 (V_PRIO: notes) */
	uint32_t drops;                                       /* packets dropped: a command with too many events */
	uint32_t shortened;                                   /* frames with a smaller budget: the interrupt came late */
	uint32_t hist[HIST];
	uint16_t peak, backlog_max, late_max, lag_max;        /* bytes; queued bytes at a frame start; frames; generator:
	                                                           frames between a step and the frame of its events */
	uint16_t irq_max;                                     /* frame interrupt entry after the SYNC edge, us */
} ld;

/* ------------------------------------------------------------------ queues: main loop -> frame interrupt */
/* Units: length, flags, execution frame u16, the encoded bytes. Queue 0 carries everything, or (V_PRIO) everything
   but CTRL / PARAM, which go into queue 1; the frame drains queue 0 first. Overtaking is safe: the cards run
   events by their execution frame, and a controller value only competes with other controller values. */
#define FIFO 2048
enum { U_TIMED = 1, U_CARD = 2 };                         /* unit flags: timed, addressed to the card (voice 0) */
typedef struct { uint8_t b[FIFO]; volatile uint16_t w, r; } queue_t;
static queue_t q[2];

static int q_free(const queue_t *x) { return (x->r - x->w - 1) & (FIFO - 1); }
static int q_used(const queue_t *x) { return (x->w - x->r) & (FIFO - 1); }
static int q_empty(void) { return q[0].r == q[0].w && q[1].r == q[1].w; }

static uint16_t q_unit(queue_t *x, uint16_t w, const uint8_t *p, int n, uint8_t fl, uint16_t fx)   /* written at w,
                                                                                                 not yet published */
{
	uint8_t h[4] = { (uint8_t)n, fl, (uint8_t)fx, (uint8_t)(fx >> 8) };
	for (int i = 0; i < n + 4; i++) {
		x->b[w] = i < 4 ? h[i] : p[i - 4];
		w = (w + 1) & (FIFO - 1);
	}
	return w;
}

static void q_put(const uint8_t *p, int n, uint8_t fl, uint16_t fx)   /* main loop, queue 0; waits while full */
{
	while (q_free(&q[0]) < n + 4) ;
	q[0].w = q_unit(&q[0], q[0].w, p, n, fl, fx);
}

/* ------------------------------------------------------------------ state */
static volatile uint16_t frame;                           /* the frame that began at the last SYNC rising edge */
static uint8_t cfg_d = 4, cfg_l = 2;                      /* presentation delay D, bus lead L */
static volatile uint8_t mark_mode;
static volatile uint16_t mark_frame;
static volatile uint8_t refresh_on = 1, corrupt_n;
static volatile uint16_t gap_req, gap_left;               /* SYNC gap test: edges to leave out */
static volatile uint8_t pc_req, req_left;                 /* the PC's REQUEST is pending / frames until timeout */

/* card 0 */
enum { EN_WAIT, EN_PROBE, EN_ASSIGN, EN_RUN, EN_EMPTY };
static volatile uint8_t en_state, en_config, card, assigned;   /* assigned: an ASSIGN is outstanding */
static uint16_t en_t;
static uint8_t card_hello[11];                            /* uid 8, firmware version 2, capabilities 1 */

/* Voices (bus.md 5.1): voice 0 is the card; with 'V' n > 1 the voices 1 ... n - 1 are virtual (load tests: their
   packets go out as for real cards, nobody answers). One poly part over the voices (midi.md 2: the same note's
   voice, else the oldest released, else the oldest held one), or (V_PARTS) one mono part per voice, MIDI channel
   k -> voice k. */
#define NV 8
enum {
	V_PARTS = 1,                                          /* channel k -> voice k (8 single-voice parts) */
	V_RESERVE = 2,                                        /* the card is outside the load: no notes allocated to it, not
	                                                         in the poly part, no refresh, the generator skips it */
	V_PHASE = 4,                                          /* NOTE_ON with phase reset (latency on the scope) */
	V_MULTI = 8,                                          /* per-voice records: one packet for several voices */
	V_PRIO = 16                                           /* CTRL / PARAM in the second queue: notes go first */
};
static volatile uint8_t n_voices = 1, v_flags;
static struct { uint8_t gate, note; uint16_t pitch, age; } vc[NV];   /* the controller's view (VOICE_STATE) */
static uint16_t v_clock;
static uint8_t slot_preset[NV][4], slot_age[NV][4], slot_clock;   /* patch slots per part (poly: [0]); 0xFF: unknown */

static uint8_t vmask(int v) { return (v || card) ? 1u << v : 0xFF; }   /* no card enumerated: all (unaddressed) */
static int first_voice(void) { return (v_flags & V_RESERVE) && n_voices > 1; }

static uint8_t part_mask(void)                            /* the poly part's voices */
{
	uint8_t m = 0;
	for (int v = first_voice(); v < n_voices; v++)
		m |= vmask(v);
	return m;
}

/* ------------------------------------------------------------------ return line */
#define RXR 256
static uint8_t rx_ring[RXR];
static uint16_t rx_rd;
static uint8_t rx_pkt[64], rx_n, rx_left, rx_code = 0xFF, rx_skip;   /* the line is idle at start-up */

/* the last reply on the return line */
static uint8_t rep[64];
static volatile uint8_t rep_len, rep_seq;

static void rx_packet(void)
{
	if (rx_n < 3 || crc8(rx_pkt, rx_n)) {
		st.rx_crc++;
		return;
	}
	st.replies++;
	memcpy(rep, rx_pkt, rx_n - 1);
	rep_len = rx_n - 1;
	rep_seq++;
	if (rx_pkt[1] == M_HELLO && rx_n >= 14) {
		memcpy(card_hello, rx_pkt + 2, sizeof card_hello);
		st.hellos++;
		if (assigned || en_state != EN_RUN) {             /* a new or reset card: configure it */
			card = 1;
			en_config = 1;
			en_state = EN_RUN;
			en_t = 0;
			for (int i = 0; i < 4; i++)
				slot_preset[0][i] = 0xFF;                 /* its patch slots are unknown after a reset */
		}
		assigned = 0;
		req_left = 0;
	}
}

static void rx_poll(void)                                 /* frame interrupt: COBS frames from the RX ring */
{
	uint16_t w = (RXR - DMA1_Channel3->CNTR) & (RXR - 1);
	while (rx_rd != w) {
		uint8_t b = rx_ring[rx_rd];
		rx_rd = (rx_rd + 1) & (RXR - 1);
		st.rx_bytes++;
		if (!b) {
			if (!rx_skip) {
				if (rx_left) st.rx_framing++;
				else if (rx_n) rx_packet();
			}
			rx_skip = 0;
			rx_n = rx_left = 0;
			rx_code = 0xFF;
			continue;
		}
		if (rx_skip)
			continue;
		if (rx_left) {
			rx_left--;
		} else {
			uint8_t c = rx_code;
			rx_code = b;
			rx_left = b - 1;
			if (c == 0xFF)
				continue;
			b = 0;
		}
		if (rx_n >= sizeof rx_pkt) { st.rx_framing++; rx_skip = 1; continue; }
		rx_pkt[rx_n++] = b;
	}
}

/* ------------------------------------------------------------------ enumeration */
static int enum_step(uint8_t *o)
{
	int n = 0;
	en_t++;
	if (req_left && !--req_left)
		assigned = 0;
	if (en_config) {                                      /* after a HELLO: the system settings */
		en_config = 0;
		uint8_t p[5] = { cfg_d, cfg_l, 0, 0, 0 };
		n += message(o + n, 0xFF, M_CONFIG, -1, p, 5, 0);
	}
	if (pc_req || req_left)
		return n;
	uint8_t a = 0;
	switch (en_state) {
	case EN_WAIT:                                         /* the card needs 100 ms of SYNC for its HSI trim */
		if (en_t >= 120) {
			uint8_t p[2] = { R_HELLO, 0 };
			n += message(o + n, 0x01, M_REQUEST, -1, p, 2, 0);
			en_state = EN_PROBE;
			en_t = 0;
			req_left = 5;
		}
		break;
	case EN_PROBE:                                        /* no addressed card answered */
		en_state = EN_ASSIGN;
		en_t = 0;
		break;
	case EN_ASSIGN:
		if (en_t >= 300) {
			en_state = EN_EMPTY;
			en_t = 0;
		} else if (en_t % 10 == 1) {
			n += message(o + n, 0x00, M_ASSIGN, -1, &a, 1, 0);
			req_left = 5;
			assigned = 1;
		}
		break;
	default:                                              /* bench (no NRST): find a card that was reset (ASSIGN)
		                                                         or, while none is known, one that kept its address */
		if (en_t % 500 == 0) {
			n += message(o + n, 0x00, M_ASSIGN, -1, &a, 1, 0);
			req_left = 5;
			assigned = 1;
		} else if (en_t % 500 == 250 && en_state == EN_EMPTY) {
			uint8_t p[2] = { R_HELLO, 0 };
			n += message(o + n, 0x01, M_REQUEST, -1, p, 2, 0);
			req_left = 5;
		}
		break;
	}
	return n;
}

/* ------------------------------------------------------------------ refreshes (bus.md 5.3) */
/* They fill the room the queued packets leave (idle frames): a refresh never overtakes a queued event of the
   same voice (a VOICE_STATE ahead of a delayed NOTE_ON would "repair" the voice the wrong way). A refresh that does
   not fit waits for the next frame. */
static volatile uint8_t vs_every;                         /* frames per VOICE_STATE packet; 0: auto, 50 / voices
                                                             (one voice per packet) or 50 (V_MULTI: all in one) */
static volatile uint16_t pp_every = 200;                  /* frames per PATCH_PRESET (a patch slot), 0 = off */
static volatile uint16_t pd_every;                        /* frames per PATCH_DATA (8 values) to the virtual voices
                                                             (load emulation; the card does not take it yet), 0 = off */
static uint16_t rf_t;
static uint8_t vs_due, pp_due, pd_due, vs_next, pp_next, pd_next, pd_off;

static void refresh_due(void)                             /* frame interrupt: the periods */
{
	if (!refresh_on || en_state < EN_RUN)
		return;
	int nv = n_voices - first_voice();
	int vs = vs_every ? vs_every : (v_flags & V_MULTI) && nv > 1 ? 50 : 50 / nv;
	rf_t++;
	if (rf_t % vs == 0)
		vs_due = 1;
	if (pp_every && rf_t % pp_every == pp_every / 2)
		pp_due = 1;
	if (pd_every && rf_t % pd_every == 0 && n_voices > 1)
		pd_due = 1;
}

static int refresh_step(uint8_t *o, uint16_t f, int room)   /* frame interrupt: the due refreshes that fit */
{
	int n = 0, k, v0 = first_voice(), parts = v_flags & V_PARTS;
	uint8_t t[64];
	uint16_t fx = f + cfg_l;
	if (!refresh_on || en_state < EN_RUN)
		return 0;
	if (vs_due) {                                         /* repairs a lost NOTE_ON / NOTE_OFF (bus.md 5.1) */
		uint8_t p[3 * NV], m = 0, nx = vs_next;
		int j = 0;
		if ((v_flags & V_MULTI) && card && n_voices - v0 > 1) {
			for (int v = v0; v < n_voices; v++) {
				p[j++] = vc[v].gate;
				p[j++] = (uint8_t)vc[v].pitch;
				p[j++] = (uint8_t)(vc[v].pitch >> 8);
				m |= 1u << v;
			}
			k = message(t, m, M_VOICE_STATE | M_MULTI, fx, p, j, 0);
		} else {
			int v = nx < v0 || nx >= n_voices ? v0 : nx;
			p[0] = vc[v].gate;
			p[1] = (uint8_t)vc[v].pitch;
			p[2] = (uint8_t)(vc[v].pitch >> 8);
			k = message(t, vmask(v), M_VOICE_STATE, fx, p, 3, 0);
			nx = v + 1;
		}
		if (k <= room - n) {
			memcpy(o + n, t, k);
			n += k;
			vs_due = 0;
			vs_next = nx;
		}
	}
	if (pp_due) {                                         /* patch slots, round robin (per part) */
		int tables = parts ? n_voices : 1, total = tables * 4, i;
		for (i = 0; i < total; i++) {
			int x = (pp_next + i) % total, tb = x / 4, s = x % 4;
			if ((parts && tb < v0) || slot_preset[tb][s] == 0xFF)
				continue;
			uint8_t p[2] = { (uint8_t)s, slot_preset[tb][s] };
			k = message(t, parts ? vmask(tb) : part_mask(), M_PATCH_PRESET, -1, p, 2, 0);
			if (k <= room - n) {
				memcpy(o + n, t, k);
				n += k;
				pp_due = 0;
				pp_next = x + 1;
			}
			break;
		}
		if (i == total)
			pp_due = 0;
	}
	if (pd_due) {                                         /* a slow resend of the patch (8 of its 64 values) */
		int v = pd_next < 1 || pd_next >= n_voices ? 1 : pd_next;
		uint8_t m = parts ? 1u << v : part_mask() & ~1u & 0xFF;
		uint8_t p[3 + 16] = { 0, pd_off, 8 };
		for (int i = 0; i < 16; i++)
			p[3 + i] = (uint8_t)(pd_off * 2 + i + 1);
		k = message(t, m, M_PATCH_DATA, -1, p, sizeof p, 0);
		if (m && k <= room - n) {
			memcpy(o + n, t, k);
			n += k;
			pd_due = 0;
			if (!parts || (pd_next = v + 1) >= n_voices) {
				pd_next = 1;
				pd_off = (pd_off + 8) & 63;
			}
		} else if (!m) {
			pd_due = 0;
		}
	}
	return n;
}

/* ------------------------------------------------------------------ frame interrupt */
#define MARK_W 200                                        /* marker pulse, us (normal: 500) */
static uint8_t fbuf[BUDGET + 100];

static int drain(queue_t *x, int n, int first, int budget, uint16_t f)   /* units from x into fbuf up to budget */
{
	while (x->r != x->w) {
		uint16_t r = x->r;
		int len = x->b[r];
		if ((n + len > budget && n > first) || n + len > (int)sizeof fbuf)
			break;                                        /* next frame (an oversized unit goes out alone) */
		uint8_t fl = x->b[(r + 1) & (FIFO - 1)];
		if (fl & U_TIMED) {                               /* sent in frame f: the cards parse it at tick f + 1 */
			uint16_t fx = x->b[(r + 2) & (FIFO - 1)] | x->b[(r + 3) & (FIFO - 1)] << 8;
			int16_t late = (int16_t)((uint16_t)(f + 1) - fx);
			if (late > 0) {
				ld.late++;
				if (x == &q[0])
					ld.late_hi++;
				if (fl & U_CARD)
					ld.late_card++;
				if (late > (int16_t)ld.late_max)
					ld.late_max = late;
			}
		}
		r = (r + 4) & (FIFO - 1);
		for (int i = 0; i < len; i++) {
			fbuf[n++] = x->b[r];
			r = (r + 1) & (FIFO - 1);
		}
		x->r = r;
		st.sent++;
		ld.packets++;
	}
	return n;
}

void TIM1_UP_IRQHandler(void) __attribute__((interrupt));
void TIM1_UP_IRQHandler(void)
{
	uint16_t lat = TIM1->CNT;                             /* us since the SYNC edge */
	TIM1->INTFR = (uint16_t)~TIM_UIF;
	uint16_t f = ++frame;
	if (lat > ld.irq_max && lat < 500)
		ld.irq_max = lat;
	TIM1->CH1CVR = (mark_mode == 1 && (uint16_t)(f + 1) == mark_frame) ? MARK_W : 500;   /* preload: frame f + 1 */
	if (gap_req) {                                        /* SYNC low from now on: the next gap_req edges are missing */
		TIM1->CHCTLR1 = TIM_OC1M_2 | TIM_OC1PE;           /* OC1M = 100: forced inactive */
		gap_left = gap_req + 1;
		gap_req = 0;
	} else if (gap_left && !--gap_left) {
		TIM1->CHCTLR1 = TIM_OC1M_2 | TIM_OC1M_1 | TIM_OC1PE;   /* PWM mode 1 again: the edge comes ~2 us late */
	}
	rx_poll();
	refresh_due();
	if (DMA1_Channel2->CNTR) {                            /* the last frame's bytes are still going out */
		st.tx_over++;
		return;
	}
	uint16_t used = q_used(&q[0]) + q_used(&q[1]);
	if (used > ld.backlog_max)
		ld.backlog_max = used;
	int budget = BUDGET, lim = (990 - (int)TIM1->CNT) * (BUS_BAUD / 100000) / 100;   /* the last stop bit before the
	                                                                                    next edge (the cards' mark) */
	if (lim < budget) {
		budget = lim;
		ld.shortened++;
	}
	int n = 0;
	uint8_t p[2] = { (uint8_t)f, (uint8_t)(f >> 8) };
	n += message(fbuf, 0xFF, M_FRAME, -1, p, 2, 0);
	n += enum_step(fbuf + n);
	int first = n, rf = 0;
	n = drain(&q[0], n, first, budget, f);
	if (q[0].r == q[0].w)                                 /* no note waits: a refresh cannot overtake one */
		n += rf = refresh_step(fbuf + n, f, budget - n);
	n = drain(&q[1], n, first, budget, f);
	int ev = n - first - rf;
	if (!q_empty())
		ld.full++;
	ld.frames++;
	ld.bytes += n;
	ld.b_fixed += first;
	ld.b_events += ev;
	ld.b_refresh += n - first - ev;
	if (n > ld.peak)
		ld.peak = n;
	ld.hist[n / 10 < HIST ? n / 10 : HIST - 1]++;
	DMA1_Channel2->CFGR &= ~DMA_CFGR1_EN;
	DMA1_Channel2->MADDR = (uint32_t)fbuf;
	DMA1_Channel2->CNTR = n;
	DMA1_Channel2->CFGR |= DMA_CFGR1_EN;
}

/* ------------------------------------------------------------------ main loop: events */
static void flush(void);

/* The events of one command (events_begin ... events_end) are staged as packet bodies with their lead, then encoded
   into the queues behind their write pointers and published at once, stamped with the frame read just before: all
   of them go out in the next frame (bus.md 3.2: the frame of their arrival + L; with V_PRIO the controllers may
   wait). If a frame begins while they are encoded, they are encoded again for the next one. Interrupts are off only
   for that check and the publish, so the frame interrupt (the TX DMA start) is never held off. [2026-10-19] Before,
   the whole encoding ran with interrupts off: a large command delayed the frame interrupt, its last bytes missed the
   next SYNC edge (tx_over: a lost frame). */
#define STG 768                                           /* staged units: length, flags, lead, dst, type, payload;
                                                             encoded at most twice that, always fits the queue */
enum { S_TIMED = 1, S_CORRUPT = 2, S_LOW = 4 };          /* S_LOW: queue 1 */
static uint8_t stg[STG], staging;
static uint16_t stg_n, stg_q[2];                          /* staged bytes, per queue */

static void mark(uint16_t fx);

static void events_begin(void)
{
	staging = 1;
	stg_n = stg_q[0] = stg_q[1] = 0;
}

static uint16_t events_end(int mk)                        /* returns the frame of the publish; mk >= 0: SYNC marker
                                                             for that frame + mk */
{
	flush();
	staging = 0;
	while (q_free(&q[0]) < 2 * stg_q[0] + 4 || q_free(&q[1]) < 2 * stg_q[1] + 4) ;
	for (;;) {
		uint16_t f0 = frame, w[2] = { q[0].w, q[1].w };
		for (int i = 0; i < stg_n; i += 5 + stg[i]) {
			const uint8_t *u = stg + i;
			uint8_t out[80];
			uint16_t fx = f0 + u[2];
			int k = message(out, u[3], u[4], (u[1] & S_TIMED) ? fx : -1, u + 5, u[0], u[1] & S_CORRUPT);
			int c = (u[1] & S_LOW) ? 1 : 0;
			w[c] = q_unit(&q[c], w[c], out, k, ((u[1] & S_TIMED) ? U_TIMED : 0) | ((u[3] & 1) ? U_CARD : 0), fx);
		}
		__disable_irq();
		if (frame == f0) {
			if (q_used(&q[0]) + q_used(&q[1]) > 2 * BUDGET)   /* a backlog of more than two frames: late */
				st.fifo_late++;
			q[0].w = w[0];
			q[1].w = w[1];
			if (mk >= 0)
				mark(f0 + mk);
			__enable_irq();
			return f0;
		}
		__enable_irq();
	}
}

/* a packet: lead = frames after the publish (timed), -1 = untimed; outside a command: queued at once */
static void put(uint8_t dst, uint8_t type, int lead, const uint8_t *pay, int n, int corrupt)
{
	if (staging) {
		if (stg_n + 5 + n > STG) {
			ld.drops++;
			return;
		}
		uint8_t t = type & ~M_MULTI;
		int low = (v_flags & V_PRIO) && (t == M_CTRL || t == M_PARAM);
		uint8_t *u = stg + stg_n;
		u[0] = n;
		u[1] = (lead >= 0 ? S_TIMED : 0) | (corrupt ? S_CORRUPT : 0) | (low ? S_LOW : 0);
		u[2] = lead < 0 ? 0 : lead;
		u[3] = dst;
		u[4] = type;
		memcpy(u + 5, pay, n);
		stg_n += 5 + n;
		stg_q[low] += 5 + n;
		return;
	}
	uint8_t out[80];
	uint16_t fx = frame + (lead < 0 ? 0 : lead);
	q_put(out, message(out, dst, type, lead >= 0 ? fx : -1, pay, n, corrupt),
	      ((lead >= 0) ? U_TIMED : 0) | ((dst & 1) ? U_CARD : 0), fx);
}

static void mark(uint16_t fx)
{
	if (mark_mode == 1) {
		mark_frame = fx;
	} else if (mark_mode == 2) {                          /* the next frame transmits: its preload is set now */
		TIM1->CH1CVR = MARK_W;
	}
}

static int take_corrupt(void)
{
	if (!corrupt_n)
		return 0;
	corrupt_n--;
	return 1;
}

/* V_MULTI: the events of one command for several voices are staged and sent together at its end: one voice -> the
   plain message; several with equal payloads -> the plain message to all of them (the bitmask); else one packet
   with a record per voice (type | M_MULTI, bus.md 5.1). A voice's second note event in a command flushes first,
   and so does every other message, so the order of the events per voice is kept. */
#define CPS 6                                             /* CTRL / PARAM IDs staged at a time */
static struct {
	uint8_t on, off;                                      /* voices with a staged NOTE_ON / NOTE_OFF */
	uint8_t on_p[NV][4], off_v[NV];
	uint8_t n_cp, lead;
	struct { uint8_t type, id, mask; int16_t v[NV]; } cp[CPS];
} sg;

static void flush_group(uint8_t type, uint8_t mask, const uint8_t *pre, int npre, const uint8_t *rec, int len)
{
	uint8_t p[1 + 4 * NV];
	int k = npre, first = -1, same = 1;
	memcpy(p, pre, npre);
	for (int v = 0; v < NV; v++) {
		if (!((mask >> v) & 1))
			continue;
		if (first < 0)
			first = v;
		else if (memcmp(rec + v * len, rec + first * len, len))
			same = 0;
		memcpy(p + k, rec + v * len, len);
		k += len;
	}
	if (same)
		put(mask, type, sg.lead, p, npre + len, 0);
	else
		put(mask, type | M_MULTI, sg.lead, p, k, 0);
}

static void flush(void)
{
	if (sg.off)
		flush_group(M_NOTE_OFF, sg.off, 0, 0, sg.off_v, 1);
	if (sg.on)
		flush_group(M_NOTE_ON, sg.on, 0, 0, &sg.on_p[0][0], 4);
	for (int i = 0; i < sg.n_cp; i++)
		flush_group(sg.cp[i].type, sg.cp[i].mask, &sg.cp[i].id, 1, (const uint8_t *)sg.cp[i].v, 2);
	sg.on = sg.off = sg.n_cp = 0;
}

static void voice_put(uint8_t type, int v, const uint8_t *pay, int n, uint8_t lead, int corrupt)   /* NOTE_ON / OFF */
{
	if (!(v_flags & V_MULTI) || corrupt || !card) {
		flush();
		put(vmask(v), type, lead, pay, n, corrupt);
		return;
	}
	if (((sg.on | sg.off) >> v) & 1)
		flush();
	sg.lead = lead;
	if (type == M_NOTE_ON) {
		sg.on |= 1u << v;
		memcpy(sg.on_p[v], pay, 4);
	} else {
		sg.off |= 1u << v;
		sg.off_v[v] = pay[0];
	}
}

/* CTRL / PARAM: v < 0: to the poly part (dst, one packet); else to voice v alone (V_PARTS: stageable) */
static void ctrl_put(uint8_t type, uint8_t dst, int v, uint8_t id, int16_t val, uint8_t lead)
{
	if (v < 0 || !(v_flags & V_MULTI) || !card) {
		flush();
		uint8_t p[3] = { id, (uint8_t)val, (uint8_t)((uint16_t)val >> 8) };
		put(dst, type, lead, p, 3, 0);
		return;
	}
	int i;
	for (i = 0; i < sg.n_cp; i++)
		if (sg.cp[i].type == type && sg.cp[i].id == id)
			break;
	if (i == sg.n_cp) {
		if (sg.n_cp == CPS)
			flush();
		i = sg.n_cp++;
		sg.cp[i].type = type;
		sg.cp[i].id = id;
		sg.cp[i].mask = 0;
	}
	sg.lead = lead;
	sg.cp[i].mask |= 1u << v;
	sg.cp[i].v[v] = val;
}

static void program(int tb, uint8_t dst, uint8_t prog, uint8_t lead)   /* program change: a slot, PATCH_SELECT */
{
	flush();
	int s = -1;
	for (int i = 0; i < 4; i++)
		if (slot_preset[tb][i] == prog)
			s = i;
	if (s < 0) {                                          /* not on the card: into the least recently used slot */
		s = 0;
		for (int i = 1; i < 4; i++)
			if ((uint8_t)(slot_clock - slot_age[tb][i]) > (uint8_t)(slot_clock - slot_age[tb][s]))
				s = i;
		slot_preset[tb][s] = prog;
		uint8_t p[2] = { (uint8_t)s, prog };
		put(dst, M_PATCH_PRESET, -1, p, 2, 0);
	}
	slot_age[tb][s] = ++slot_clock;
	uint8_t p[1] = { (uint8_t)s };
	put(dst, M_PATCH_SELECT, lead, p, 1, 0);
}

static int alloc(uint8_t note)                            /* poly part: a voice for a note (midi.md 2) */
{
	int best = -1;
	for (int v = first_voice(); v < n_voices; v++) {
		if (vc[v].gate && vc[v].note == note)
			return v;                                     /* the same note again: its voice */
		if (best < 0 || vc[v].gate < vc[best].gate ||
		    (vc[v].gate == vc[best].gate && (uint16_t)(v_clock - vc[v].age) > (uint16_t)(v_clock - vc[best].age)))
			best = v;                                     /* released before held, the oldest first */
	}
	return best;
}

/* one MIDI message -> bus events, timed for the frame of the publish + lead */
static void midi_msg(uint8_t status, const uint8_t *d, uint8_t lead)
{
	uint8_t ty = status & 0xF0, ch = status & 0x0F;
	int parts = v_flags & V_PARTS, v = -1;
	if (parts && ch >= n_voices)
		return;
	uint8_t pm = parts ? vmask(ch) : part_mask();         /* the part's voices */
	int pv = parts ? ch : -1;
	if (ty == 0x90 && d[1]) {
		v = parts ? ch : alloc(d[0]);
		if (v < 0)
			return;
		vc[v].gate = 1;
		vc[v].note = d[0];
		vc[v].pitch = (uint16_t)d[0] << 8;
		vc[v].age = ++v_clock;
		uint8_t p[4] = { 0, d[0], d[1], (v_flags & V_PHASE) ? 2 : 0 };   /* pitch u16 = note x 256, velocity, flags */
		voice_put(M_NOTE_ON, v, p, 4, lead, take_corrupt());
	} else if (ty == 0x80 || ty == 0x90) {
		for (int k = parts ? ch : 0; k < (parts ? ch + 1 : n_voices); k++)
			if (vc[k].gate && vc[k].note == d[0])
				v = k;                                    /* only the voice holding this note releases */
		if (v < 0)
			return;
		vc[v].gate = 0;
		vc[v].age = ++v_clock;
		uint8_t p[1] = { d[1] };
		voice_put(M_NOTE_OFF, v, p, 1, lead, take_corrupt());
	} else if (ty == 0xC0) {
		program(parts ? ch : 0, pm, d[0], lead);
	} else if (ty == 0xE0) {
		ctrl_put(M_CTRL, pm, pv, 0, (int16_t)(((d[1] << 7) | d[0]) - 8192), lead);
	} else if (ty == 0xB0) {
		if (d[0] == 1) ctrl_put(M_CTRL, pm, pv, 1, d[1] * 129, lead);
		else if (d[0] == 11) ctrl_put(M_CTRL, pm, pv, 3, d[1] * 129, lead);
		else if (d[0] == 7) ctrl_put(M_PARAM, pm, pv, 47, d[1], lead);
		else if (d[0] == 71) ctrl_put(M_PARAM, pm, pv, 33, d[1] * 2, lead);
		else if (d[0] == 74) ctrl_put(M_PARAM, pm, pv, 32, d[1] * 20, lead);
	}
}

/* MIDI bytes -> bus events, all for one execution frame (running status per source) */
typedef struct { uint8_t status, k, d[2]; } midi_in_t;
static midi_in_t pc_in, gen_in;                           /* the PC's 'e', the load generator */

static void midi_events(midi_in_t *in, const uint8_t *m, int n, uint8_t lead)
{
	for (int i = 0; i < n; i++) {
		uint8_t b = m[i];
		if (b >= 0xF8) continue;
		if (b & 0x80) { in->status = b; in->k = 0; continue; }
		in->d[in->k++] = b;
		uint8_t ty = in->status & 0xF0;
		if (in->k < ((ty == 0xC0 || ty == 0xD0) ? 1 : 2)) continue;
		in->k = 0;
		midi_msg(in->status, in->d, lead);
	}
}

/* ------------------------------------------------------------------ load generator ('G', main loop) */
/* Every `every` frames a chord of `chord` notes (released after `hold` frames; hold 0 or >= every: legato, the
   release in the same command as the next chord), every `cevery` frames a step of the controllers in `ctrl`
   (G_*; V_PARTS: on every part's channel, each at its own phase). The steps run as MIDI through midi_events, at
   the frame they are due or as soon as the main loop gets there (lag_max). */
enum { G_BEND = 1, G_WHEEL = 2, G_CUTOFF = 4, G_RES = 8, G_EXPR = 16, G_VOL = 32 };
static const uint8_t chord_iv[NV] = { 0, 4, 7, 11, 12, 16, 19, 23 };   /* a major seventh chord over two octaves */
static struct {
	uint8_t chord, ctrl, held, k;                         /* held: notes of the last chord still on */
	uint16_t every, hold, cevery, t, next;                /* next: the frame of the next step */
	uint8_t note[NV], ch[NV];
	volatile uint8_t on;
} gen;

static uint8_t tri7(unsigned x) { x &= 0xFF; return x & 0x80 ? 255 - x : x; }   /* 0 ... 127 ... 0 */

static void gen_release(uint8_t *m, int *k)
{
	for (int i = 0; i < gen.held; i++) {
		m[(*k)++] = 0x80 | gen.ch[i];
		m[(*k)++] = gen.note[i];
		m[(*k)++] = 0;
	}
	gen.held = 0;
}

static void gen_step(uint16_t f)
{
	uint8_t m[200];
	int k = 0, parts = v_flags & V_PARTS;
	int c0 = parts ? first_voice() : 0, c1 = parts ? n_voices : 1;   /* MIDI channels: the parts */
	uint16_t t = gen.t++;
	if (gen.chord && gen.every) {
		uint16_t ph = t % gen.every;
		int legato = !gen.hold || gen.hold >= gen.every;
		if (gen.held && ph == (legato ? 0 : gen.hold))
			gen_release(m, &k);
		if (ph == 0) {
			uint8_t root = 36 + (gen.k++ * 5) % 12;
			for (int i = 0; i < gen.chord; i++) {
				gen.ch[i] = c0 + i % (c1 - c0);
				gen.note[i] = root + chord_iv[i];
				m[k++] = 0x90 | gen.ch[i];
				m[k++] = gen.note[i];
				m[k++] = 100 - 4 * i;
			}
			gen.held = gen.chord;
		}
	}
	if (gen.ctrl && gen.cevery && t % gen.cevery == gen.cevery / 2) {
		unsigned s = t / gen.cevery * 4;
		for (int c = c0; c < c1; c++) {
			unsigned x = s + c * 16;
			uint8_t cc[5][2] = { { 1, tri7(x + 40) }, { 74, tri7(x + 80) }, { 71, tri7(x + 120) / 2 },
			                     { 11, 64 + tri7(x) / 2 }, { 7, 90 + tri7(x) / 4 } };
			if (gen.ctrl & G_BEND) {
				unsigned b = tri7(x) << 7 | (x & 0x7F);
				m[k++] = 0xE0 | c;
				m[k++] = b & 0x7F;
				m[k++] = b >> 7;
			}
			for (int j = 0; j < 5; j++)
				if (gen.ctrl & (G_WHEEL << j)) {
					m[k++] = 0xB0 | c;
					m[k++] = cc[j][0];
					m[k++] = cc[j][1];
				}
		}
	}
	if (!k)
		return;
	events_begin();
	midi_events(&gen_in, m, k, cfg_l);
	uint16_t lag = events_end(-1) - f;
	if (lag > ld.lag_max)
		ld.lag_max = lag;
}

static void gen_poll(void)                                /* main loop: the steps due (a few per call: the commands
                                                             still get through when the bus cannot keep up) */
{
	for (int i = 0; i < 4 && gen.on && (int16_t)(frame - gen.next) >= 0; i++) {
		if ((int16_t)(frame - gen.next) > 100)            /* far behind (a long command): skip */
			gen.next = frame;
		gen_step(gen.next++);
	}
}

/* ------------------------------------------------------------------ USB-MIDI (main loop) */
/* [2026-10-19] One USB packet = one command, as 'e': its events go through midi_events for the frame of the publish
   + L. The interrupt stamps each packet on arrival (frame, us since its SYNC edge); per packet the time to the
   publish and to the edge of the execution frame (the note then sounds D frames later, bus.md 3.1). */
static midi_in_t usb_in;
static const uint8_t cin_len[16] = { 0, 0, 2, 3, 3, 1, 2, 3, 3, 3, 3, 3, 2, 2, 3, 1 };   /* bytes per code index */
typedef struct {
	uint32_t n, lat_sum, proc_sum;
	uint16_t lat_min, lat_max, proc_max;                  /* us */
} lat_t;
typedef struct {
	uint32_t pkts, events, sysex, ident, ident_lost;
} um_t;
static um_t um;
static lat_t lm = { .lat_min = 0xFFFF }, le = { .lat_min = 0xFFFF };   /* USB-MIDI packets; 'e' commands over CDC */
#ifdef USBH
static um_t hm;                                           /* [2026-10-20] packets from the USB host port */
static midi_in_t uh_in;
static lat_t lh = { .lat_min = 0xFFFF }, ldh = { .lat_min = 0xFFFF };   /* host packets; 'I' -> host arrival */
static uint32_t i_stamp;                                  /* usb_stamp() of the last 'I' not yet seen at the host */
static uint8_t i_pending;
#endif
static uint8_t sx[8];
static uint16_t sx_n;

/* the arrival (usb_stamp) of events published in frame f0 for f0 + L: to the publish, to the execution frame edge */
static void lat_add(lat_t *l, uint32_t stamp, uint16_t f0)
{
	uint32_t t = usb_stamp();
	uint16_t fa = stamp >> 16, ua = stamp & 0xFFFF;
	int32_t lat = (int32_t)(uint16_t)(f0 + cfg_l - fa) * 1000 - ua;
	int32_t proc = (int32_t)(uint16_t)((t >> 16) - fa) * 1000 + (int32_t)(t & 0xFFFF) - ua;
	if (lat < 0 || lat > 60000 || proc < 0 || proc > 60000)
		return;
	l->n++;
	l->lat_sum += lat;
	l->proc_sum += proc;
	if (lat < l->lat_min) l->lat_min = lat;
	if (lat > l->lat_max) l->lat_max = lat;
	if (proc > l->proc_max) l->proc_max = proc;
}

uint32_t usb_stamp(void)                                  /* USB interrupt: frame << 16 | us since its SYNC edge */
{
	uint16_t us = TIM1->CNT, f = frame;
	if ((TIM1->INTFR & TIM_UIF) && us < 500)              /* the edge has passed, the frame interrupt is pending */
		f++;
	return (uint32_t)f << 16 | us;
}

static void usb_sysex(const uint8_t *b, int n)            /* the universal identity request: F0 7E id 06 01 F7 */
{
	for (int i = 0; i < n; i++) {
		if (b[i] == 0xF0)
			sx_n = 0;
		if (sx_n < sizeof sx)
			sx[sx_n] = b[i];
		sx_n++;
		if (b[i] != 0xF7)
			continue;
		um.sysex++;
		if (sx_n == 6 && sx[0] == 0xF0 && sx[1] == 0x7E && sx[3] == 0x06 && sx[4] == 0x01) {
			/* F0 7E 00 06 02, ID 7D (non-commercial), family 00 00, member 00 00, version 00 01 00 00, F7 */
			static const uint8_t p[20] = { 0x04, 0xF0, 0x7E, 0x00, 0x04, 0x06, 0x02, 0x7D, 0x04, 0x00, 0x00, 0x00,
			                               0x04, 0x00, 0x00, 0x01, 0x07, 0x00, 0x00, 0xF7 };
			if (usb_midi_send(p, sizeof p) == 0)
				um.ident++;
			else
				um.ident_lost++;                          /* the IN endpoint is busy: no program reads */
		}
		sx_n = 0;
	}
}

/* [2026-10-20] one USB-MIDI packet (n bytes of 4-byte events) -> midi_events, all for the frame of the publish + L;
   sysex: SysEx goes to usb_sysex (the device's packets: identity requests are answered), else it is only counted
   (the host port's packets) */
static void midi_packet(um_t *u, midi_in_t *in, lat_t *l, const uint8_t *p, int n, uint32_t stamp, int sysex)
{
	uint8_t m[48];
	int k = 0;
	u->pkts++;
	for (int i = 0; i + 4 <= n; i += 4) {
		uint8_t cin = p[i] & 0x0F, len = cin_len[cin];
		if (!len)
			continue;
		u->events++;
		if (cin >= 0x4 && cin <= 0x7 && (cin != 0x5 || p[i + 1] == 0xF7 || (sysex && sx_n))) {
			if (sysex)
				usb_sysex(p + i + 1, len);
			else if (cin != 0x4)
				u->sysex++;
			continue;
		}
		memcpy(m + k, p + i + 1, len);
		k += len;
	}
	if (!k)
		return;
	events_begin();
	midi_events(in, m, k, cfg_l);
	lat_add(l, stamp, events_end(cfg_l));
}

static void usb_midi_poll(void)
{
	uint8_t p[64];
	uint32_t stamp;
	int n = usb_midi_get(p, &stamp);
	if (n)
		midi_packet(&um, &usb_in, &lm, p, n, stamp, 1);
#ifdef USBH
	n = usbh_midi_get(p, &stamp);
	if (!n)
		return;
	if (i_pending) {                                      /* 'I' (the device on USBD) -> arrival at the host */
		int32_t d = (int32_t)(uint16_t)((stamp >> 16) - (i_stamp >> 16)) * 1000 + (int32_t)(stamp & 0xFFFF) -
		            (int32_t)(i_stamp & 0xFFFF);
		i_pending = 0;
		if (d >= 0 && d < 60000) {
			ldh.n++;
			ldh.lat_sum += d;
			if (d < ldh.lat_min) ldh.lat_min = d;
			if (d > ldh.lat_max) ldh.lat_max = d;
		}
	}
	midi_packet(&hm, &uh_in, &lh, p, n, stamp, 0);
#endif
}

static void idle(void)
{
	gen_poll();
#ifdef USBH
	usbh_poll();
#endif
	usb_midi_poll();
	usb_poll();
}

/* ------------------------------------------------------------------ main loop: bus commands */
static void reply16(uint16_t v)
{
	uart_putc('+');
	uart_putc(v & 0xff);
	uart_putc(v >> 8);
}

static void wait_sent(void)                               /* until the queue is empty and the last byte is out */
{
	while (!q_empty()) ;
	uint16_t f = frame;
	while (frame == f) ;                                  /* the frame interrupt has started the DMA */
	while (DMA1_Channel2->CNTR) ;
	while (!(USART3->STATR & USART_STATR_TC)) ;
}

static void put_line(const char *s, int n)
{
	for (int i = 0; i < n; i++)
		uart_putc(s[i]);
}

static __attribute__((noinline)) void status_line(void)
{
	char s[320];
	const uint8_t *h = card_hello;
	int n = snprintf(s, sizeof s, "frame %u enum %u card %u uid %02x%02x%02x%02x-%02x%02x%02x%02x fw %u caps %u "
	                 "D %u L %u tx_over %lu fifo_late %lu sent %lu rx %lu replies %lu rx_crc %lu rx_framing %lu "
	                 "hellos %lu voices %u vflags %u gen %u\n", frame, en_state, card, h[3], h[2], h[1], h[0], h[7],
	                 h[6], h[5], h[4], h[8] | h[9] << 8, h[10], cfg_d, cfg_l, st.tx_over, st.fifo_late, st.sent,
	                 st.rx_bytes, st.replies, st.rx_crc, st.rx_framing, st.hellos, n_voices, v_flags, gen.on);
	put_line(s, n);
}

static __attribute__((noinline)) void load_line(int clear)
{
	char s[400];
	__disable_irq();
	typeof(ld) l = ld;
	uint32_t tx_over = st.tx_over, fifo_late = st.fifo_late;
	if (clear)
		memset(&ld, 0, sizeof ld);
	__enable_irq();
	int n = snprintf(s, sizeof s, "frames %lu bytes %lu fixed %lu events %lu refresh %lu peak %u full %lu packets %lu "
	                 "late %lu late_hi %lu late_card %lu late_max %u backlog_max %u lag_max %u drops %lu tx_over %lu "
	                 "fifo_late %lu budget %u irq_max %u shortened %lu hist", l.frames, l.bytes, l.b_fixed, l.b_events,
	                 l.b_refresh, l.peak, l.full, l.packets, l.late, l.late_hi, l.late_card, l.late_max, l.backlog_max,
	                 l.lag_max, l.drops, tx_over, fifo_late, BUDGET, l.irq_max, l.shortened);
	for (int i = 0; i < HIST; i++)
		n += snprintf(s + n, sizeof s - n, "%c%lu", i ? ',' : ' ', l.hist[i]);
	s[n++] = '\n';
	put_line(s, n);
}

static unsigned stack_free(void);
static uint32_t rst_flags;

static __attribute__((noinline)) void usb_line(int clear)   /* [2026-10-19] 'U' */
{
	char s[336];
	const usb_stats_t *u = &usb_st;
	int lv = usb_levels();
	int n = snprintf(s, sizeof s, "usb port %s conf %u dtr %u addr %u pullup %u dp %u dm %u dp_boot %u resets %lu "
	                 "suspends %lu resumes %lu setups %lu stalls %lu errors %lu midi_pkts %lu midi_bytes %lu "
	                 "midi_held %lu midi_in %lu cdc_rx %lu cdc_tx %lu cdc_held %lu cdc_drop %lu ", usb_port_name,
	                 u->configured, u->dtr, u->addr, u->pullup, (lv >> 1) & 1, lv & 1, u->dp_boot, u->resets,
	                 u->suspends, u->resumes, u->setups, u->stalls, u->errors, u->midi_pkts, u->midi_bytes,
	                 u->midi_held, u->midi_in_pkts, u->cdc_rx, u->cdc_tx, u->cdc_held, u->cdc_drop);
	put_line(s, n);
	uint32_t isr_cfg;
	asm volatile("csrr %0, 0x804" : "=r"(isr_cfg));                /* INTSYSCR: nesting, hardware stack */
	n = snprintf(s, sizeof s, "packets %lu events %lu sysex %lu ident %lu ident_lost %lu stack_free %u rst %08lx "
	             "intsyscr %lx", um.pkts, um.events, um.sysex, um.ident, um.ident_lost, stack_free(), rst_flags,
	             isr_cfg);
	put_line(s, n);
	for (int i = 0; i < 2; i++) {                         /* latency: USB-MIDI packets (lat_), 'e' over CDC (elat_) */
		lat_t *l = i ? &le : &lm;
		const char *p = i ? "elat" : "lat";
		n = snprintf(s, sizeof s, " %s_n %lu %s_min %u %s_max %u %s_mean %lu %s_proc_max %u %s_proc_mean %lu", p, l->n,
		             p, l->n ? l->lat_min : 0, p, l->lat_max, p, l->n ? l->lat_sum / l->n : 0, p, l->proc_max, p,
		             l->n ? l->proc_sum / l->n : 0);
		put_line(s, n);
		if (clear) {
			memset(l, 0, sizeof *l);
			l->lat_min = 0xFFFF;
		}
	}
	if (clear)
		memset(&um, 0, sizeof um);
	put_line("\n", 1);
}

static __attribute__((noinline)) void pin_line(void)    /* [2026-10-19] 'X': usbdev.h usb_pin_check, 14 bits as '0' /
                                                             '1', then the 13 PA12 edge times; one text line */
{
	char s[160];
	int v = usb_pin_check(), n = 0;
	for (int i = 0; i < 14; i++)
		s[n++] = '0' + ((v >> i) & 1);
	for (int i = 0; i < 13; i++)
		n += snprintf(s + n, sizeof s - n, " %lu", pu_time[i]);
	s[n++] = '\n';
	put_line(s, n);
}

#ifdef USBH
static __attribute__((noinline)) void host_line(int clear)   /* [2026-10-20] 'H' */
{
	char s[300];
	const usbh_stats_t *u = &uh;
	int n = snprintf(s, sizeof s, "usbh state %u power %u flt %u speed %u addr %u vid %04x pid %04x ep_in %02x "
	                 "in_size %u in_type %u interval %u ep_out %02x out_size %u ms_if %u ms_alt %u enum_ms %u "
	                 "attaches %lu detaches %lu enums %lu enum_fails %lu resets %lu faults %lu ", u->state, u->power,
	                 u->flt, u->speed, u->addr, u->vid, u->pid, u->ep_in, u->in_size, u->in_type, u->interval,
	                 u->ep_out, u->out_size, u->ms_if, u->ms_alt, u->enum_ms, u->attaches, u->detaches, u->enums,
	                 u->enum_fails, u->resets, u->faults);
	put_line(s, n);
	n = snprintf(s, sizeof s, "sofs %lu polls %lu naks %lu pkts %lu bytes %lu tog_err %lu errors %lu stalls %lu "
	             "ring_full %lu late_sof %lu outs %lu sof_age_max %u cpu_max %u cpu_sum %lu ctl_naks %lu xfer_err %lu "
	             "last_err %u last_res %u events %lu sysex %lu ", u->sofs, u->polls, u->naks, u->pkts, u->bytes,
	             u->tog_err, u->errors, u->stalls, u->ring_full, u->late_sof, u->outs, u->sof_age_max, u->cpu_max,
	             u->cpu_sum, u->ctl_naks, u->xfer_err, u->last_err, u->last_res, hm.events, hm.sysex);
	put_line(s, n);
	n = snprintf(s, sizeof s, "hlat_n %lu hlat_min %u hlat_max %u hlat_mean %lu hlat_proc_max %u hlat_proc_mean %lu "
	             "dlat_n %lu dlat_min %u dlat_max %u dlat_mean %lu product ", lh.n, lh.n ? lh.lat_min : 0, lh.lat_max,
	             lh.n ? lh.lat_sum / lh.n : 0, lh.proc_max, lh.n ? lh.proc_sum / lh.n : 0, ldh.n,
	             ldh.n ? ldh.lat_min : 0, ldh.lat_max, ldh.n ? ldh.lat_sum / ldh.n : 0);
	for (int i = 0; u->product[i]; i++)
		s[n++] = u->product[i] == ' ' ? '_' : u->product[i];
	if (!u->product[0])
		s[n++] = '-';
	s[n++] = '\n';
	put_line(s, n);
	if (clear) {
		usbh_clear();
		memset(&hm, 0, sizeof hm);
		memset(&lh, 0, sizeof lh);
		memset(&ldh, 0, sizeof ldh);
		lh.lat_min = ldh.lat_min = 0xFFFF;
	}
}

static __attribute__((noinline)) void host_cmd(int op)   /* [2026-10-20] 'h' */
{
	char s[560];
	if (op == 3) {
		int n = usbh_pd_probe(s, sizeof s - 1);
		s[n++] = '\n';
		put_line(s, n);
	} else if (op == 4) {
		const uint8_t *d, *c;
		int len = usbh_descriptors(&d, &c);
		if (!len) {
			put_line("none\n", 5);
			return;
		}
		put_line("dev ", 4);
		for (int i = 0; i < 18 + len; i++) {
			if (i == 18)
				put_line(" cfg ", 5);
			uint8_t b = i < 18 ? d[i] : c[i - 18];
			uart_putc("0123456789abcdef"[b >> 4]);
			uart_putc("0123456789abcdef"[b & 15]);
		}
		uart_putc('\n');
	} else if (op == 5) {
		uint8_t b[64];
		int n = uart_getc();
		for (int i = 0; i < n; i++)
			b[i < 64 ? i : 63] = uart_getc();
		uint32_t t = now();
		int r;
		while ((r = usbh_midi_send(b, n > 64 ? 64 : n)) < 0 &&
		       (int32_t)(now() - t) < (int32_t)(FUNCONF_SYSTEM_CORE_CLOCK / 10))
			idle();
		uart_putc(r < 0 ? '-' : '+');
	} else {
		if (op == 0)
			usbh_power(0);
		else if (op == 1)
			usbh_power(1);
		else if (op == 2)
			usbh_restart();
		uart_putc('+');
	}
}
#endif

static uint16_t get16(void)
{
	uint16_t v = uart_getc();
	return v | uart_getc() << 8;
}

static __attribute__((noinline)) void bus_command(int c)
{
	uint8_t buf[256];
	if (c == 'm') {
		int n = uart_getc();
		for (int i = 0; i < n; i++)
			buf[i] = uart_getc();
		q_put(buf, n, 0, 0);
		wait_sent();
		uart_putc('+');
	} else if (c == 'e') {
		int n = uart_getc();
		for (int i = 0; i < n; i++)
			buf[i] = uart_getc();
		events_begin();
		midi_events(&pc_in, buf, n, cfg_l);
		uint16_t f0 = events_end(cfg_l);
		if (src)
			lat_add(&le, usb_cdc_stamp(), f0);            /* [2026-10-19] the last packet (no pipelining) */
		reply16(f0 + cfg_l);
	} else if (c == 'b') {
		int n = uart_getc(), fl = uart_getc();
		for (int i = 0; i < n; i++)
			buf[i] = uart_getc();
		events_begin();
		if (n >= 2)
			put(buf[0], buf[1], (fl & 0x80) ? fl & 0x3F : -1, buf + 2, n - 2 > 60 ? 60 : n - 2, fl & 0x40);
		reply16(events_end(n >= 2 ? fl & 0x3F : -1) + (fl & 0x3F));
	} else if (c == 'R') {
		uint8_t p[2];
		p[0] = uart_getc();
		p[1] = uart_getc();
		pc_req = 1;
		while (req_left)                                  /* an enumeration request is outstanding */
			idle();
		uint8_t seq = rep_seq;
		req_left = 7;
		put(card ? 0x01 : 0x00, M_REQUEST, -1, p, 2, 0);
		while (rep_seq == seq && req_left)
			idle();
		pc_req = 0;
		if (rep_seq == seq) {
			uart_putc(0);
		} else {
			uart_putc(rep_len);
			for (int i = 0; i < rep_len; i++)
				uart_putc(rep[i]);
		}
	} else if (c == 'S') {
		status_line();
	} else if (c == 'L') {
		load_line(uart_getc());
	} else if (c == 'c') {
		cfg_d = uart_getc();
		cfg_l = uart_getc();
		uint8_t p[5] = { cfg_d, cfg_l, 0, 0, 0 };
		put(0xFF, M_CONFIG, -1, p, 5, 0);
		uart_putc('+');
	} else if (c == 'k') {
		mark_mode = uart_getc();
		uart_putc('+');
	} else if (c == 'v') {
		refresh_on = uart_getc();
		uart_putc('+');
	} else if (c == 'f') {
		corrupt_n = uart_getc();
		uart_putc('+');
	} else if (c == 'g') {
		gap_req = get16();
		uart_putc('+');
	} else if (c == 'n') {
		card = 0;
		en_t = 0;
		en_state = EN_WAIT;
		uart_putc('+');
	} else if (c == 'V') {                                /* voices n, flags (V_*): all notes off */
		int nv = uart_getc(), fl = uart_getc();
		events_begin();
		n_voices = nv < 1 ? 1 : nv > NV ? NV : nv;
		v_flags = fl;
		for (int v = 0; v < NV; v++)
			vc[v].gate = 0;
		gen.held = 0;
		uint8_t p[1] = { 0 };
		put(0xFF, M_NOTE_OFF, cfg_l, p, 1, 0);
		events_end(-1);
		uart_putc('+');
	} else if (c == 'T') {                                /* refresh periods: VOICE_STATE u8, PATCH_PRESET u16,
		                                                         PATCH_DATA u16 (frames; 0 = auto / off / off) */
		vs_every = uart_getc();
		pp_every = get16();
		pd_every = get16();
		uart_putc('+');
	} else if (c == 'G') {                                /* generator: chord u8, every u16, hold u16, ctrl u8,
		                                                         cevery u16; chord and ctrl 0: off */
		uint8_t ch = uart_getc();
		uint16_t ev = get16(), ho = get16();
		uint8_t ct = uart_getc();
		uint16_t ce = get16();
		gen.on = 0;
		if (gen.held) {                                   /* release the last chord */
			uint8_t m[3 * NV];
			int k = 0;
			gen_release(m, &k);
			events_begin();
			midi_events(&gen_in, m, k, cfg_l);
			events_end(-1);
		}
		gen.chord = ch > NV ? NV : ch;
		gen.every = ev;
		gen.hold = ho;
		gen.ctrl = ct;
		gen.cevery = ce;
		gen.t = gen.k = 0;
		gen.next = frame + 1;
		gen.on = (gen.chord && gen.every) || (gen.ctrl && gen.cevery);
		uart_putc('+');
	} else if (c == 'U') {
		usb_line(uart_getc());
	} else if (c == 'Q') {                                /* bench: n bytes of USB-MIDI event packets into the OUT
		                                                     path, as if received on the endpoint -> '+' */
		int n = uart_getc();
		for (int i = 0; i < n; i++)
			buf[i] = uart_getc();
		while (usb_midi_inject(buf, n) < 0)
			idle();
		uart_putc('+');
#ifdef USBH
	} else if (c == 'H') {
		host_line(uart_getc());
	} else if (c == 'h') {
		host_cmd(uart_getc());
	} else if (c == 'I') {                                /* [2026-10-20] a packet on our own MIDI IN endpoint */
		int n = uart_getc();
		for (int i = 0; i < n; i++)
			buf[i] = uart_getc();
		uint32_t t = now();
		int r;
		while ((r = usb_midi_send(buf, n > 64 ? 64 : n)) < 0 &&
		       (int32_t)(now() - t) < (int32_t)(FUNCONF_SYSTEM_CORE_CLOCK / 10))
			idle();
		if (r == 0) {
			i_stamp = usb_stamp();
			i_pending = 1;
		}
		uart_putc(r < 0 ? '-' : '+');
#endif
	} else if (c == 'u') {                                /* D+ pull-up: 0 off, 1 on, n: off for n x 10 ms */
		int m = uart_getc();
		uart_putc('+');
		uint32_t t = now();
		while (src && usb_cdc_pending() && (int32_t)(now() - t) < (int32_t)(FUNCONF_SYSTEM_CORE_CLOCK / 20))
			idle();                                       /* the reply leaves before a detach */
		if (m < 2) {
			usb_pullup(m);
		} else {
			usb_pullup(0);
			Delay_Ms(10 * m);
			usb_pullup(1);
		}
	}
}

static void hw_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_AFIO | RCC_APB2Periph_GPIOA | RCC_APB2Periph_GPIOB | RCC_APB2Periph_USART1 |
	                  RCC_APB2Periph_TIM1;
	/* PA8 TIM1 CH1 and PA9 USART1 TX: AF push-pull 50 MHz; PA10 USART1 RX: floating input */
	GPIOA->CFGHR = (GPIOA->CFGHR & ~0xfffu) | 0xb | (0xb << 4) | (0x4 << 8);
	/* PB12 NRST, PB13 SWIO: open drain 50 MHz, released */
	GPIOB->BSHR = SWIO | NRST;
	GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xffu << 16)) | (0x7 << 16) | (0x7 << 20);

	USART1->BRR = FUNCONF_SYSTEM_CORE_CLOCK / 115200;     /* APB2 = HCLK */
	USART1->CTLR1 = USART_CTLR1_UE | USART_CTLR1_TE | USART_CTLR1_RE;
#ifndef UART_DIAG
	RCC->AHBPCENR |= RCC_AHBPeriph_DMA1;
	USART1->CTLR3 = USART_CTLR3_DMAR;                     /* RX: circular ring (uart_getc) */
	DMA1_Channel5->PADDR = (uint32_t)&USART1->DATAR;
	DMA1_Channel5->MADDR = (uint32_t)u1_ring;
	DMA1_Channel5->CNTR = U1R;
	DMA1_Channel5->CFGR = DMA_CFGR1_CIRC | DMA_CFGR1_MINC | DMA_CFGR1_EN;
#endif

	/* voice bus: USART3 PB10 TX (AF push-pull) -> card RX (PD6), PB11 RX (pull-up) <- card TX (PD5, open drain) */
	RCC->APB1PCENR |= RCC_APB1Periph_USART3;
	RCC->AHBPCENR |= RCC_AHBPeriph_DMA1;
	GPIOB->BSHR = 1u << 11;
	GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xffu << 8)) | (0xb << 8) | (0x8 << 12);
	USART3->BRR = FUNCONF_SYSTEM_CORE_CLOCK / 2 / BUS_BAUD;   /* APB1 = HCLK / 2: 72 = 4.5 at 1 Mbaud, exact */
	USART3->CTLR3 = USART_CTLR3_DMAT | USART_CTLR3_DMAR;
	USART3->CTLR1 = USART_CTLR1_UE | USART_CTLR1_TE | USART_CTLR1_RE;
	DMA1_Channel2->PADDR = (uint32_t)&USART3->DATAR;      /* TX: one transfer per frame */
	DMA1_Channel2->CFGR = DMA_CFGR1_DIR | DMA_CFGR1_MINC;
	DMA1_Channel3->PADDR = (uint32_t)&USART3->DATAR;      /* RX: circular ring */
	DMA1_Channel3->MADDR = (uint32_t)rx_ring;
	DMA1_Channel3->CNTR = RXR;
	DMA1_Channel3->CFGR = DMA_CFGR1_CIRC | DMA_CFGR1_MINC | DMA_CFGR1_EN;

	TIM1->PSC = FUNCONF_SYSTEM_CORE_CLOCK / 1000000 - 1;  /* 1 MHz */
	TIM1->ATRLR = 999;                                    /* 1 kHz */
	TIM1->CH1CVR = 500;
	TIM1->CHCTLR1 = TIM_OC1M_2 | TIM_OC1M_1 | TIM_OC1PE;  /* PWM mode 1: high from the update (frame start) */
	TIM1->CCER = TIM_CC1E;
	TIM1->BDTR = TIM_MOE;
	TIM1->SWEVGR = 1;                                     /* UG: load the preloads */
	TIM1->INTFR = 0;
	TIM1->DMAINTENR = TIM_UIE;
	NVIC_SetPriority(TIM1_UP_IRQn, 0x00);                 /* [2026-10-19] above the USB interrupt (0x80) */
	NVIC_EnableIRQ(TIM1_UP_IRQn);
	TIM1->CTLR1 = TIM_CEN;
	usb_init();
#ifdef USBH
	usbh_init();                                          /* [2026-10-20] USBFS host; the port power on last */
#endif
}

/* [2026-10-19] diagnostics: the reset cause, the stack's low-water mark (painted at start-up) */
extern uint32_t _ebss[];
static uint32_t rst_flags;

static void stack_paint(void)
{
	uint32_t *p = _ebss, *sp;
	asm volatile("mv %0, sp" : "=r"(sp));
	while (p < sp - 16)
		*p++ = 0xA5A5A5A5;
}

static unsigned stack_free(void)                          /* bytes never used above the end of .bss */
{
	uint32_t *p = _ebss;
	while (*p == 0xA5A5A5A5)
		p++;
	return (unsigned)((p - _ebss) * 4);
}

int main(void)
{
	SystemInit();
	rst_flags = RCC->RSTSCKR;
	RCC->RSTSCKR |= RCC_RMVF;
	stack_paint();
	memset(slot_preset, 0xFF, sizeof slot_preset);
	hw_init();
	printf("bench_ctrl: Ardulink SWIO programmer on USART1, SYNC 1 kHz on PA8, voice bus 1 Mbaud on USART3, "
	       "USB-MIDI + CDC (%s)%s\n", usb_port_name,
#ifdef USBH
	       ", USB-MIDI host (USBFS)"
#else
	       ""
#endif
	      );
	__builtin_setjmp(cmd_jmp);                            /* a CDC command cut off by its port lands here */
	for (;;) {
		int c = next_command();
		if (c == '?') {
			swio_line_reset();
			uart_putc('!');
		} else if (c == 'w') {
			uint8_t reg = (uint8_t)uart_getc();
			uint32_t v = 0;
			for (int i = 0; i < 4; i++)
				v |= (uint32_t)uart_getc() << (8 * i);
			swio_write(reg, v);
			uart_putc('+');
		} else if (c == 'r') {
			uint32_t v = swio_read((uint8_t)uart_getc());
			for (int i = 0; i < 4; i++)
				uart_putc((v >> (8 * i)) & 0xff);
		} else if (c == 'p' || c == 'P') {
			uart_putc('+');
		} else if (c == 'q') {                    /* bench check: PB10 as input with pull-up, its level ('0' / '1') */
			GPIOB->BSHR = 1u << 10;
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 8)) | (0x8 << 8);
			Delay_Us(100);
			int lv = (GPIOB->INDR & (1u << 10)) ? '1' : '0';
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 8)) | (0xb << 8);
			uart_putc(lv);
		} else if (c == 'z') {                    /* bench check: PB10 held low for 4 s (find where the bus wire lands) */
			uart_putc('+');
			GPIOB->BCR = 1u << 10;
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 8)) | (0x3 << 8);   /* GPIO push-pull, low */
			Delay_Ms(4000);
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 8)) | (0xb << 8);   /* back to USART3 TX */
		} else if (c == 'y') {                    /* bench check: send 0x00 on the bus, sample PB10: low / high counts */
			uint32_t lo = 0, hi = 0;
			for (int i = 0; i < 4; i++) {
				while (!(USART3->STATR & USART_STATR_TXE)) ;
				USART3->DATAR = 0;
				for (int k = 0; k < 2000; k++)
					(GPIOB->INDR & (1u << 10)) ? hi++ : lo++;
			}
			uart_putc(lo > 255 ? 255 : lo);
			uart_putc(hi > 255 ? 255 : hi);
			uart_putc((GPIOB->CFGHR >> 8) & 0xff);
		} else if (c == 'X') {                    /* [2026-10-19] bench check: the USB pins (usb_line) */
			pin_line();
		} else if (c == 'J') {                    /* [2026-10-19] bench check: '+', then a jump into the factory
			                                             bootloader (system flash 0x1FFF8000) with the clocks and the
			                                             peripherals reset; back only by a reset (minichlink -b) */
			uart_putc('+');
			while (!(USART1->STATR & USART_STATR_TC)) ;
			usb_pullup(0);
			Delay_Ms(20);
			__disable_irq();
			for (int i = 0; i < 8; i++)
				NVIC->IRER[i] = 0xFFFFFFFF;
			RCC->CFGR0 &= ~RCC_SW;                        /* HSI */
			while (RCC->CFGR0 & RCC_SWS) ;
			RCC->CTLR &= ~RCC_PLLON;
			RCC->CFGR0 = 0;
			RCC->APB2PRSTR = 0xFFFFFFFF;
			RCC->APB1PRSTR = 0xFFFFFFFF;
			RCC->AHBRSTR = 0xFFFFFFFF;
			RCC->APB2PRSTR = RCC->APB1PRSTR = RCC->AHBRSTR = 0;
			((void (*)(void))0x1FFF8000)();
		} else if (c == 'x') {                    /* bench check (not Ardulink): SWIO level released, then with pull-up */
			int open = (GPIOB->INDR & SWIO) ? '1' : '0';
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 20)) | (0x8 << 20);   /* input with pull-up (OUTDR = 1) */
			Delay_Us(200);
			int pulled = (GPIOB->INDR & SWIO) ? '1' : '0';
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 20)) | (0x7 << 20);   /* back to open drain */
			uart_putc(open);
			uart_putc(pulled);
		} else {
			bus_command(c);
		}
	}
}
