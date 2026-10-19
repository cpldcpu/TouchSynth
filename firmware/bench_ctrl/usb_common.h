/* [2026-10-19] The part of the bench controller's USB device that both drivers share (usbdev.c: USBD on PA11 /
 * PA12, the backplane's port, make USB=usbd; usbdev_fs.c: USBFS on PB6 / PB7, the development board's USB-C, the
 * default): descriptors, the data paths with their flow control, the API of usbdev.h, a bench check. Included by the
 * driver file only. The driver provides ep_rx_arm() and ep_tx() and calls the *_rx_* functions from its interrupt.
 *
 * A composite device (IAD, class EF/02/01), one direction per endpoint number (ch32fun's fsusb.c gives endpoint n
 * its buffer n):
 *   interface 0  Audio Control (MIDI 1.0: no units, the header names interface 1)
 *   interface 1  MIDI Streaming: EP 0x01 OUT bulk 64 (host -> synth), EP 0x82 IN bulk 64 (synth -> host); one
 *                cable: embedded IN jack 1 -> external OUT jack 4, external IN jack 2 -> embedded OUT jack 3
 *   interface 2  CDC ACM control: EP 0x83 IN interrupt 16 (never sends)
 *   interface 3  CDC data: EP 0x04 OUT bulk 64, EP 0x85 IN bulk 64
 *
 * Flow control: an OUT endpoint is armed again only when the next packet fits (MIDI: a free one of 4 packet slots;
 * CDC: 64 bytes in its 256-byte ring); otherwise it NAKs until the main loop has taken data, and the host retries:
 * nothing is lost.
 */
#ifndef USB_COMMON_H
#define USB_COMMON_H

#include "ch32fun.h"
#include <stdint.h>
#include <string.h>
#include "usbdev.h"

#ifndef USB_VID
#define USB_VID 0x1209                                    /* pid.codes; 0x0001 is its test PID (development only) */
#endif
#ifndef USB_PID
#define USB_PID 0x0001
#endif

enum { EP_MIDI_OUT = 1, EP_MIDI_IN = 2, EP_NOTIF = 3, EP_CDC_OUT = 4, EP_CDC_IN = 5 };

/* ------------------------------------------------------------------ descriptors */
static const uint8_t dev_desc[18] = {
	18, 1, 0x00, 0x02,                                    /* USB 2.0 (full speed) */
	0xEF, 0x02, 0x01, 64,                                 /* miscellaneous / common class / IAD; EP0 64 bytes */
	USB_VID & 0xFF, USB_VID >> 8, USB_PID & 0xFF, USB_PID >> 8,
	0x00, 0x01, 1, 2, 3, 1                                /* bcdDevice 1.00, strings 1-3, one configuration */
};

