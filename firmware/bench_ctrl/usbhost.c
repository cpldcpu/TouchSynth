/* [2026-10-20] USB-MIDI host on the CH32V203's USBFS (PB6 D-, PB7 D+): see usbhost.h. Build: make USBH=1.
 *
 * Register model and transaction handling follow WCH's CH32V20x EVT example USBFS/HOST_KM (ch32v20x_usbfs_host.c,
 * Copyright (c) 2021 Nanjing Qinheng Microelectronics Co., Ltd., Apache License 2.0): host mode set-up
 * (BASE_CTRL = HOST_MODE | INT_BUSY | DMA_EN, HOST_EP_MOD, one RX and one TX DMA buffer), a transaction = token
 * PID and endpoint written to HOST_EP_PID with the data toggles in HOST_RX_CTRL / HOST_TX_CTRL, completion in
 * INT_FG.UIF_TRANSFER, success = INT_ST.UIS_TOG_OK, else the handshake PID in INT_ST[3:0]; low speed with
 * UC_LOW_SPEED, UH_LOW_SPEED and UH_PRE_PID_EN; the speed from MIS_ST.UMS_DM_LEVEL after the bus reset. Rewritten
 * here as a non-blocking state machine (WCH's code busy-waits with delays of up to 100 ms per enumeration step):
 *
 *   - everything runs in the main loop (usbh_poll from idle()); the USBFS interrupt stays disabled, so the frame
 *     interrupt (TIM1 update, SYNC) keeps its timing and nothing here needs a critical section
 *   - at most one transaction per USB frame: a transaction starts only right after the host's SOF flag
 *     (UIF_HST_SOF) and not later than SOF_LATE us into the frame (the SOF phase is measured against TIM1, which
 *     runs from the same crystal: the phase is constant)
 *   - control transfers (enumeration) as a sequence of such transactions: SETUP, IN data packets, status
 *   - the MIDI IN endpoint (bulk, or interrupt every bInterval frames) is polled each frame while there is room for
 *     a packet; DATA0 / DATA1 kept per endpoint; a NAK costs nothing until the next frame; a repeated packet (the
 *     device missed our ACK: wrong toggle) is dropped; a STALL is cleared (CLEAR_FEATURE ENDPOINT_HALT, DATA0)
 *
 * Port power (backplane: TPS2051C, 0.5 A): HOST_EN (PB8, push-pull) goes high only after the host mode is set up;
 * HOST_FLT_N (PB9, input with pull-up) low for FLT_MS switches the port off, and it is tried again after 1, 2, 4,
 * 8 s (reset to 1 s by a good enumeration). On the development board PB8 / PB9 are free GPIOs (nothing switches
 * VBUS there).
 */
#include "ch32fun.h"
#include <stdio.h>
#include <string.h>
#include "usbhost.h"

#define H        USBOTG_H_FS
#define TPM      (FUNCONF_SYSTEM_CORE_CLOCK / 1000)       /* SysTick (HCLK) ticks per ms */
#define TPU      (FUNCONF_SYSTEM_CORE_CLOCK / 1000000)
#define HOST_EN  8                                        /* PB8 */
#define HOST_FLT 9                                        /* PB9 */
#define FLT_MS   2                                        /* fault filter (the TPS2051C has its own ~8 ms deglitch) */
#define SOF_LATE 700                                      /* us into a USB frame after which no transaction starts */
#define ADDR     1                                        /* the device's address */

enum { PID_OUT = 0x1, PID_ACK = 0x2, PID_DATA0 = 0x3, PID_IN = 0x9, PID_NAK = 0xA, PID_DATA1 = 0xB,
       PID_SETUP = 0xD, PID_STALL = 0xE };
enum { R_OK, R_NAK, R_STALL, R_TOG, R_ERR };              /* transaction results */
enum { HE_NONE, HE_DEV8, HE_ADDR, HE_DEV, HE_CFG9, HE_CFG, HE_SETCFG, HE_SETIF, HE_CLEAR, HE_IN, HE_ATTACH };

extern uint32_t usb_stamp(void);                          /* bench_ctrl.c: frame << 16 | us since its SYNC edge */

usbh_stats_t uh;

static __attribute__((aligned(4))) uint8_t rx_buf[64], tx_buf[64];
static uint8_t dev_desc[18], cfg[512];
static uint16_t cfg_len;

static inline uint32_t now(void) { return *(volatile uint32_t *)&SysTick->CNT; }
static int since_ms(uint32_t t0) { return (int)((now() - t0) / TPM); }

/* ------------------------------------------------------------------ received packets (main loop -> bench_ctrl.c) */
#define RS 8
static uint8_t r_buf[RS][64], r_len[RS], r_w, r_r;
static uint32_t r_stamp[RS];

