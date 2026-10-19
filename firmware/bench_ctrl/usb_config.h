/* [2026-10-19] Configuration of ch32fun's extralibs/fsusb.c (USBFS on PB6 / PB7) for usbdev_fs.c: one buffer per
 * endpoint number (fsusb.c gives endpoint n buffer n), the descriptors in usb_common.h. */
#ifndef _USB_CONFIG_H
#define _USB_CONFIG_H

#include "funconfig.h"
#include "ch32fun.h"

#define FUSB_BUFFERS_NUMBER  6                            /* EP0 ... EP5, 64 bytes each */
#define FUSB_EP1_MODE        USBFS_EP_MODE_RX             /* 0x01 MIDI OUT */
#define FUSB_EP2_MODE        USBFS_EP_MODE_TX             /* 0x82 MIDI IN */
#define FUSB_EP3_MODE        USBFS_EP_MODE_TX             /* 0x83 CDC notification */
#define FUSB_EP4_MODE        USBFS_EP_MODE_RX             /* 0x04 CDC OUT */
#define FUSB_EP5_MODE        USBFS_EP_MODE_TX             /* 0x85 CDC IN */
#define FUSB_USER_HANDLERS   1
#define FUSB_HID_INTERFACES  0
#define FUSB_HID_USER_REPORTS 0

#include "usb_defines.h"

struct descriptor_list_struct {
	uint32_t lIndexValue;                                 /* wIndex << 16 | wValue */
	const uint8_t *addr;
	uint8_t length;
};
#define DESCRIPTOR_LIST_ENTRIES 6
extern struct descriptor_list_struct descriptor_list[DESCRIPTOR_LIST_ENTRIES];

#endif