#define CFG_LEN (9 + 92 + 66)
static const uint8_t cfg_desc[CFG_LEN] = {
	9, 2, CFG_LEN & 0xFF, CFG_LEN >> 8, 4, 1, 0, 0x80, 50,   /* 4 interfaces, bus powered, 100 mA */
	/* MIDI (USB Device Class Definition for MIDI Devices 1.0, appendix B) */
	9, 4, 0, 0, 0, 1, 1, 0, 0,                            /* interface 0: audio control */
	9, 0x24, 1, 0x00, 0x01, 9, 0, 1, 1,                   /* AC header 1.00, total 9, one streaming interface: 1 */
	9, 4, 1, 0, 2, 1, 3, 0, 0,                            /* interface 1: MIDI streaming, 2 endpoints */
	7, 0x24, 1, 0x00, 0x01, 65, 0,                        /* MS header 1.00, total 65 */
	6, 0x24, 2, 1, 1, 0,                                  /* MIDI IN jack, embedded, ID 1 */
	6, 0x24, 2, 2, 2, 0,                                  /* MIDI IN jack, external, ID 2 */
	9, 0x24, 3, 1, 3, 1, 2, 1, 0,                         /* MIDI OUT jack, embedded, ID 3 <- jack 2 */
	9, 0x24, 3, 2, 4, 1, 1, 1, 0,                         /* MIDI OUT jack, external, ID 4 <- jack 1 */
	9, 5, EP_MIDI_OUT, 2, 64, 0, 0, 0, 0,                 /* EP 0x01 OUT bulk 64 */
	5, 0x25, 1, 1, 1,                                     /* -> embedded IN jack 1 */
	9, 5, 0x80 | EP_MIDI_IN, 2, 64, 0, 0, 0, 0,           /* EP 0x82 IN bulk 64 */
	5, 0x25, 1, 1, 3,                                     /* <- embedded OUT jack 3 */
	/* CDC ACM */
	8, 0x0B, 2, 2, 2, 2, 0, 0,                            /* IAD: interfaces 2-3, CDC ACM */
	9, 4, 2, 0, 1, 2, 2, 0, 0,                            /* interface 2: communications, ACM, no protocol */
	5, 0x24, 0, 0x10, 0x01,                               /* header 1.10 */
	5, 0x24, 1, 0, 3,                                     /* call management: none, data interface 3 */
	4, 0x24, 2, 2,                                        /* ACM: line coding and control line state */
	5, 0x24, 6, 2, 3,                                     /* union: control 2, data 3 */
	7, 5, 0x80 | EP_NOTIF, 3, 16, 0, 16,                  /* EP 0x83 IN interrupt 16, 16 ms */
	9, 4, 3, 0, 2, 0x0A, 0, 0, 0,                         /* interface 3: data */
	7, 5, EP_CDC_OUT, 2, 64, 0, 0,                        /* EP 0x04 OUT bulk 64 */
	7, 5, 0x80 | EP_CDC_IN, 2, 64, 0, 0,                  /* EP 0x85 IN bulk 64 */
};

/* string descriptor i (0: languages, 1 manufacturer, 2 product, 3 serial = the chip's unique ID) into b (at least
   34 bytes); returns its length, -1: none */
static int usb_string(int i, uint8_t *b)
{
	static const char *const s_text[] = { 0, "TouchSynth", "TouchSynth Poly" };
	char hex[17];
	const char *s;
	if (i == 0) {
		b[0] = 4;
		b[1] = 3;
		b[2] = 0x09;                                      /* English (US) */
		b[3] = 0x04;
		return 4;
	}
	if (i == 3) {
		uint32_t u[2] = { ESIG->UID0, ESIG->UID1 };
		for (int k = 0; k < 16; k++)
			hex[k] = "0123456789ABCDEF"[(u[k / 8] >> (28 - 4 * (k % 8))) & 15];
		hex[16] = 0;
		s = hex;
	} else if (i < 3) {
		s = s_text[i];
	} else {
		return -1;
	}
	int n = strlen(s);
	b[0] = 2 + 2 * n;
	b[1] = 3;
	for (int k = 0; k < n; k++) {
		b[2 + 2 * k] = s[k];
		b[3 + 2 * k] = 0;
	}
	return 2 + 2 * n;
}

static uint8_t line_coding[7] = { 0x00, 0xC2, 0x01, 0x00, 0, 0, 8 };   /* 115200 8N1 (only stored) */

/* ------------------------------------------------------------------ data paths */
static void ep_rx_arm(int ep);                            /* driver: OUT endpoint ep ACKs again */
static int ep_tx(int ep, const uint8_t *p, int n);        /* driver: one IN packet on ep; < 0: not now */

usb_stats_t usb_st;

#define MS 4                                              /* MIDI OUT packet slots */
static uint8_t m_buf[MS][64], m_len[MS];
static uint32_t m_stamp[MS];
static volatile uint8_t m_w, m_r, m_held, mi_busy;        /* mi_busy: a MIDI IN packet in flight */