int usbh_midi_get(uint8_t *p, uint32_t *stamp)
{
	if (r_r == r_w)
		return 0;
	int s = r_r % RS, n = r_len[s];
	memcpy(p, r_buf[s], n);
	*stamp = r_stamp[s];
	r_r++;
	return n;
}

/* ------------------------------------------------------------------ transactions */
static uint8_t x_busy, x_pid;
static uint16_t x_len;                                    /* bytes received by the last IN */
static uint32_t x_t0;

static void x_start(uint8_t pid, uint8_t ep, int tog)
{
	H->HOST_RX_CTRL = tog ? USBOTG_UH_R_TOG : 0;
	H->HOST_TX_CTRL = tog ? USBOTG_UH_T_TOG : 0;
	H->INT_FG = USBOTG_UIF_TRANSFER;
	H->HOST_EP_PID = (uint8_t)(pid << 4 | ep);
	x_pid = pid;
	x_busy = 1;
	x_t0 = now();
}

static int x_check(void)                                  /* -1: still running, else R_* */
{
	if (!(H->INT_FG & USBOTG_UIF_TRANSFER)) {
		if (now() - x_t0 < 2 * TPM)
			return -1;
		H->HOST_EP_PID = 0;                               /* no completion within 2 ms */
		x_busy = 0;
		uh.last_res = 0xFF;
		return R_ERR;
	}
	H->HOST_EP_PID = 0;
	uint8_t st = H->INT_ST;
	x_len = H->RX_LEN;
	H->INT_FG = USBOTG_UIF_TRANSFER;
	x_busy = 0;
	uint8_t r = st & 0x0F;
	uh.last_res = r;
	if (st & USBOTG_UIS_TOG_OK)
		return R_OK;
	if (r == PID_NAK)
		return R_NAK;
	if (r == PID_STALL)
		return R_STALL;
	if (x_pid == PID_IN && (r == PID_DATA0 || r == PID_DATA1))
		return R_TOG;                                     /* the device repeated its last packet */
	return R_ERR;                                         /* no answer, bad CRC or PID */
}

/* ------------------------------------------------------------------ USB frames */
static uint16_t sof_ph;                                   /* TIM1->CNT at the SOF (us), the earliest detection */
static uint8_t sof_cal;                                   /* SOFs seen since the port was enabled */

static int sof_slot(void)                                 /* 1: a new USB frame began just now, a transaction may start */
{
	if (!(H->INT_FG & USBOTG_UIF_HST_SOF))
		return 0;
	H->INT_FG = USBOTG_UIF_HST_SOF;
	uh.sofs++;
	uint16_t c = TIM1->CNT;
	if (sof_cal < 20) {                                   /* calibration (port enabled, nothing else to do): the
		                                                     earliest detection is the SOF phase */
		int d = (int)c - (int)sof_ph;
		if (d > 500) d -= 1000;
		if (d < -500) d += 1000;
		if (!sof_cal++ || d < 0)
			sof_ph = c;
		return 0;
	}
	uint16_t age = (uint16_t)((c + 1000 - sof_ph) % 1000);
	if (age > 950) {                                      /* a little earlier than the estimate */
		sof_ph = c;
		age = 0;
	}
	if (age > SOF_LATE) {
		uh.late_sof++;
		return 0;
	}
	if (age > uh.sof_age_max)
		uh.sof_age_max = age;
	return 1;
}

/* ------------------------------------------------------------------ control transfers (endpoint 0) */
enum { CT_IDLE, CT_SETUP, CT_IN, CT_STATUS };
static struct {
	uint8_t setup[8], stage, tog, tries, ep0;
	uint8_t *buf;
	uint16_t want, got;
	uint32_t t0;
} ct = { .ep0 = 8 };

static void ct_begin(uint8_t type, uint8_t req, uint16_t val, uint16_t idx, uint16_t len, uint8_t *buf)
{
	uint8_t s[8] = { type, req, (uint8_t)val, (uint8_t)(val >> 8), (uint8_t)idx, (uint8_t)(idx >> 8), (uint8_t)len,
	                 (uint8_t)(len >> 8) };
	memcpy(ct.setup, s, 8);
	ct.buf = buf;
	ct.want = buf ? len : 0;
	ct.got = 0;
	ct.stage = CT_SETUP;
	ct.tries = 0;
	ct.t0 = now();
}

