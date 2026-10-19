/* [2026-10-19] USB device of the bench controller on the CH32V203's USBD (the full-speed device controller on
 * PA11 D-, PA12 D+): the backplane's USB-C port (backplane.md 3.2, 4). Build: make USB=usbd. Descriptors, data
 * paths and the API: usb_common.h. The development board's USB-C is wired to USBFS instead: usbdev_fs.c (default).
 *
 * Own driver, written for this firmware from the reference manual's register model (the STM32-style USB device
 * block: one EPRn register per endpoint number, buffer descriptors and packets in the 512-byte PMA shared with CAN,
 * 16-bit words at a 32-bit stride). ch32fun's extralibs/usbd.c drives the same block, but it always re-arms an OUT
 * endpoint after a packet (no flow control: a MIDI flood would be lost), writes RCC->AHBPCENR = SRAM (turns DMA1,
 * the voice bus, off) and NAKs the wrong direction after an IN packet. After a packet the hardware NAKs the
 * endpoint until it is armed again: the flow control of usb_common.h needs nothing else.
 *
 * The interrupt (USB_LP_CAN1_RX0) has a lower priority than the frame interrupt (TIM1_UP) and copies at most 64
 * bytes; the MIDI parsing runs in the main loop (bench_ctrl.c: the same path as the PC command 'e').
 * Not yet proven on hardware: the development board has no host on PA11 / PA12 (bench 2026-10-19).
 */
#include "usb_common.h"

/* ------------------------------------------------------------------ packet memory */
#define PMA ((volatile uint32_t *)CAN_USBD_SHARED_BASE)  /* 16 bits per 32-bit word */
#define BT(ep, k) PMA[(ep) * 4 + (k)]                     /* buffer table at 0: ADDR_TX, COUNT_TX, ADDR_RX, COUNT_RX */
enum {                                                    /* PMA byte addresses (BTABLE: 6 endpoints x 8 bytes) */
	A_EP0_RX = 0x40, A_EP0_TX = 0x80, A_MIDI_RX = 0xC0, A_MIDI_TX = 0x100, A_NOTIF_TX = 0x140, A_CDC_RX = 0x150,
	A_CDC_TX = 0x190                                      /* ... 0x1D0 of 0x200 */
};
#define RX64 0x8400                                       /* COUNT_RX: BL_SIZE 1, 2 blocks of 32 bytes */

static void pma_write(uint16_t a, const uint8_t *p, int n)
{
	volatile uint32_t *d = PMA + a / 2;
	for (int i = 0; i < n; i += 2)
		*d++ = p[i] | (i + 1 < n ? p[i + 1] << 8 : 0);
}

static void pma_read(uint16_t a, uint8_t *p, int n)
{
	volatile uint32_t *s = PMA + a / 2;
	for (int i = 0; i < n; i += 2) {
		uint16_t w = *s++;
		p[i] = (uint8_t)w;
		if (i + 1 < n)
			p[i + 1] = w >> 8;
	}
}

/* ------------------------------------------------------------------ endpoint registers */
/* CTR_RX / CTR_TX: write 0 clears, 1 keeps; DTOG and STAT: write 1 toggles; type, kind, address: plain */
#define EP_KEEP (USBD_CTR_RX | USBD_SETUP | USBD_EPTYPE | USBD_EPKIND | USBD_CTR_TX | USBD_EA)
enum { RX_DIS = 0, RX_STALL = 0x1000, RX_NAK = 0x2000, RX_VALID = 0x3000,
       TX_DIS = 0, TX_STALL = 0x0010, TX_NAK = 0x0020, TX_VALID = 0x0030 };
enum { T_BULK = 0x0000, T_CTRL = 0x0200, T_INT = 0x0600 };

static void stat_rx(int ep, uint16_t s)
{
	uint16_t r = USBD->EPR[ep];
	USBD->EPR[ep] = ((r & (EP_KEEP | USBD_STAT_RX)) ^ s) | USBD_CTR_RX | USBD_CTR_TX;
}