#define CR 256                                            /* CDC rings */
static uint8_t c_rx[CR], c_tx[CR];
static volatile uint8_t c_rx_w, c_rx_r, c_rx_held, c_tx_w, c_tx_r, c_tx_busy;
static volatile uint32_t c_stamp;                         /* usb_stamp() of the last CDC OUT packet */

static int c_rx_room(void) { return CR - 1 - (uint8_t)(c_rx_w - c_rx_r); }
static int m_free(void) { return (uint8_t)(m_w - m_r) < MS; }

static uint8_t *midi_rx_slot(void) { return m_free() ? m_buf[m_w % MS] : 0; }   /* interrupt: where the packet goes */

static int midi_rx_done(int n)                            /* interrupt: the packet is in its slot; 1: arm again */
{
	m_len[m_w % MS] = n;
	m_stamp[m_w % MS] = usb_stamp();
	m_w++;
	usb_st.midi_pkts++;
	usb_st.midi_bytes += n;
	if (m_free())
		return 1;
	m_held = 1;
	usb_st.midi_held++;
	return 0;
}

static int cdc_rx_put(const uint8_t *b, int n)            /* interrupt: a CDC OUT packet; 1: arm again */
{
	for (int i = 0; i < n; i++)
		c_rx[c_rx_w++] = b[i];
	usb_st.cdc_rx += n;
	c_stamp = usb_stamp();
	if (c_rx_room() >= 64)
		return 1;
	c_rx_held = 1;
	usb_st.cdc_held++;
	return 0;
}

static void data_reset(int configured)                    /* interrupt: configuration set or cleared */
{
	mi_busy = c_tx_busy = 0;
	m_held = !m_free();
	c_rx_held = c_rx_room() < 64;
	usb_st.configured = configured;
	if (!configured)
		usb_st.dtr = 0;
}

int usb_midi_get(uint8_t *p, uint32_t *stamp)
{
	if (m_r == m_w)
		return 0;
	int s = m_r % MS, n = m_len[s];
	memcpy(p, m_buf[s], n);
	*stamp = m_stamp[s];
	m_r++;
	__disable_irq();
	if (m_held && usb_st.configured) {
		m_held = 0;
		ep_rx_arm(EP_MIDI_OUT);
	}
	__enable_irq();
	return n;
}

int usb_midi_inject(const uint8_t *p, int n)              /* bench: a packet as if from the MIDI OUT endpoint */
{
	int r = -1;
	n = n > 64 ? 64 : n & ~3;
	__disable_irq();
	uint8_t *s = midi_rx_slot();
	if (s && n) {
		memcpy(s, p, n);
		m_len[m_w % MS] = n;
		m_stamp[m_w % MS] = usb_stamp();
		m_w++;
		r = 0;
	}
	__enable_irq();
	return r;
}

int usb_midi_send(const uint8_t *p, int n)
{
	int r = -1;
	__disable_irq();
	if (usb_st.configured && !mi_busy && ep_tx(EP_MIDI_IN, p, n) >= 0) {
		mi_busy = 1;
		usb_st.midi_in_pkts++;
		r = 0;
	}
	__enable_irq();
	return r;
}

int usb_cdc_ready(void) { return usb_st.configured && usb_st.dtr; }

int usb_cdc_getc(void)
{
	if (c_rx_r == c_rx_w)
		return -1;
	int c = c_rx[c_rx_r++];
	if (c_rx_held && c_rx_room() >= 64) {
		__disable_irq();
		if (c_rx_held && usb_st.configured) {
			c_rx_held = 0;
			ep_rx_arm(EP_CDC_OUT);
		}
		__enable_irq();
	}
	return c;
}

int usb_cdc_putc(int c)
{
	if (!usb_cdc_ready()) {
		usb_st.cdc_drop++;
		return 0;                                         /* nobody listens: dropped */
	}
	if ((uint8_t)(c_tx_w + 1) == c_tx_r)
		return -1;
	c_tx[c_tx_w++] = (uint8_t)c;
	return 0;
}

