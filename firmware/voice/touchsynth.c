/* TouchSynth Poly voice firmware (from TouchSynth firmware 0.1), CH32V006 on board 1 (ch32fun)
 *
 * Timing (interrupt levels: all at the high preemption level except the DAC render, which everything preempts):
 *   TIM1 update  46.875 kHz  dithered CV PWM (4 channels), noise LFSR     (hw.c)
 *   TIM2 update  = pitch     DCO reset / pulse, sub-oscillator toggle     (hw.c)
 *   control tick 1 kHz       voice bus (card), envelopes, LFO, glide, CV laws, tune player (bus.c, synth.c)
 *                            card: the SYNC edge (EXTI4, PD4), SysTick only while SYNC is missing; board 1: SysTick
 *   DMA1 ch1     732 Hz      DAC mode: render the buffer half that has played (lowest level; hw.c, dsp.c)
 *   main loop                MIDI (board 1), SWIO console
 * DAC mode: TIM2 CC3 requests DMA1 ch1 once per 187.5 kHz carrier period, which loads the PWM duty from the ring.
 * Card: what the tick computes reaches the outputs D frames later (CV delay line, queued DAC voice state; bus.md
 * 3.1), so all cards sound an event at the same moment.
 */
#include "board.h"
#include "hw.h"
#include "synth.h"
#include "dsp.h"
#include "bus.h"

void console_poll(void);

#define TICK (F_CPU / 1000)

volatile uint32_t tick_count;                       /* control ticks since reset (console: status) */
volatile uint32_t tick_lat_max, tick_lat_dac_max;   /* control tick entry latency, cycles: worst overall and */
volatile uint32_t tick_dac_n;                       /* while a DAC render ran, ticks during renders, longest */
volatile uint32_t tick_run_max;                     /* tick (cycles; diagnostics) */
volatile uint32_t tick_core_max;                    /* [2026-10-19] card: the same without the bus replies */

/* the control tick: t = its SysTick time (SYNC edge or compare match), sync = 1 at a SYNC edge */
static void control_tick(uint32_t t, int sync)
{
	uint32_t t0 = SysTick->CNT;
	tick_count++;
#if BOARD_CARD
	bus_tick(t, sync);                              /* frame counter, bus receiver, events due now */
#else
	(void)t; (void)sync;
#endif
	synth_tick();
	hw_cv_commit();
#if defined(CH32V006)
	dsp_commit(BOARD_CARD ? bus_present(t) : 0);    /* board 1: no presentation delay */
#endif
	uint32_t run = SysTick->CNT - t0;
	if (run > tick_run_max)
		tick_run_max = run;
	hw_busy_cycles += run;
#if BOARD_CARD
	run -= bus_reply_cycles;                        /* a REQUEST's reply: up to 10 k cycles, on demand only */
	if (run > tick_core_max)
		tick_core_max = run;
#endif
}

/* SysTick: the tick on board 1; on the card only while SYNC is missing (standalone, or bridging a lost edge) */
void SysTick_Handler(void) __attribute__((interrupt));
void SysTick_Handler(void)
{
	uint32_t t = SysTick->CMP, lat = SysTick->CNT - t;   /* cycles since the compare match */
	if (lat > tick_lat_max)
		tick_lat_max = lat;
	if (hw_dac_rendering()) {                       /* preempted the render (nesting, main) */
		tick_dac_n++;
		if (lat > tick_lat_dac_max)
			tick_lat_dac_max = lat;
	}
	SysTick->CMP += TICK;
	if ((int32_t)(SysTick->CMP - SysTick->CNT) <= 0)  /* interrupts were blocked for more than a tick: resync, */
		SysTick->CMP = SysTick->CNT + TICK;         /* or the next match would only come after a counter wrap */
	SysTick->SR = 0;
	control_tick(t, 0);
}

#if BOARD_CARD
void sync_tick(uint32_t t)                          /* SYNC interrupt (hw.c), same preemption level as SysTick */
{
	static uint32_t t_last;
	if (t - t_last < TICK * 3 / 4) {                /* not a frame edge: noise on the line (the bench's SYNC wire */
		bus.st.glitches++;                          /* shows them 0.5 ms after the edge, at the falling edge) */
		return;
	}
	t_last = t;
	SysTick->CMP = t + TICK + TICK / 4;             /* SysTick takes over if the next edge is 0.25 ms late */
	SysTick->SR = 0;
	NVIC_ClearPendingIRQ(SysTick_IRQn);
	control_tick(t, 1);
}
#else
/* MIDI: note on / off and program change (preset) on any channel (running status) */
static void midi_poll(void)
{
	static uint8_t status, d0, n;
	int b;
	while ((b = hw_midi_read()) >= 0) {
		if (b >= 0xF8) continue;                    /* real time */
		if (b & 0x80) { status = b; n = 0; continue; }
		if ((status & 0xF0) == 0xC0) { synth_preset(b); continue; }     /* one data byte; main loop context */
		if (n == 0) { d0 = b; n = 1; continue; }
		n = 0;
		uint8_t type = status & 0xF0;
		if (type == 0x90 && b) synth_note_on(d0, b >= 100 ? 2 : 0);   /* high velocity = accent */
		else if (type == 0x80 || type == 0x90) synth_note_off(d0);
	}
}
#endif

/* stack low-water mark: the free RAM between .bss and the stack is filled with a pattern at start-up */
#define STACK_FILL 0xA5A5A5A5u
extern uint32_t _ebss[];

static void stack_paint(void)
{
	uint32_t *sp;
	__asm volatile("mv %0, sp" : "=r"(sp));
	for (uint32_t *p = _ebss; p < sp - 16; p++)
		*p = STACK_FILL;
}

uint32_t stack_free(void)                           /* bytes never used by the stack since reset */
{
	uint32_t *p = _ebss;
	while (*p == STACK_FILL)
		p++;
	return (uint32_t)(p - _ebss) * 4;
}

int main(void)
{
	SystemInit();
	stack_paint();
	hw_init();
	synth_init();
#if BOARD_CARD
	bus_init();
#endif

	/* interrupt nesting (INTSYSCR.INESTEN, two levels, no hardware stack): the DAC render at the low preemption
	   level (IPRIOR bit 7), everything else at the high one (reset value 0), so the control tick, the CV PWM and
	   the UART preempt a render; the render preempts the main loop */
	__set_INTSYSCR(__get_INTSYSCR() | 2);
	NVIC_SetPriority(DMA1_Channel1_IRQn, 0x80);

	SysTick->CMP = SysTick->CNT + TICK;
	SysTick->CTLR |= SYSTICK_CTLR_STIE;
	NVIC_EnableIRQ(SysTick_IRQn);

	for (;;) {
#if !BOARD_CARD
		midi_poll();                                /* the card's bus runs in the control tick (bus.c) */
#endif
		console_poll();
	}
}