static void stat_tx(int ep, uint16_t s)
{
	uint16_t r = USBD->EPR[ep];
	USBD->EPR[ep] = ((r & (EP_KEEP | USBD_STAT_TX)) ^ s) | USBD_CTR_RX | USBD_CTR_TX;
}

static void clear_ctr(int ep, uint16_t which)             /* which: USBD_CTR_RX or USBD_CTR_TX */
{
	USBD->EPR[ep] = ((USBD->EPR[ep] & EP_KEEP) | USBD_CTR_RX | USBD_CTR_TX) & ~which;
}

static void ep_open(int ep, uint16_t type, uint16_t rx, uint16_t tx)   /* type and address; DTOG 0; the stats */
{
	uint16_t r = USBD->EPR[ep];
	USBD->EPR[ep] = type | ep | ((r & (USBD_DTOG_RX | USBD_STAT_RX | USBD_DTOG_TX | USBD_STAT_TX)) ^ (rx | tx));
}

/* ------------------------------------------------------------------ driver hooks of usb_common.h */
static void ep_rx_arm(int ep) { stat_rx(ep, RX_VALID); }

static int ep_tx(int ep, const uint8_t *p, int n)
{
	pma_write(ep == EP_MIDI_IN ? A_MIDI_TX : A_CDC_TX, p, n);
	BT(ep, 1) = n;
	stat_tx(ep, TX_VALID);
	return 0;
}

static void out_packet(int ep)                            /* interrupt: an OUT packet (the endpoint NAKs now) */
{
	int n = BT(ep, 3) & 0x3FF;
	n = n > 64 ? 64 : n;
	if (ep == EP_MIDI_OUT) {
		uint8_t *s = midi_rx_slot();                      /* always free: armed only with a free slot */
		if (!s)
			return;
		pma_read(A_MIDI_RX, s, n);
		if (midi_rx_done(n))
			stat_rx(ep, RX_VALID);
	} else {
		uint8_t b[64];
		pma_read(A_CDC_RX, b, n);
		if (cdc_rx_put(b, n))
			stat_rx(ep, RX_VALID);
	}
}

/* ------------------------------------------------------------------ control endpoint */
enum { C_IDLE, C_IN, C_STATUS_IN, C_OUT };
static uint8_t ctl_state, ctl_zlp, ctl_addr, ctl_req;
static const uint8_t *ctl_p;
static uint16_t ctl_n;
static uint8_t ctl_buf[64];

static void ep0_in(void)                                  /* the next IN packet of the data stage (or a ZLP) */
{
	int n = ctl_n > 64 ? 64 : ctl_n;
	pma_write(A_EP0_TX, ctl_p, n);
	BT(0, 1) = n;
	ctl_p += n;
	ctl_n -= n;
	stat_tx(0, TX_VALID);
}

static void ep0_zlp(void)                                 /* status stage IN */
{
	ctl_state = C_STATUS_IN;
	BT(0, 1) = 0;
	stat_tx(0, TX_VALID);
}

static int ep_valid(uint8_t a)                            /* an endpoint address of the configuration */
{
	int ep = a & 0x7F;
	return ep >= 1 && ep <= 5 && !(a & 0x80) == (ep == EP_MIDI_OUT || ep == EP_CDC_OUT);
}

static void halt(uint8_t a, int on)                       /* SET / CLEAR_FEATURE(ENDPOINT_HALT) */
{
	int ep = a & 0x7F;
	uint16_t r = USBD->EPR[ep];
	if (a & 0x80) {
		if (!on && (r & USBD_DTOG_TX))                    /* clearing the halt resets the data toggle */
			USBD->EPR[ep] = (r & EP_KEEP) | USBD_CTR_RX | USBD_CTR_TX | USBD_DTOG_TX;
		stat_tx(ep, on ? TX_STALL : TX_NAK);
		if (ep == EP_MIDI_IN) mi_busy = 0;
		if (ep == EP_CDC_IN) c_tx_busy = 0;
	} else {
		if (!on && (r & USBD_DTOG_RX))
			USBD->EPR[ep] = (r & EP_KEEP) | USBD_CTR_RX | USBD_CTR_TX | USBD_DTOG_RX;
		int held = ep == EP_MIDI_OUT ? m_held : c_rx_held;
		stat_rx(ep, on ? RX_STALL : held ? RX_NAK : RX_VALID);
	}
}