static int ct_step(int slot)                              /* -1: running, 0: done, 1: failed */
{
	if (x_busy) {
		int r = x_check();
		if (r < 0)
			return -1;
		if (r == R_OK) {
			ct.tries = 0;
			if (ct.stage == CT_SETUP) {
				ct.stage = ct.want ? CT_IN : CT_STATUS;
				ct.tog = 1;
			} else if (ct.stage == CT_IN) {
				int n = x_len < ct.want - ct.got ? x_len : ct.want - ct.got;
				memcpy(ct.buf + ct.got, rx_buf, n);
				ct.got += n;
				ct.tog ^= 1;
				if (x_len < ct.ep0 || ct.got >= ct.want)
					ct.stage = CT_STATUS;
			} else {
				ct.stage = CT_IDLE;
				return 0;
			}
		} else if (r == R_STALL) {
			uh.stalls++;
			ct.stage = CT_IDLE;
			return 1;
		} else if (r == R_NAK) {
			uh.ctl_naks++;
		} else if (++ct.tries > 5) {                      /* R_ERR, R_TOG: the same transaction again */
			uh.xfer_err++;
			ct.stage = CT_IDLE;
			return 1;
		}
		if (since_ms(ct.t0) > 500) {                      /* NAKed for too long */
			uh.xfer_err++;
			ct.stage = CT_IDLE;
			return 1;
		}
	}
	if (!slot)
		return -1;
	if (ct.stage == CT_SETUP) {
		memcpy(tx_buf, ct.setup, 8);
		H->HOST_TX_LEN = 8;
		x_start(PID_SETUP, 0, 0);
	} else if (ct.stage == CT_IN) {
		x_start(PID_IN, 0, ct.tog);
	} else if (ct.want) {                                 /* status of a read: an empty OUT, DATA1 */
		H->HOST_TX_LEN = 0;
		x_start(PID_OUT, 0, 1);
	} else {                                              /* status of a request without data: an empty IN, DATA1 */
		x_start(PID_IN, 0, 1);
	}
	return -1;
}

/* ------------------------------------------------------------------ the device */
static uint8_t state_t, e_step, e_tries, in_tog, out_tog, out_pending, out_len, out_tries, in_wait, n_err, clr;
static uint32_t t0, t_attach, flt_t, backoff = 1000;
static uint8_t out_buf[64], str_buf[66];

static void set_speed(int low)
{
	if (low) {
		H->BASE_CTRL |= USBOTG_UC_LOW_SPEED;
		H->HOST_CTRL |= USBOTG_UH_LOW_SPEED;
		H->HOST_SETUP |= USBOTG_UH_PRE_PID_EN;
	} else {
		H->BASE_CTRL &= ~USBOTG_UC_LOW_SPEED;
		H->HOST_CTRL &= ~USBOTG_UH_LOW_SPEED;
		H->HOST_SETUP &= ~USBOTG_UH_PRE_PID_EN;
	}
}

static void port_off(void)                                /* no SOF, port disabled, address 0, full speed */
{
	if (x_busy) {
		H->HOST_EP_PID = 0;
		x_busy = 0;
	}
	H->HOST_SETUP &= ~USBOTG_UH_SOF_EN;
	H->HOST_CTRL &= ~(USBOTG_UH_PORT_EN | USBOTG_UH_BUS_RESET);
	H->DEV_ADDR = 0;
	set_speed(0);
	ct.stage = CT_IDLE;
	out_pending = 0;
	uh.addr = 0;
}

static void host_mode(void)                               /* WCH's USBFS_Host_Init; internal pull-downs on (PD_DIS 0) */
{
	H->BASE_CTRL = USBOTG_UC_RESET_SIE | USBOTG_UC_CLR_ALL;
	Delay_Us(10);
	H->BASE_CTRL = USBOTG_UC_HOST_MODE;
	H->HOST_CTRL = 0;
	H->DEV_ADDR = 0;
	H->HOST_EP_MOD = USBOTG_UH_EP_TX_EN | USBOTG_UH_EP_RX_EN;
	H->HOST_RX_DMA = (uint32_t)rx_buf;
	H->HOST_TX_DMA = (uint32_t)tx_buf;
	H->HOST_RX_CTRL = 0;
	H->HOST_TX_CTRL = 0;
	H->BASE_CTRL = USBOTG_UC_HOST_MODE | USBOTG_UC_INT_BUSY | USBOTG_UC_DMA_EN;
	H->INT_FG = 0xFF;
	H->INT_EN = USBOTG_UIE_TRANSFER | USBOTG_UIE_DETECT | USBOTG_UIE_HST_SOF;   /* flags only: NVIC off */
	x_busy = 0;
}

static void go(uint8_t s)
{
	uh.state = s;
	t0 = now();
}

static void detached(void)
{
	port_off();
	uh.detaches++;
	uh.ep_in = uh.ep_out = 0;
	go(HS_WAIT);
}

void usbh_power(int on)
{
	if (on) {
		GPIOB->BSHR = 1u << HOST_EN;
		uh.power = 1;
		go(HS_WAIT);
	} else {
		GPIOB->BCR = 1u << HOST_EN;
		uh.power = 0;
		port_off();
		go(HS_OFF);
	}
	flt_t = 0;
}

