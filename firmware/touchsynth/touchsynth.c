/* TouchSynth firmware 0.1 - CH32V003 / CH32V002 / CH32V006 (ch32fun)
 *
 * Timing:
 *   TIM1 update  46.875 kHz  dithered CV PWM (4 channels), noise LFSR     (hw.c)
 *   TIM2 update  = pitch     DCO reset / pulse, sub-oscillator toggle     (hw.c)
 *   SysTick      1 kHz       envelopes, LFO, glide, CV laws, tune player  (synth.c, control_tick)
 *   main loop                touch scan + UI + LEDs, MIDI, SWIO console
 */
#include "board.h"
#include "hw.h"
#include "synth.h"
#include "ui.h"

void console_poll(void);

#define TICK (F_CPU / 1000)

void SysTick_Handler(void) __attribute__((interrupt));
void SysTick_Handler(void)
{
	SysTick->CMP += TICK;
	SysTick->SR = 0;
	synth_tick();
	ui_tick();
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

int main(void)
{
	SystemInit();
	hw_init();
	synth_init();
	ui_init();

	SysTick->CMP = SysTick->CNT + TICK;
	SysTick->CTLR |= SYSTICK_CTLR_STIE;
	NVIC_EnableIRQ(SysTick_IRQn);

	for (;;) {
		ui_poll();
		midi_poll();
		console_poll();
	}
}
