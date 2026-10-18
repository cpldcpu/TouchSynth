/* TouchSynth Poly voice firmware (from TouchSynth firmware 0.1), CH32V006 on board 1 (ch32fun)
 *
 * Timing (interrupt levels: all at the high preemption level except the DAC render, which everything preempts):
 *   TIM1 update  46.875 kHz  dithered CV PWM (4 channels), noise LFSR     (hw.c)
 *   TIM2 update  = pitch     DCO reset / pulse, sub-oscillator toggle     (hw.c)
 *   SysTick      1 kHz       envelopes, LFO, glide, CV laws, tune player  (synth.c, synth_tick)
 *   DMA1 ch1     732 Hz      DAC mode: render the buffer half that has played (lowest level; hw.c, dsp.c)
 *   main loop                MIDI, SWIO console
 * DAC mode: TIM2 CC3 requests DMA1 ch1 once per 187.5 kHz carrier period, which loads the PWM duty from the ring.
 */
#include "board.h"
#include "hw.h"
#include "synth.h"
#include "dsp.h"

void console_poll(void);

#define TICK (F_CPU / 1000)

volatile uint32_t tick_count;                       /* control ticks since reset (console: status) */
volatile uint32_t tick_lat_max, tick_lat_dac_max;   /* control tick entry latency, cycles: worst overall and */
volatile uint32_t tick_dac_n;                       /* while a DAC render ran, ticks during renders, longest */
volatile uint32_t tick_run_max;                     /* tick (cycles; diagnostics) */

void SysTick_Handler(void) __attribute__((interrupt));
void SysTick_Handler(void)
{
	uint32_t t0 = SysTick->CNT, lat = t0 - SysTick->CMP;   /* cycles since the compare match */
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
	tick_count++;
	synth_tick();
	uint32_t run = SysTick->CNT - t0;
	if (run > tick_run_max)
		tick_run_max = run;
}

/* MIDI: note on / off on any channel (running status) */
static void midi_poll(void)
{
	static uint8_t status, d0, n;
	int b;
	while ((b = hw_midi_read()) >= 0) {
		if (b >= 0xF8) continue;                    /* real time */
		if (b & 0x80) { status = b; n = 0; continue; }
		if (n == 0) { d0 = b; n = 1; continue; }
		n = 0;
		uint8_t type = status & 0xF0;
		if (type == 0x90 && b) synth_note_on(d0, b >= 100 ? 2 : 0);   /* high velocity = accent */
		else if (type == 0x80 || type == 0x90) synth_note_off(d0);
	}
}

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

	/* interrupt nesting (INTSYSCR.INESTEN, two levels, no hardware stack): the DAC render at the low preemption
	   level (IPRIOR bit 7), everything else at the high one (reset value 0), so the control tick, the CV PWM and
	   the UART preempt a render; the render preempts the main loop */
	__set_INTSYSCR(__get_INTSYSCR() | 2);
	NVIC_SetPriority(DMA1_Channel1_IRQn, 0x80);

	SysTick->CMP = SysTick->CNT + TICK;
	SysTick->CTLR |= SYSTICK_CTLR_STIE;
	NVIC_EnableIRQ(SysTick_IRQn);

	for (;;) {
		midi_poll();
		console_poll();
	}
}