void usbh_restart(void)
{
	if (uh.state >= HS_DEBOUNCE && uh.state <= HS_FAILED) {
		port_off();
		e_tries = 0;
		go(HS_DEBOUNCE);                                  /* reset again after the debounce time */
		t_attach = now();
	}
}

void usbh_clear(void)
{
	uh.attaches = uh.detaches = uh.enums = uh.enum_fails = uh.resets = uh.faults = 0;
	uh.sofs = uh.polls = uh.naks = uh.pkts = uh.bytes = uh.tog_err = uh.errors = uh.stalls = 0;
	uh.ring_full = uh.late_sof = uh.outs = uh.cpu_sum = uh.ctl_naks = uh.xfer_err = 0;
	uh.sof_age_max = uh.cpu_max = 0;
}

void usbh_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOB;
	GPIOB->BCR = 1u << HOST_EN;                           /* port power off (the backplane: 100 kOhm pull-down too) */
	GPIOB->BSHR = 1u << HOST_FLT;
	GPIOB->CFGHR = (GPIOB->CFGHR & ~0xffu) | 0x2 | (0x8 << 4);   /* PB8 push-pull 2 MHz, PB9 input with pull-up */
	RCC->CFGR0 = (RCC->CFGR0 & ~RCC_USBPRE) | RCC_USBPRE_DIV3;   /* 48 MHz (also set by usbdev.c) */
	RCC->AHBPCENR |= RCC_USBFS;
	host_mode();
	usbh_power(1);                                        /* only now: the host mode is set up */
}

/* the first Audio (1) / MIDI Streaming (3) interface with an IN endpoint; 1: found */
static int parse_cfg(void)
{
	int ms = 0, found = 0;
	uh.ep_in = uh.ep_out = 0;
	for (int i = 0; i + 2 <= cfg_len && cfg[i] >= 2; i += cfg[i]) {
		const uint8_t *d = cfg + i;
		if (d[1] == 4 && cfg[i] >= 9) {                   /* interface */
			if (found)
				break;
			ms = d[5] == 1 && d[6] == 3;
			if (ms) {
				uh.ms_if = d[2];
				uh.ms_alt = d[3];
				uh.ep_out = 0;
			}
		} else if (d[1] == 5 && cfg[i] >= 7 && ms) {      /* endpoint of a MIDI streaming interface */
			uint8_t type = d[3] & 3;
			if (type != 2 && type != 3)
				continue;
			uint16_t size = d[4] | d[5] << 8;
			if (d[2] & 0x80) {
				if (!uh.ep_in) {
					uh.ep_in = d[2];
					uh.in_size = size > 64 ? 64 : size;
					uh.in_type = type;
					uh.interval = type == 3 && d[6] ? d[6] : 1;
					found = 1;
				}
			} else if (!uh.ep_out) {
				uh.ep_out = d[2];
				uh.out_size = size > 64 ? 64 : size;
			}
		}
	}
	return found;
}

enum { E_DEV8, E_ADDR, E_ADDR_WAIT, E_DEV, E_CFG9, E_CFG, E_STR, E_SETCFG, E_SETIF, E_DONE };

static void enum_begin(int step)
{
	e_step = step;
	switch (step) {
	case E_DEV8: ct_begin(0x80, 6, 0x0100, 0, 8, dev_desc); break;
	case E_ADDR: ct_begin(0x00, 5, ADDR, 0, 0, 0); break;
	case E_DEV: ct_begin(0x80, 6, 0x0100, 0, 18, dev_desc); break;
	case E_CFG9: ct_begin(0x80, 6, 0x0200, 0, 9, cfg); break;
	case E_CFG: {
		uint16_t n = cfg[2] | cfg[3] << 8;
		cfg_len = n > sizeof cfg ? sizeof cfg : n;
		ct_begin(0x80, 6, 0x0200, 0, cfg_len, cfg);
		break;
	}
	case E_STR: ct_begin(0x80, 6, 0x0300 | dev_desc[15], 0x0409, sizeof str_buf, str_buf); break;
	case E_SETCFG: ct_begin(0x00, 9, cfg[5], 0, 0, 0); break;
	case E_SETIF: ct_begin(0x01, 11, uh.ms_alt, uh.ms_if, 0, 0); break;
	}
}

static void enum_fail(uint8_t err)
{
	uh.last_err = err;
	uh.enum_fails++;
	port_off();
	if (++e_tries < 3) {
		go(HS_DEBOUNCE);                                  /* 100 ms, then another bus reset */
	} else {
		go(HS_FAILED);                                    /* until the device is unplugged */
	}
}

