/* [2026-10-19] USB device of the bench controller: a composite of a class-compliant USB-MIDI 1.0 function and a CDC
 * ACM serial port (usb_common.h). Two drivers with this API: usbdev_fs.c (USBFS, PB6 / PB7: the development board's
 * USB-C, the default build) and usbdev.c (USBD, PA11 / PA12: the backplane's port, make USB=usbd).
 */
#ifndef USBDEV_H
#define USBDEV_H

#include <stdint.h>

void usb_init(void);                                      /* 48 MHz USB clock (PLL / 3), pins, peripheral, pull-up on */
void usb_pullup(int on);                                  /* the internal D+ pull-up: attach / detach */
void usb_poll(void);                                      /* main loop: follow the state, send CDC output */
int usb_levels(void);                                     /* the bus lines now: bit 0 D-, bit 1 D+ */
extern const char usb_port_name[];                        /* "fs" (USBFS, PB6 / PB7) or "usbd" (USBD, PA11 / PA12) */

/* bench check (detaches for about 20 ms): bits 0, 1 PA11, PA12 and bits 4, 5 PB6, PB7 with the GPIO pull-ups, bits
   2, 3 and 6, 7 with the pull-downs (a host's 15 kOhm pull-downs read 0 against a pull-up); bits 8-13 PA12 and the
   USBD pull-up (EXTEN_USBD_PU_EN): on against the GPIO pull-down, USBD in reset / running; floating from 0 V, on /
   off; with the GPIO pull-up, on / off. pu_time: PA12 edge times in HCLK ticks (usb_common.h pin_probe) */
int usb_pin_check(void);
extern uint32_t pu_time[13];

/* MIDI OUT (host -> device): received packets of 4-byte USB-MIDI events, in arrival order. n: bytes (a multiple of
   4), stamp: usb_stamp() at the arrival. 0: none */
int usb_midi_get(uint8_t *p, uint32_t *stamp);
int usb_midi_send(const uint8_t *p, int n);               /* MIDI IN (device -> host), up to 64 bytes; -1: busy */
int usb_midi_inject(const uint8_t *p, int n);             /* bench: a packet into the OUT path as if received (the
                                                             main loop parses it as any); -1: no free slot */

/* CDC data */
int usb_cdc_ready(void);                                  /* configured, and the host holds DTR (a program has the port
                                                             open) */
int usb_cdc_getc(void);                                   /* -1: no byte */
int usb_cdc_putc(int c);                                  /* -1: no room; 0 (dropped) when not ready */
int usb_cdc_pending(void);                                /* output not yet taken by the host */
uint32_t usb_cdc_stamp(void);                             /* usb_stamp() at the arrival of the last CDC packet */

uint32_t usb_stamp(void);                                 /* the application's time stamp (frame << 16 | us) */

/* status and counters */
typedef struct {
	uint8_t configured, dtr, addr, pullup, dp_boot;        /* dp_boot: D+ before the pull-up (an external pull-up would
	                                                          read 1 with a host attached) */
	uint32_t resets, suspends, resumes, setups, stalls, errors;   /* fs: resets = configurations lost; setups and
	                                                                 stalls: class requests only */
	uint32_t midi_pkts, midi_bytes, midi_held;            /* OUT packets, bytes; times the endpoint was left NAKing */
	uint32_t midi_in_pkts;
	uint32_t cdc_rx, cdc_tx, cdc_held, cdc_drop;          /* bytes in / out; times held; output bytes dropped */
} usb_stats_t;
extern usb_stats_t usb_st;

#endif