int usb_cdc_pending(void) { return usb_st.configured && (c_tx_busy || c_tx_r != c_tx_w); }
uint32_t usb_cdc_stamp(void) { return c_stamp; }

static void usb_tx_poll(void)                             /* main loop: the CDC output in packets */
{
	if (!usb_st.configured || c_tx_busy || c_tx_r == c_tx_w)
		return;
	uint8_t b[63];                                        /* short packets only: no zero-length packet needed */
	int n = 0;
	uint8_t r = c_tx_r;
	while (n < (int)sizeof b && r != c_tx_w)
		b[n++] = c_tx[r++];
	__disable_irq();
	if (!c_tx_busy && ep_tx(EP_CDC_IN, b, n) >= 0) {
		c_tx_busy = 1;
		c_tx_r = r;
		usb_st.cdc_tx += n;
	}
	__enable_irq();
}

static void control_line(uint16_t val)                    /* SET_CONTROL_LINE_STATE: DTR = bit 0 */
{
	usb_st.dtr = val & 1;
	if (!usb_st.dtr)
		c_tx_r = c_tx_w;                                  /* the program closed the port: drop its pending output */
}

/* ------------------------------------------------------------------ bench check */
/* usb_pin_check (usbdev.h): the caller has detached its own peripheral. The USBD transceiver is held off (PDWN) for
   the GPIO readings, then powered (in reset) for the pull-up probe; its clock and state are restored. */
uint32_t pu_time[13];

/* PA12 driven to `high`, then released into cfg (0x4 floating, 0x8 pulled away from `high`), with the USBD pull-up if
   pu: HCLK ticks until it reads the other level, best of 8 */
static uint32_t pa12_edge(int high, uint32_t cfg, int pu)
{
	uint32_t best = 2880;
	for (int i = 0; i < 8; i++) {
		EXTEN->EXTEN_CTR &= ~EXTEN_USBD_PU_EN;
		if (high)
			GPIOA->BSHR = 1u << 12;
		else
			GPIOA->BCR = 1u << 12;
		GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xfu << 16)) | (0x3 << 16);   /* driven, push-pull */
		Delay_Us(20);
		__disable_irq();
		uint32_t t0 = *(volatile uint32_t *)&SysTick->CNT, t;
		GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xfu << 16)) | (0x4 << 16);
		if (high)
			GPIOA->BCR = 1u << 12;
		else
			GPIOA->BSHR = 1u << 12;
		GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xfu << 16)) | (cfg << 16);
		if (pu)
			EXTEN->EXTEN_CTR |= EXTEN_USBD_PU_EN;
		while (!!(GPIOA->INDR & (1u << 12)) == high && (t = *(volatile uint32_t *)&SysTick->CNT - t0) < 2880) ;
		t = *(volatile uint32_t *)&SysTick->CNT - t0;
		__enable_irq();
		if (t < best)
			best = t;
	}
	EXTEN->EXTEN_CTR &= ~EXTEN_USBD_PU_EN;
	return best;
}