static void enum_next(void)
{
	switch (e_step) {
	case E_DEV8:
		ct.ep0 = dev_desc[7] >= 8 && dev_desc[7] <= 64 ? dev_desc[7] : 8;
		enum_begin(E_ADDR);
		break;
	case E_ADDR:
		H->DEV_ADDR = (H->DEV_ADDR & USBOTG_UDA_GP_BIT) | ADDR;
		uh.addr = ADDR;
		e_step = E_ADDR_WAIT;
		t0 = now();
		break;
	case E_DEV:
		uh.vid = dev_desc[8] | dev_desc[9] << 8;
		uh.pid = dev_desc[10] | dev_desc[11] << 8;
		enum_begin(E_CFG9);
		break;
	case E_CFG9:
		enum_begin(E_CFG);
		break;
	case E_CFG:
		memset(str_buf, 0, sizeof str_buf);
		if (dev_desc[15]) {
			enum_begin(E_STR);
			break;
		}
		/* fall through */
	case E_STR: {
		int n = 0;                                        /* UTF-16LE -> ASCII ('?' beyond) */
		for (int i = 2; i + 1 < str_buf[0] && i + 1 < (int)sizeof str_buf && n < 32; i += 2)
			uh.product[n++] = str_buf[i + 1] || str_buf[i] < 32 || str_buf[i] > 126 ? '?' : str_buf[i];
		uh.product[n] = 0;
		enum_begin(E_SETCFG);
		break;
	}
	case E_SETCFG:
		if (parse_cfg() && uh.ms_alt) {
			enum_begin(E_SETIF);
			break;
		}
		/* fall through */
	case E_SETIF:
		uh.enums++;
		uh.enum_ms = (uint16_t)since_ms(t_attach);
		e_tries = 0;
		backoff = 1000;
		in_tog = out_tog = 0;
		in_wait = 0;
		n_err = 0;
		uh.last_err = HE_NONE;
		go(uh.ep_in ? HS_RUN : HS_NOMIDI);
		break;
	}
}

static void enum_poll(int slot)
{
	if (e_step == E_ADDR_WAIT) {                          /* SET_ADDRESS recovery: 2 ms (USB 2.0 9.2.6.3) */
		if (since_ms(t0) >= 5)
			enum_begin(E_DEV);
		return;
	}
	int r = ct_step(slot);
	if (r < 0)
		return;
	if (r == 0) {
		enum_next();
	} else if (e_step == E_STR) {                         /* strings are optional */
		str_buf[0] = 0;
		enum_next();
	} else {
		static const uint8_t err[] = { HE_DEV8, HE_ADDR, 0, HE_DEV, HE_CFG9, HE_CFG, 0, HE_SETCFG, HE_SETIF };
		enum_fail(err[e_step]);
	}
}

/* running: the MIDI IN endpoint each frame (interrupt endpoints every bInterval frames), OUT when a packet waits */
static void run_poll(int slot)
{
	static uint8_t cur;                                   /* the transaction in flight: 'i', 'o' or 'c' (control) */
	if (clr) {                                            /* clearing a halted IN endpoint */
		int r = ct_step(slot);
		if (r < 0)
			return;
		clr = 0;
		in_tog = 0;
		if (r) {
			uh.last_err = HE_CLEAR;
			usbh_restart();
		}
		return;
	}
	if (x_busy) {
		int r = x_check();
		if (r < 0)
			return;
		if (cur == 'i') {
			if (r == R_OK) {
				in_tog ^= 1;
				n_err = 0;
				int n = x_len & ~3;
				if (n) {
					int s = r_w % RS;
					memcpy(r_buf[s], rx_buf, n);
					r_len[s] = n;
					r_stamp[s] = usb_stamp();
					r_w++;
					uh.pkts++;
					uh.bytes += n;
				}
			} else if (r == R_NAK) {
				uh.naks++;
				n_err = 0;
			} else if (r == R_TOG) {
				uh.tog_err++;
			} else if (r == R_STALL) {
				uh.stalls++;
				ct_begin(0x02, 1, 0, uh.ep_in, 0, 0);     /* CLEAR_FEATURE(ENDPOINT_HALT) */
				clr = 1;
			} else {
				uh.errors++;
				if (++n_err > 20) {                       /* the device does not answer any more */
					uh.last_err = HE_IN;
					usbh_restart();
				}
			}
		} else if (cur == 'o') {
			if (r == R_OK) {
				out_tog ^= 1;
				out_pending = 0;
				uh.outs++;
			} else if (r == R_STALL || (r != R_NAK && ++out_tries > 3)) {
				out_pending = 0;                          /* dropped */
				uh.errors++;
			}
		}
	}
	if (!slot)
		return;
	if (out_pending) {
		memcpy(tx_buf, out_buf, out_len);
		H->HOST_TX_LEN = out_len;
		x_start(PID_OUT, uh.ep_out & 0x0F, out_tog);
		cur = 'o';
		return;
	}
	if (in_wait && --in_wait)
		return;
	if ((uint8_t)(r_w - r_r) >= RS) {                     /* the main loop has not taken the packets yet */
		uh.ring_full++;
		return;
	}
	in_wait = uh.interval;
	x_start(PID_IN, uh.ep_in & 0x0F, in_tog);
	cur = 'i';
	uh.polls++;
}