static void configure(int on)
{
	data_reset(on);
	if (on) {
		ep_open(EP_MIDI_OUT, T_BULK, m_held ? RX_NAK : RX_VALID, TX_DIS);
		ep_open(EP_MIDI_IN, T_BULK, RX_DIS, TX_NAK);
		ep_open(EP_NOTIF, T_INT, RX_DIS, TX_NAK);
		ep_open(EP_CDC_OUT, T_BULK, c_rx_held ? RX_NAK : RX_VALID, TX_DIS);
		ep_open(EP_CDC_IN, T_BULK, RX_DIS, TX_NAK);
	} else {
		for (int ep = 1; ep <= 5; ep++)
			ep_open(ep, ep == EP_NOTIF ? T_INT : T_BULK, RX_DIS, TX_DIS);
	}
}

static void set_interface(int itf)                        /* alternate setting 0 again: the data toggles restart */
{
	static const uint8_t eps[4][2] = { { 0, 0 }, { EP_MIDI_OUT, 0x80 | EP_MIDI_IN }, { 0x80 | EP_NOTIF, 0 },
	                                   { EP_CDC_OUT, 0x80 | EP_CDC_IN } };
	for (int i = 0; i < 2; i++)
		if (eps[itf][i])
			halt(eps[itf][i], 0);
}

/* a SETUP packet: returns the IN data length (with ctl_p set), 0: no data stage, -1: stall, -2: OUT data follows */
static int setup(const uint8_t *s)
{
	uint8_t type = s[0], req = s[1];
	uint16_t val = s[2] | s[3] << 8, idx = s[4] | s[5] << 8, len = s[6] | s[7] << 8;
	static const uint8_t zero2[2] = { 0, 0 };
	ctl_req = req;
	if ((type & 0x60) == 0x00) {                          /* standard */
		switch (req) {
		case 0x00:                                        /* GET_STATUS */
			ctl_p = zero2;
			if ((type & 0x1F) == 2) {                     /* endpoint: halted? */
				int ep = idx & 0x7F;
				if (ep && !ep_valid(idx & 0xFF))
					return -1;
				ctl_buf[0] = ep && ((idx & 0x80) ? (USBD->EPR[ep] & USBD_STAT_TX) == TX_STALL
				                                 : (USBD->EPR[ep] & USBD_STAT_RX) == RX_STALL);
				ctl_buf[1] = 0;
				ctl_p = ctl_buf;
			}
			return 2;
		case 0x01:                                        /* CLEAR_FEATURE */
		case 0x03:                                        /* SET_FEATURE */
			if ((type & 0x1F) == 2 && val == 0 && ep_valid(idx & 0xFF)) {
				halt(idx & 0xFF, req == 0x03);
				return 0;
			}
			return (type & 0x1F) == 0 && val == 1 ? 0 : -1;   /* remote wake-up: accepted, not used */
		case 0x05:                                        /* SET_ADDRESS: after the status stage */
			ctl_addr = val & 0x7F;
			return 0;
		case 0x06: {                                      /* GET_DESCRIPTOR */
			int n = -1;
			switch (val >> 8) {
			case 1: ctl_p = dev_desc; n = sizeof dev_desc; break;
			case 2: ctl_p = cfg_desc; n = sizeof cfg_desc; break;
			case 3: ctl_p = ctl_buf; n = usb_string(val & 0xFF, ctl_buf); break;
			}                                             /* device qualifier, BOS ...: stall (full speed only) */
			return n;
		}
		case 0x08:                                        /* GET_CONFIGURATION */
			ctl_buf[0] = usb_st.configured;
			ctl_p = ctl_buf;
			return 1;
		case 0x09:                                        /* SET_CONFIGURATION */
			if (val > 1)
				return -1;
			configure(val == 1);
			return 0;
		case 0x0A:                                        /* GET_INTERFACE */
			ctl_buf[0] = 0;
			ctl_p = ctl_buf;
			return idx < 4 ? 1 : -1;
		case 0x0B:                                        /* SET_INTERFACE: alternate setting 0 only */
			if (idx >= 4 || val)
				return -1;
			set_interface(idx);
			return 0;
		}
		return -1;
	}
	if ((type & 0x60) == 0x20 && (type & 0x1F) == 1 && (idx & 0xFF) == 2) {   /* CDC, interface 2 */
		switch (req) {
		case 0x20:                                        /* SET_LINE_CODING */
			return len == 7 ? -2 : -1;
		case 0x21:                                        /* GET_LINE_CODING */
			ctl_p = line_coding;
			return 7;
		case 0x22:                                        /* SET_CONTROL_LINE_STATE */
			control_line(val);
			return 0;
		case 0x23:                                        /* SEND_BREAK */
			return 0;
		}
	}
	return -1;
}

