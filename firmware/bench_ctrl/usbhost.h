/* [2026-10-20] USB host of the bench controller: a minimal USB-MIDI host on the CH32V203's USBFS (OTG_FS in host
 * mode, PB6 D-, PB7 D+), the backplane's host port (backplane.md 4.2: USB-A J2, TPS2051C U4 with HOST_EN on PB8 and
 * HOST_FLT_N on PB9). Build: make USBH=1 (usbhost.c; the USB device then runs on USBD, PA11 / PA12, usbdev.c).
 *
 * Root port only (no hubs), full and low speed: attach / detach, bus reset, enumeration, the first Audio class MIDI
 * Streaming interface with an IN endpoint (bulk or interrupt) and its OUT endpoint if present; the IN endpoint is
 * polled at most once per USB frame, its USB-MIDI event packets are handed to the main loop (usbh_midi_get), which
 * runs them through the same MIDI -> bus path as the USB device and the PC command 'e'. Everything runs in the main
 * loop (usbh_poll from idle()); no interrupt, no critical section.
 */
#ifndef USBHOST_H
#define USBHOST_H

#include <stdint.h>

void usbh_init(void);                                     /* host mode on USBFS, then the port power (HOST_EN) on */
void usbh_poll(void);                                     /* main loop: attach, enumeration, polling, faults */
void usbh_power(int on);                                  /* the port power (HOST_EN, PB8); off: the device detaches */
void usbh_restart(void);                                  /* drop the device and enumerate it again (bus reset) */

/* received USB-MIDI event packets (4 bytes per event), in arrival order; n: bytes, stamp: usb_stamp() at the
   transfer's completion. 0: none */
int usbh_midi_get(uint8_t *p, uint32_t *stamp);
int usbh_midi_send(const uint8_t *p, int n);              /* to the device's MIDI OUT endpoint (up to its packet size);
                                                             -1: no OUT endpoint, not running, or one still pending */

/* bench check (the port is dropped for about 10 ms, interrupts off for at most 50 us at a time): the D+ / D- pull-
   downs, see usbhost.c; writes one text line (without '\n') into s, returns its length */
int usbh_pd_probe(char *s, int n);
int usbh_descriptors(const uint8_t **dev, const uint8_t **conf);   /* the device descriptor (18 bytes) and the
                                                             configuration descriptor; returns its length, 0: none */

enum { HS_OFF, HS_WAIT, HS_DEBOUNCE, HS_RESET, HS_RECOVER, HS_ENUM, HS_RUN, HS_NOMIDI, HS_FAILED, HS_FAULT };

typedef struct {
	uint8_t state, speed, addr, power, flt;               /* speed: 1 full, 0 low; flt: HOST_FLT_N level */
	uint8_t ep_in, ep_out, in_type, interval, ms_if, ms_alt; /* the MIDI streaming interface and its endpoints */
	uint16_t vid, pid, in_size, out_size, enum_ms;        /* enum_ms: attach (debounced) -> running */
	char product[33];
	uint32_t attaches, detaches, enums, enum_fails, resets, faults;
	uint32_t sofs, polls, naks, pkts, bytes, tog_err, errors, stalls, ring_full, late_sof, outs;
	uint16_t sof_age_max;                                 /* us after the SOF at which a poll started */
	uint16_t cpu_max;                                     /* us in one usbh_poll call */
	uint32_t cpu_sum;                                     /* us in usbh_poll calls that did work, since the last clear */
	uint32_t ctl_naks, xfer_err;                          /* control transfers: NAKs, failed transactions */
	uint8_t last_err, last_res;                           /* the last error code (usbhost.c HE_*), the handshake PID */
} usbh_stats_t;
extern usbh_stats_t uh;
void usbh_clear(void);                                    /* the counters (not the device's identity) */

#endif