int usbh_midi_send(const uint8_t *p, int n)
{
	if (uh.state != HS_RUN || !uh.ep_out || out_pending || n > uh.out_size || n <= 0)
		return -1;
	memcpy(out_buf, p, n);
	out_len = n;
	out_tries = 0;
	out_pending = 1;
	return 0;
}

void usbh_poll(void)
{
	uint32_t t_in = now();
	uint8_t s0 = uh.state;
	int busy0 = x_busy;

	/* port power fault (HOST_FLT_N low) */
	uh.flt = (GPIOB->INDR >> HOST_FLT) & 1;
	if (uh.power && !uh.flt) {
		if (!flt_t) {
			flt_t = now() | 1;
		} else if (now() - flt_t >= FLT_MS * TPM) {
			GPIOB->BCR = 1u << HOST_EN;
			uh.power = 0;
			uh.faults++;
			port_off();
			go(HS_FAULT);
			flt_t = 0;
		}
	} else {
		flt_t = 0;
	}

	/* detach: not attached now, or (enumerating / running) a DETECT event or UH_PORT_EN cleared by the hardware: the
	   device left and may be back already (bench 2026-10-20: a 300 ms detach while the main loop was blocked was
	   missed when only the attach level was checked) */
	if (uh.state == HS_DEBOUNCE || uh.state >= HS_ENUM) {
		int ev = H->INT_FG & USBOTG_UIF_DETECT;
		if (ev)
			H->INT_FG = USBOTG_UIF_DETECT;
		int gone = !(H->MIS_ST & USBOTG_UMS_DEV_ATTACH);
		if (uh.state >= HS_ENUM && uh.state <= HS_NOMIDI && (ev || !(H->HOST_CTRL & USBOTG_UH_PORT_EN)))
			gone = 1;
		if (uh.state <= HS_FAILED && gone) {
			if (uh.state == HS_DEBOUNCE)
				go(HS_WAIT);
			else
				detached();
		}
	}

	int slot = uh.state >= HS_RECOVER && uh.state <= HS_NOMIDI ? sof_slot() : 0;
	switch (uh.state) {
	case HS_WAIT:
		if (H->MIS_ST & USBOTG_UMS_DEV_ATTACH) {
			H->INT_FG = USBOTG_UIF_DETECT;
			uh.attaches++;
			e_tries = 0;
			t_attach = now();
			go(HS_DEBOUNCE);
		}
		break;
	case HS_DEBOUNCE:                                     /* 100 ms of attach (USB 2.0 7.1.7.3), then the bus reset */
		if (since_ms(t0) >= 100) {
			set_speed(0);
			H->DEV_ADDR = 0;
			H->HOST_CTRL |= USBOTG_UH_BUS_RESET;
			uh.resets++;
			go(HS_RESET);
		}
		break;
	case HS_RESET:                                        /* SE0 for 15 ms (10-20 ms) */
		if (since_ms(t0) >= 15) {
			H->HOST_CTRL &= ~USBOTG_UH_BUS_RESET;
			go(HS_RECOVER);
			state_t = 0;
		}
		break;
	case HS_RECOVER:
		if (!state_t) {
			if (since_ms(t0) < 2)
				break;
			H->INT_FG = USBOTG_UIF_DETECT;                /* the reset itself may have flagged a detach */
			if (!(H->MIS_ST & USBOTG_UMS_DEV_ATTACH)) {
				detached();
				break;
			}
			uh.speed = !(H->MIS_ST & USBOTG_UMS_DM_LEVEL);   /* D- high in idle: low speed */
			set_speed(!uh.speed);
			H->HOST_CTRL |= USBOTG_UH_PORT_EN;
			H->HOST_SETUP |= USBOTG_UH_SOF_EN;
			H->INT_FG = USBOTG_UIF_HST_SOF;
			sof_cal = 0;
			state_t = 1;
			t0 = now();
		} else if (since_ms(t0) >= 20) {                  /* reset recovery (10 ms) and the SOF phase */
			ct.ep0 = 8;
			go(HS_ENUM);
			enum_begin(E_DEV8);
		}
		break;
	case HS_ENUM:
		enum_poll(slot);
		break;
	case HS_RUN:
		run_poll(slot);
		break;
	case HS_FAULT:
		if (since_ms(t0) >= (int)backoff) {
			if (backoff < 8000)
				backoff *= 2;
			usbh_power(1);
		}
		break;
	}

	/* CPU time of calls that did something (a transaction started or finished, a state change) */
	if (x_busy != busy0 || uh.state != s0 || slot) {
		uint32_t us = (now() - t_in) / TPU;
		uh.cpu_sum += us;
		if (us > uh.cpu_max)
			uh.cpu_max = us;
	}
}

