/* TouchSynth Poly voice bus, card side (docs/bus.md): receiver, timed events, replies on the return line */
#ifndef BUS_H
#define BUS_H

#include <stdint.h>

#define BUS_FW_VERSION 0x0003                          /* HELLO: firmware version */

/* bus state (bus.state) */
enum {
	BUS_STANDALONE,                                    /* no SYNC: SysTick ticks, receiver off (bus.md 6) */
	BUS_TRIM,                                          /* SYNC edges: HSITRIM from 100 periods, receiver off */
	BUS_LISTEN,                                        /* receiver on, waiting for FRAME */
	BUS_SYNCED,                                        /* frame counter set by FRAME: timed events run */
	BUS_LOST                                           /* SYNC missing for 10 ticks while synced: VCA muted */
};

typedef struct {                                       /* error and event counters (16 bit, wrapping) */
	uint16_t packets;                                  /* accepted: CRC good and addressed to this card */
	uint16_t crc;                                      /* CRC errors (dropped) */
	uint16_t framing;                                  /* COBS errors: oversize, a code group cut by a delimiter */
	uint16_t uart;                                     /* UART framing / noise / overrun flags (once per tick) */
	uint16_t late;                                     /* timed events for a past frame (run at once) */
	uint16_t far;                                      /* timed events more than 32 frames ahead (dropped) */
	uint16_t qfull;                                    /* timed events dropped: queue full */
	uint16_t slips;                                    /* FRAME against the frame counter: mismatches */
	uint16_t late_ticks;                               /* V_n that reached the DAC renderer late (dsp_late) */
	uint16_t underruns;                                /* DAC buffer halves late or missed (hw_dac_stats) */
	uint16_t sync_gaps;                                /* SysTick ticks that bridged a missing SYNC edge */
	uint16_t repairs;                                  /* VOICE_STATE corrections */
	uint16_t replies;                                  /* replies sent (dropped while the TX is busy: not counted) */
	uint16_t other;                                    /* addressed packets too short, unknown or not supported */
	uint16_t glitches;                                 /* SYNC edges less than 3/4 frame after the last (ignored) */
} bus_stats_t;

typedef struct {
	uint8_t state;                                     /* BUS_* */
	uint8_t addr;                                      /* 0...7, 0xFF = unaddressed */
	uint8_t delay;                                     /* presentation delay D, frames (CONFIG) */
	uint8_t lead;                                      /* the controller's bus lead L (CONFIG; informational) */
	uint8_t slot;                                      /* active patch slot */
	uint8_t slots[4];                                  /* the preset in each patch slot (PATCH_PRESET) */
	uint8_t trims;                                     /* HSITRIM corrections made at start-up */
	uint8_t load;                                      /* CPU load of the tick and the DAC render, % */
	uint16_t frame;                                    /* frame counter (FRAME, bus.md 3) */
	int32_t pbar;                                      /* filtered HCLK cycles per SYNC period, Q8 */
	bus_stats_t st;
} bus_t;

extern bus_t bus;

void bus_init(void);
void bus_tick(uint32_t t, int sync);                   /* control tick, before synth_tick: t = SysTick time of the
                                                          tick, sync = 1 at a SYNC edge, 0 for a SysTick tick */
uint32_t bus_present(uint32_t t);                      /* when what a tick at t computes reaches the outputs: t + D
                                                          frames (bus.md 3.1) */
int32_t bus_ppm(void);                                 /* HSI against SYNC, ppm (from pbar) */
extern uint32_t bus_reply_cycles;                      /* [2026-10-19] cycles of this tick's replies (REQUEST) */

#endif
