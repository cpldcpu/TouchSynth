/* [2026-10-19] USB device of the bench controller on the CH32V203's USBFS (OTG_FS in device mode, PB6 D-, PB7 D+):
 * the development board's USB-C is wired there (bench 2026-10-19: a host's pull-downs on PB6 / PB7, none on PA11 /
 * PA12). The default build; make USB=usbd: usbdev.c (USBD on PA11 / PA12, the backplane's port). Descriptors, data
 * paths and the API: usb_common.h.
 *
 * Built on ch32fun's extralibs/fsusb.c (configuration: usb_config.h), with its user handlers:
 *   HandleSetupCustom  CDC class requests (line coding, DTR); everything else is stalled
 *   HandleDataOut      OUT packets into usb_common.h; flow control: the endpoint is set to NAK when the next packet
 *                      would not fit (fsusb.c leaves it ACK otherwise). fsusb.c toggles the expected DATA0/1 of a
 *                      non-control OUT endpoint without looking at the toggle check: a repeated packet (the host
 *                      missed the ACK) is recognised here (UIS_TOG_OK clear), its toggle restored, its data dropped
 *   HandleInRequest    an IN packet was taken: the endpoint is free
 * fsusb.c handles SET_CONFIGURATION / bus reset itself; usb_poll() follows its state (DevConfig).
 * The interrupt (USBHD_IRQn) runs below the frame interrupt (TIM1_UP).
 */
#include "usb_common.h"
#include "fsusb.h"

static uint8_t s_desc[4][34];                             /* string descriptors, built at start-up */
struct descriptor_list_struct descriptor_list[DESCRIPTOR_LIST_ENTRIES] = {
	{ 0x00000100, dev_desc, sizeof dev_desc },
	{ 0x00000200, cfg_desc, sizeof cfg_desc },
	{ 0x00000300, s_desc[0], 0 },
	{ 0x04090301, s_desc[1], 0 },
	{ 0x04090302, s_desc[2], 0 },
	{ 0x04090303, s_desc[3], 0 },
};

/* ------------------------------------------------------------------ driver hooks of usb_common.h */
static void ep_rx_arm(int ep) { USBFS_SendACK(ep, 0); }

static int ep_tx(int ep, const uint8_t *p, int n)
{
	return USBFS_SendEndpointNEW(ep, (uint8_t *)p, n, 1) ? -1 : 0;   /* busy, or a control transfer runs */
}

static void sync_state(void)                              /* main loop: follow fsusb.c's configuration state */
{
	int on = USBFSCTX.USBFS_DevConfig != 0;
	if (on == usb_st.configured)
		return;
	__disable_irq();
	data_reset(on);
	if (!on)
		usb_st.resets++;                                  /* counted when a configuration is lost (bus reset) */
	__enable_irq();
}

/* ------------------------------------------------------------------ fsusb.c user handlers (interrupt) */
int HandleSetupCustom(struct _USBState *ctx, int code)
{
	usb_st.setups++;
	ctx->pCtrlPayloadPtr = 0;
	if ((ctx->USBFS_SetupReqType & USB_REQ_TYP_MASK) == USB_REQ_TYP_CLASS &&
	    ((ctx->USBFS_IndexValue >> 16) & 0xFF) == 2) {                 /* CDC, interface 2 */
		switch (code) {
		case CDC_SET_LINE_CODING:                         /* 7 bytes follow: HandleDataOut, endpoint 0 */
			return ctx->USBFS_SetupReqLen == 7 ? 7 : 0;
		case CDC_GET_LINE_CODING:
			ctx->pCtrlPayloadPtr = line_coding;
			return 7;
		case CDC_SET_LINE_CTLSTE:
			control_line(ctx->USBFS_IndexValue & 0xFFFF);
			return -1;                                    /* no data stage */
		case CDC_SEND_BREAK:
			return -1;
		}
	}
	usb_st.stalls++;
	return 0;
}

void HandleDataOut(struct _USBState *ctx, int ep, uint8_t *data, int len)
{
	if (ep == 0) {
		if (ctx->USBFS_SetupReqCode == CDC_SET_LINE_CODING && len == 7)
			memcpy(line_coding, data, 7);
		ctx->USBFS_SetupReqLen = 0;                       /* the status stage follows */
		return;
	}
	if (!(USBFS->INT_ST & USBOTG_UIS_TOG_OK)) {           /* a repeated packet */
		UEP_CTRL_RX(ep) ^= USBFS_UEP_R_TOG;
		usb_st.errors++;
		return;
	}
	len = len > 64 ? 64 : len;
	if (ep == EP_MIDI_OUT) {
		uint8_t *s = midi_rx_slot();
		if (!s) {                                         /* armed by a bus reset while full: this packet is lost */
			usb_st.errors++;
			USBFS_SendNAK(ep, 0);
			m_held = 1;
			return;
		}
		memcpy(s, data, len);
		if (!midi_rx_done(len))
			USBFS_SendNAK(ep, 0);
	} else if (ep == EP_CDC_OUT) {
		if (!cdc_rx_put(data, len))
			USBFS_SendNAK(ep, 0);
	}
}

int HandleInRequest(struct _USBState *ctx, int ep, uint8_t *data, int len)
{
	if (ep == EP_MIDI_IN)
		mi_busy = 0;
	else if (ep == EP_CDC_IN)
		c_tx_busy = 0;
	return 0;                                             /* nothing more: NAK */
}

/* ------------------------------------------------------------------ set-up */
void usb_pullup(int on)
{
	if (on) {
		USBFS->UDEV_CTRL |= USBOTG_UD_PORT_EN;
		USBFS->BASE_CTRL |= USBOTG_UC_DEV_PU_EN;
	} else {
		USBFS->BASE_CTRL &= ~USBOTG_UC_DEV_PU_EN;
		USBFS->UDEV_CTRL &= ~USBOTG_UD_PORT_EN;           /* the pins are released */
		USBFSCTX.USBFS_DevConfig = 0;
		sync_state();
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
	for (int i = 0; i < 4; i++)
		descriptor_list[2 + i].length = usb_string(i, s_desc[i]);
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOB;
	usb_st.dp_boot = (GPIOB->INDR >> 7) & 1;              /* PB7 before the pull-up: 0 with a host (15 kOhm) */
	USBFSSetup();                                         /* 48 MHz (PLL / 3), device mode, pull-up on */
	NVIC_SetPriority(USB_IRQn, 0x80);                     /* below the frame interrupt */
	usb_st.pullup = 1;
}

void usb_poll(void)
{
	sync_state();
	usb_st.addr = USBFS->DEV_ADDR & 0x7F;
	usb_tx_poll();
}

int usb_levels(void) { return (GPIOB->INDR >> 6) & 3; }
const char usb_port_name[] = "fs";