static int pin_probe(void)
{
	uint32_t usben = RCC->APB1PCENR & RCC_USBEN, pb = GPIOB->CFGLR, ex = EXTEN->EXTEN_CTR, cntr;
	int v = 0;
	RCC->APB1PCENR |= RCC_USBEN;
	cntr = USBD->CNTR;
	EXTEN->EXTEN_CTR &= ~EXTEN_USBD_PU_EN;
	USBD->CNTR = USBD_FRES | USBD_PDWN;
	for (int k = 0; k < 2; k++) {                         /* GPIO pull-up (k 0), pull-down (k 1) */
		if (k) {
			GPIOA->BCR = 3u << 11;
			GPIOB->BCR = 3u << 6;
		} else {
			GPIOA->BSHR = 3u << 11;
			GPIOB->BSHR = 3u << 6;
		}
		GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xffu << 12)) | (0x8 << 12) | (0x8 << 16);
		GPIOB->CFGLR = (pb & ~(0xffu << 24)) | (0x8 << 24) | (0x8 << 28);
		Delay_Ms(2);
		v |= ((GPIOA->INDR >> 11) & 3) << (2 * k);
		v |= ((GPIOB->INDR >> 6) & 3) << (4 + 2 * k);
	}
	/* the USBD pull-up (PA12 still with the GPIO pull-down): bit 8 on, USBD in reset; bit 9 on, USBD running (no
	   interrupts enabled); then PA12 floating after the pull-down has discharged it: bit 10 on, bit 11 off */
	for (int k = 0; k < 4; k++) {
		USBD->CNTR = k ? 0 : USBD_FRES;
		if (k == 3)
			EXTEN->EXTEN_CTR &= ~EXTEN_USBD_PU_EN;
		else
			EXTEN->EXTEN_CTR |= EXTEN_USBD_PU_EN;
		if (k >= 2) {
			EXTEN->EXTEN_CTR &= ~EXTEN_USBD_PU_EN;
			GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xfu << 16)) | (0x8 << 16);   /* pull-down: discharge */
			Delay_Ms(2);
			GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xfu << 16)) | (0x4 << 16);   /* floating */
			if (k == 2)
				EXTEN->EXTEN_CTR |= EXTEN_USBD_PU_EN;
			Delay_Us(200);
		} else {
			Delay_Ms(2);
		}
		v |= ((GPIOA->INDR >> 12) & 1) << (8 + k);
	}
	/* bits 12, 13: USBD running, PA12 with the GPIO pull-up, the USBD pull-up on / off (does the GPIO pull mode
	   switch the USBD pull-up off?) */
	GPIOA->BSHR = 1u << 12;
	GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xfu << 16)) | (0x8 << 16);
	for (int k = 0; k < 2; k++) {
		if (k)
			EXTEN->EXTEN_CTR &= ~EXTEN_USBD_PU_EN;
		else
			EXTEN->EXTEN_CTR |= EXTEN_USBD_PU_EN;
		Delay_Ms(2);
		v |= ((GPIOA->INDR >> 12) & 1) << (12 + k);
	}
	USBD->CNTR = USBD_FRES;
	USBD->ISTR = 0;
	/* PA12 edge times in HCLK ticks (best of 8; 2880: none within 20 us). [0]: the loop's own delay (the pin driven
	   to the other level). Then for the USBD transceiver on (CNTR 0) with the function disabled (DADDR.EF 0), on with
	   EF 1, off (PDWN): from 0 V with the USBD pull-up alone, from 0 V with the GPIO pull-up, from 3.3 V with the GPIO
	   pull-down, from 3.3 V floating. Same pin capacitance: the ratios are the ratios of the resistances (the GPIO
	   pulls are 30-50 kOhm). */
	pu_time[0] = pa12_edge(0, 0x3, 0);
	for (int j = 0; j < 3; j++) {
		USBD->CNTR = j == 2 ? USBD_FRES | USBD_PDWN : 0;
		USBD->DADDR = j == 1 ? USBD_EF : 0;
		pu_time[1 + 4 * j] = pa12_edge(0, 0x4, 1);
		pu_time[2 + 4 * j] = pa12_edge(0, 0x8, 0);
		pu_time[3 + 4 * j] = pa12_edge(1, 0x8, 0);
		pu_time[4 + 4 * j] = pa12_edge(1, 0x4, 0);
	}
	USBD->DADDR = 0;
	USBD->CNTR = USBD_FRES;
	USBD->ISTR = 0;
	EXTEN->EXTEN_CTR = ex;
	GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xffu << 12)) | (0x4 << 12) | (0x4 << 16);   /* floating inputs */
	GPIOB->CFGLR = pb;
	USBD->CNTR = cntr;
	if (!usben)
		RCC->APB1PCENR &= ~RCC_USBEN;
	return v;
}

#endif