static void ep0_setup(void)
{
	uint8_t s[8];
	pma_read(A_EP0_RX, s, 8);
	usb_st.setups++;
	ctl_addr = 0xFF;
	int n = setup(s);
	uint16_t len = s[6] | s[7] << 8;
	if (n == -1) {
		usb_st.stalls++;
		ctl_state = C_IDLE;
		stat_tx(0, TX_STALL);
		stat_rx(0, RX_STALL);                             /* the next SETUP is taken anyway */
	} else if (n == -2) {
		ctl_state = C_OUT;
		stat_rx(0, RX_VALID);
	} else if (n == 0 || !(s[0] & 0x80)) {
		ep0_zlp();
		stat_rx(0, RX_VALID);
	} else {
		ctl_state = C_IN;
		ctl_n = n < len ? n : len;
		ctl_zlp = ctl_n < len && ctl_n % 64 == 0;         /* a short reply that ends on a packet boundary */
		ep0_in();
		stat_rx(0, RX_VALID);                             /* the status stage (OUT, zero length) */
	}
}

static void ep0_out(void)                                 /* OUT data stage or the status stage of an IN transfer */
{
	int n = BT(0, 3) & 0x3FF;
	if (ctl_state == C_OUT) {
		if (ctl_req == 0x20 && n == 7)
			pma_read(A_EP0_RX, line_coding, 7);
		ep0_zlp();
	} else {
		ctl_state = C_IDLE;
	}
	stat_rx(0, RX_VALID);
}

static void ep0_done_in(void)
{
	if (ctl_state == C_IN) {
		if (ctl_n) {
			ep0_in();
		} else if (ctl_zlp) {
			ctl_zlp = 0;
			ep0_in();
		}
	} else if (ctl_state == C_STATUS_IN) {
		if (ctl_addr != 0xFF) {
			USBD->DADDR = USBD_EF | ctl_addr;
			usb_st.addr = ctl_addr;
			ctl_addr = 0xFF;
		}
		ctl_state = C_IDLE;
	}
}

static void bus_reset(void)
{
	static const uint16_t tx[6] = { A_EP0_TX, 0, A_MIDI_TX, A_NOTIF_TX, 0, A_CDC_TX };
	static const uint16_t rx[6] = { A_EP0_RX, A_MIDI_RX, 0, 0, A_CDC_RX, 0 };
	USBD->BTABLE = 0;
	for (int ep = 0; ep < 6; ep++) {
		BT(ep, 0) = tx[ep];
		BT(ep, 1) = 0;
		BT(ep, 2) = rx[ep];
		BT(ep, 3) = rx[ep] ? RX64 : 0;
	}
	ep_open(0, T_CTRL, RX_VALID, TX_NAK);
	configure(0);
	ctl_state = C_IDLE;
	usb_st.addr = 0;
	USBD->DADDR = USBD_EF;                                /* address 0 */
}