/* ------------------------------------------------------------------ bench checks */
int usbh_descriptors(const uint8_t **dev, const uint8_t **conf)
{
	*dev = dev_desc;
	*conf = cfg;
	return uh.state >= HS_RUN && uh.state <= HS_NOMIDI ? cfg_len : 0;
}

/* PB6 or PB7 driven high, then released as a floating input: SysTick ticks until it reads 0, best of 8 (TMAX: not
   within 50 us). With a pull-down R and the pin's capacitance C the time is R C ln(3.3 V / V_IL): the ratio of two
   times is the ratio of the two pull-down resistances (same pin, same C). ref: the pin driven low instead (the
   loop's own delay). */
#define TMAX (50 * TPU)
static uint32_t edge(int pin, int ref)
{
	uint32_t best = TMAX, sh = pin * 4, t;
	for (int i = 0; i < 8; i++) {
		GPIOB->BSHR = 1u << pin;
		GPIOB->CFGLR = (GPIOB->CFGLR & ~(0xfu << sh)) | (0x3u << sh);   /* push-pull, high */
		Delay_Us(20);
		__disable_irq();
		uint32_t t0 = now();
		if (ref)
			GPIOB->BCR = 1u << pin;
		else
			GPIOB->CFGLR = (GPIOB->CFGLR & ~(0xfu << sh)) | (0x4u << sh);   /* floating input */
		do
			t = now() - t0;
		while (((GPIOB->INDR >> pin) & 1) && t < TMAX);
		__enable_irq();
		if (t < best)
			best = t;
	}
	GPIOB->CFGLR = (GPIOB->CFGLR & ~(0xfu << sh)) | (0x4u << sh);
	return best;
}

/* PB6 / PB7 as GPIO with the pull-ups (cnf 0x8, up), the pull-downs (0x8, !up) or driven high (0x3): bits 0, 1 the
   GPIO input (D-, D+), bits 2, 3 the SIE's pin bits (UH_DM_PIN, UH_DP_PIN; 0 with the USBFS clock off) */
static int levels(int up, uint32_t cnf)
{
	if (up)
		GPIOB->BSHR = 3u << 6;
	else
		GPIOB->BCR = 3u << 6;
	GPIOB->CFGLR = (GPIOB->CFGLR & ~(0xffu << 24)) | (cnf << 24) | (cnf << 28);
	Delay_Ms(1);
	int v = (GPIOB->INDR >> 6) & 3;
	if (RCC->AHBPCENR & RCC_USBFS)
		v |= ((H->HOST_CTRL >> 4) & 3) << 2;
	GPIOB->CFGLR = (GPIOB->CFGLR & ~(0xffu << 24)) | (0x4u << 24) | (0x4u << 28);
	return v;
}

static void probe_mode(int c)                             /* the USBFS clock on, the SIE in condition c */
{
	RCC->AHBPCENR |= RCC_USBFS;
	H->BASE_CTRL = USBOTG_UC_RESET_SIE | USBOTG_UC_CLR_ALL;
	Delay_Us(10);
	if (c == 1 || c == 2) {
		H->BASE_CTRL = 0;
		H->HOST_CTRL = c == 2 ? USBOTG_UD_PD_DIS : 0;      /* UDEV_CTRL: port I/O off */
	} else if (c >= 3) {
		H->BASE_CTRL = USBOTG_UC_HOST_MODE;
		H->HOST_CTRL = c == 4 ? USBOTG_UH_PD_DIS : 0;
	}
	if (c == 0)
		RCC->AHBPCENR &= ~RCC_USBFS;
	Delay_Ms(1);
}

/* Condition c set up, then the SIE held in reset (UC_RESET_SIE: the pads are GPIOs again), the pin charged to
   3.3 V by its GPIO output (the other pin driven low), released as a floating input, then the SIE out of reset in
   condition c: ticks until the SIE's pin bit (*ts) and the GPIO input (*ti) read 0, best of 8 (TMAX: not within
   50 us). Returns 1 if the pin read high before the release; *hc: HOST_CTRL afterwards (PD_DIS kept?). */
static int release(int c, int pin, uint32_t *ts, uint32_t *ti, uint8_t *hcr)
{
	uint32_t sh = pin * 4, o = pin == 6 ? 7 : 6, sb = pin == 6 ? 0x10 : 0x20, t, ok = 1;
	*ts = *ti = TMAX;
	probe_mode(c);
	uint8_t bc = H->BASE_CTRL, hc = H->HOST_CTRL & 0xCF;
	for (int i = 0; i < 8; i++) {
		H->BASE_CTRL = bc | USBOTG_UC_RESET_SIE;           /* the SIE in reset: the pads are GPIOs */
		GPIOB->BSHR = 1u << pin;
		GPIOB->BCR = 1u << o;
		GPIOB->CFGLR = (GPIOB->CFGLR & ~(0xffu << 24)) | (0x3u << 24) | (0x3u << 28);
		Delay_Us(20);
		ok &= (GPIOB->INDR >> pin) & 1;
		__disable_irq();
		GPIOB->CFGLR = (GPIOB->CFGLR & ~(0xffu << 24)) | (0x4u << 24) | (0x4u << 28);
		uint32_t t0 = now(), es = TMAX, ei = TMAX;
		H->BASE_CTRL = bc;
		H->HOST_CTRL = hc;
		do {
			t = now() - t0;
			if (es == TMAX && !(H->HOST_CTRL & sb))
				es = t;
			if (ei == TMAX && !((GPIOB->INDR >> pin) & 1))
				ei = t;
		} while ((es == TMAX || ei == TMAX) && t < TMAX);
		__enable_irq();
		if (es < *ts) *ts = es;
		if (ei < *ti) *ti = ei;
	}
	(void)sh;
	*hcr = H->HOST_CTRL;
	return ok;
}

/* The internal D+ / D- pull-downs of the USBFS port (UH_PD_DIS / UD_PD_DIS = 0: on), five conditions:
     off   USBFS clock off            dev   device mode, port off, PD_DIS 0     devd  the same with PD_DIS 1
     host  host mode, PD_DIS 0        hostd host mode, PD_DIS 1
   Bench 2026-10-20: while the USBFS clock runs, the GPIO block does not reach PB6 / PB7 (driven high as outputs
   they read 0), so GPIO pulls tell nothing then. Per condition (bit pairs D-, D+): "up" the GPIO inputs with the
   GPIO pull-ups, "drv" with the pins driven high, "sie" the SIE's pin bits (UH_DM_PIN, UH_DP_PIN) with the pins
   floating; "fall" (off only): the falling-edge time of each pin from 3.3 V without a GPIO pull, through the
   external pull-downs alone; "rel" (the other four): each pin charged to 3.3 V with the USBFS clock gated, then
   the clock on: ticks until the SIE's pin bit and the GPIO input read 0 (release()). With an external pull-down
   R_ext and an internal one R_int: rel(PD_DIS 1) ~ R_ext C, rel(PD_DIS 0) ~ (R_ext || R_int) C; without R_ext
   (no cable): PD_DIS 1 does not fall at all. Ticks: 144 per us. */
int usbh_pd_probe(char *s, int n)
{
	static const char *const name[5] = { "off", "dev", "devd", "host", "hostd" };
	int k = 0, pw = uh.power;
	port_off();
	k += snprintf(s + k, n - k, "pd tpu %u tmax %lu ref %lu %lu", (unsigned)TPU, (unsigned long)TMAX,
	              (unsigned long)edge(6, 1), (unsigned long)edge(7, 1));
	for (int c = 0; c < 5; c++) {
		probe_mode(c);
		int sie = c ? (H->HOST_CTRL >> 4) & 3 : 0;   /* bit 0: DM, bit 1: DP; GPIO floating */
		int up = levels(1, 0x8), drv = levels(1, 0x3);
		k += snprintf(s + k, n - k, " %s up %d%d drv %d%d sie %d%d", name[c], up & 1, (up >> 1) & 1, drv & 1,
		              (drv >> 1) & 1, sie & 1, (sie >> 1) & 1);
		if (c == 0) {
			uint32_t f6 = edge(6, 0), f7 = edge(7, 0);
			k += snprintf(s + k, n - k, " fall %lu %lu", (unsigned long)f6, (unsigned long)f7);
		} else {
			uint32_t s6, i6, s7, i7;
			uint8_t h6, h7;
			int ok = release(c, 6, &s6, &i6, &h6) | release(c, 7, &s7, &i7, &h7) << 1;
			k += snprintf(s + k, n - k, " rel %lu %lu io %lu %lu ok %d hc %02x", (unsigned long)s6,
			              (unsigned long)s7, (unsigned long)i6, (unsigned long)i7, ok, h6 & h7);
		}
	}
	RCC->AHBPCENR |= RCC_USBFS;
	host_mode();
	if (pw)
		usbh_power(1);
	else
		usbh_power(0);
	return k;
}