void USB_LP_CAN1_RX0_IRQHandler(void) __attribute__((interrupt));
void USB_LP_CAN1_RX0_IRQHandler(void)
{
	uint16_t is;
	while ((is = USBD->ISTR) & USBD_CTR) {
		int ep = is & USBD_EP_ID;
		uint16_t r = USBD->EPR[ep];
		if (r & USBD_CTR_RX) {
			clear_ctr(ep, USBD_CTR_RX);
			if (ep == 0) {
				if (r & USBD_SETUP)
					ep0_setup();
				else
					ep0_out();
			} else if (ep == EP_MIDI_OUT || ep == EP_CDC_OUT) {
				out_packet(ep);
			}
		}
		if (r & USBD_CTR_TX) {
			clear_ctr(ep, USBD_CTR_TX);
			if (ep == 0)
				ep0_done_in();
			else if (ep == EP_MIDI_IN)
				mi_busy = 0;
			else if (ep == EP_CDC_IN)
				c_tx_busy = 0;
		}
	}
	if (is & USBD_RESET) {
		USBD->ISTR = (uint16_t)~USBD_RESET;
		usb_st.resets++;
		bus_reset();
	}
	if (is & (USBD_ERR | USBD_PMAOVR)) {
		USBD->ISTR = (uint16_t)~(USBD_ERR | USBD_PMAOVR);
		usb_st.errors++;
	}
	if (is & USBD_SUSP) {                                 /* the host suspended the bus: the clocks keep running */
		USBD->ISTR = (uint16_t)~USBD_SUSP;
		usb_st.suspends++;
	}
	if (is & USBD_WKUP) {
		USBD->ISTR = (uint16_t)~USBD_WKUP;
		usb_st.resumes++;
	}
}

/* ------------------------------------------------------------------ set-up */
void usb_pullup(int on)
{
	if (on) {
		USBD->CNTR = 0;
		USBD->ISTR = 0;
		USBD->CNTR = USBD_CTRM | USBD_RESETM | USBD_SUSPM | USBD_WKUPM | USBD_ERRM | USBD_PMAOVRM;
		EXTEN->EXTEN_CTR |= EXTEN_USBD_PU_EN;
	} else {
		EXTEN->EXTEN_CTR &= ~EXTEN_USBD_PU_EN;
		USBD->CNTR = USBD_FRES;                           /* detached: the peripheral held in reset (SE0 = bus reset) */
		configure(0);
	}
	usb_st.pullup = on;
}

int usb_pin_check(void)                                   /* bench check, see usbdev.h */
{
	int pu = usb_st.pullup;
	usb_pullup(0);
	int v = pin_probe();
	if (pu)
		usb_pullup(1);
	return v;
}

void usb_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOA | RCC_APB2Periph_AFIO;
	GPIOA->CFGHR = (GPIOA->CFGHR & ~(0xffu << 12)) | (0x4 << 12) | (0x4 << 16);   /* PA11, PA12 floating inputs */
	Delay_Us(100);
	usb_st.dp_boot = (GPIOA->INDR >> 12) & 1;             /* no pull-up yet: 0 with a host (its 15 kOhm pull-down) */
	RCC->CFGR0 = (RCC->CFGR0 & ~RCC_USBPRE) | RCC_USBPRE_DIV3;   /* USB clock: PLL 144 MHz / 3 = 48 MHz */
	RCC->APB1PCENR |= RCC_USBEN;
	USBD->CNTR = USBD_FRES;                               /* powered (PDWN 0), still in reset */
	Delay_Us(10);
	NVIC_SetPriority(USB_LP_CAN1_RX0_IRQn, 0x80);         /* below the frame interrupt */
	NVIC_EnableIRQ(USB_LP_CAN1_RX0_IRQn);
	usb_pullup(1);
}

void usb_poll(void) { usb_tx_poll(); }
int usb_levels(void) { return (GPIOA->INDR >> 11) & 3; }
const char usb_port_name[] = "usbd";
