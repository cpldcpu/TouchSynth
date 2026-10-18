/* TouchSynth hardware drivers (CH32V003 / CH32V00x, ch32fun) */
#include "board.h"
#include "hw.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#include "ch32v00x_touch.h"
#pragma GCC diagnostic pop

/* ------------------------------------------------------------------ CV PWM (TIM1) + noise */
static volatile uint16_t cv_code[4];
static volatile uint8_t noise_on;
static uint8_t cv_phase;
static uint16_t lfsr = 0xACE1;

/* 46.875 kHz: load the dithered compare values for the next PWM period and clock the noise LFSR.
   2-bit sigma-delta dither: code = 4 * c10 + f, f of every 4 periods get c10 + 1. */
void TIM1_UP_IRQHandler(void) __attribute__((interrupt)) __attribute__((section(".srodata")));
void TIM1_UP_IRQHandler(void)
{
	TIM1->INTFR = (uint16_t)~T_UIF;
	uint8_t ph = (cv_phase + 1) & 3;
	cv_phase = ph;
	uint16_t c;
	c = cv_code[0]; TIM1->CH1CVR = (c >> 2) + ((c & 3) > ph);
	c = cv_code[1]; TIM1->CH2CVR = (c >> 2) + ((c & 3) > ph);
	c = cv_code[2]; TIM1->CH3CVR = (c >> 2) + ((c & 3) > ph);
	c = cv_code[3]; TIM1->CH4CVR = (c >> 2) + ((c & 3) > ph);
	if (noise_on) {
		uint16_t bit = (lfsr ^ (lfsr >> 2) ^ (lfsr >> 3) ^ (lfsr >> 5)) & 1;
		lfsr = (lfsr >> 1) | (bit << 15);
		GPIOD->BSHR = (lfsr & 1) ? (1 << 0) : (1 << 16);
	}
}

void hw_cv_set(int ch, uint16_t code)
{
	cv_code[ch] = code > 4095 ? 4095 : code;
}

uint16_t hw_cv_get(int ch)
{
	return cv_code[ch];
}

static void cv_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_TIM1;
	TIM1->PSC = 0;
	TIM1->ATRLR = CV_PWM_TOP;                       /* 48 MHz / 1024 = 46.875 kHz */
	TIM1->CHCTLR1 = T_OC_PWM1_LO | T_OC_PWM1_HI;     /* CH1, CH2: PWM1, preload */
	TIM1->CHCTLR2 = T_OC_PWM1_LO | T_OC_PWM1_HI;     /* CH3, CH4 */
	TIM1->CH1CVR = TIM1->CH2CVR = TIM1->CH3CVR = TIM1->CH4CVR = 0;
	TIM1->CCER = T_CC1E | T_CC2E | T_CC3E | T_CC4E; /* main outputs only, never the N outputs */
	TIM1->BDTR = T_MOE;
	TIM1->SWEVGR = T_UG;
	TIM1->CTLR1 = T_ARPE | T_CEN;
	TIM1->INTFR = 0;
	TIM1->DMAINTENR = T_UIE;
	NVIC_EnableIRQ(TIM1_UP_IRQn);
}

/* ------------------------------------------------------------------ DCO (TIM2) */
static volatile uint8_t sub_on;
static uint8_t sub_state;

/* once per oscillator period: toggle the sub-oscillator (one octave down) */
void TIM2_IRQHandler(void) __attribute__((interrupt));
void TIM2_IRQHandler(void)
{
	TIM2->INTFR = (uint16_t)~T_UIF;
	if (sub_on) {
		sub_state ^= 1;
		GPIOC->BSHR = sub_state ? (1 << 1) : (1 << (1 + 16));
	}
}

void hw_dco_set(uint16_t psc, uint16_t arr, uint8_t pw)
{
	uint16_t rst = (RESET_TICKS + psc - 1) / psc;   /* reset pulse >= 3 us */
	TIM2->CTLR1 |= T_UDIS;                           /* take the new values at the next update together */
	TIM2->PSC = psc - 1;
	TIM2->ATRLR = arr - 1;
	TIM2->CH1CVR = rst;
	TIM2->CH2CVR = pw ? (uint16_t)(((uint32_t)arr * pw) >> 8) : 0;
	TIM2->CTLR1 &= ~T_UDIS;
}

void hw_dco_waves(int sub, int noise)
{
	sub_on = sub;
	if (!sub)
		funDigitalWrite(PIN_SUB, 0);
	noise_on = noise;
	if (!noise)
		funDigitalWrite(PIN_NOISE, 0);
}

static void dco_init(void)
{
	RCC->APB1PCENR |= RCC_APB1Periph_TIM2;
	TIM2->PSC = 0;
	TIM2->ATRLR = 0xFFFF;
	TIM2->CHCTLR1 = T_OC_PWM1_LO | T_OC_PWM1_HI;     /* CH1 reset, CH2 pulse */
	TIM2->CCER = T_CC1E | T_CC1P | T_CC2E;           /* CH1 inverted: low during the first 3 us (reset) */
	TIM2->CH1CVR = RESET_TICKS;
	TIM2->CH2CVR = 0;
	TIM2->SWEVGR = T_UG;
	TIM2->CTLR1 = T_ARPE | T_CEN;
	TIM2->INTFR = 0;
	TIM2->DMAINTENR = T_UIE;
	NVIC_EnableIRQ(TIM2_IRQn);
}

/* ------------------------------------------------------------------ PWM DAC on the pulse pin (DAC mode) */
#if defined(CH32V006)
#define DAC_BUF (2 * DAC_HALF * DAC_EPS)
uint16_t hw_scratch[2048];
#define dac_buf ((uint8_t *)hw_scratch)
_Static_assert(DAC_BUF <= sizeof hw_scratch, "DAC ring larger than the shared buffer");
static volatile uint8_t dac_need;                   /* bit 0: first half has played, bit 1: second half */
static uint8_t dac_on;
static volatile uint16_t dac_overruns;              /* a half was due again before it had been refilled */
static uint16_t dac_fill_max;                       /* longest refill, us */
static uint16_t dac_gap_max;                        /* longest time between two polls, us */
static uint32_t dac_last_poll;

/* DMA1 channel 2 serves the TIM2 update request: half / full transfer = a buffer half to refill */
void DMA1_Channel2_IRQHandler(void) __attribute__((interrupt));
void DMA1_Channel2_IRQHandler(void)
{
	uint32_t f = DMA1->INTFR;
	uint8_t due = ((f & DMA_HTIF2) ? 1 : 0) | ((f & DMA_TCIF2) ? 2 : 0);
	if (dac_need & due)
		dac_overruns++;
	dac_need |= due;
	DMA1->INTFCR = DMA_CHTIF2 | DMA_CTCIF2 | DMA_CGIF2;
}

void hw_dac_start(void)
{
	if (dac_on)
		return;
	for (int i = 0; i < DAC_BUF; i++)
		dac_buf[i] = 128;
	NVIC_DisableIRQ(TIM2_IRQn);                      /* no sub-oscillator */
	sub_on = 0;
	funDigitalWrite(PIN_SUB, 0);
	TIM2->DMAINTENR = 0;
	TIM2->CTLR1 = 0;                                 /* the counting mode may only change while stopped */
	TIM2->PSC = 0;
	TIM2->ATRLR = 256;                               /* up 0...256, down again: 512 ticks, 93.75 kHz */
	TIM2->CH1CVR = 0xFFFF;                           /* CH1 (inverted) stays low: DCO held in reset */
	TIM2->CH2CVR = 128;
	TIM2->CNT = 0;
	TIM2->SWEVGR = T_UG;
	TIM2->CTLR1 = T_ARPE | T_CMS1 | T_CEN;
	RCC->AHBPCENR |= RCC_AHBPeriph_DMA1;
	DMA1_Channel2->CFGR = 0;
	DMA1_Channel2->PADDR = (uint32_t)&TIM2->CH2CVR;
	DMA1_Channel2->MADDR = (uint32_t)dac_buf;
	DMA1_Channel2->CNTR = DAC_BUF;
	DMA1_Channel2->CFGR = DMA_DIR_PeripheralDST | DMA_CFGR1_MINC | DMA_CFGR1_CIRC | DMA_CFGR1_PSIZE_0 |
	                      DMA_CFGR1_PL_1 | DMA_CFGR1_HTIE | DMA_CFGR1_TCIE;   /* bytes -> 16-bit register */
	DMA1->INTFCR = DMA_CHTIF2 | DMA_CTCIF2 | DMA_CGIF2;
	dac_need = 0;
	dac_overruns = dac_fill_max = dac_gap_max = 0;
	dac_last_poll = 0;
	NVIC_EnableIRQ(DMA1_Channel2_IRQn);
	DMA1_Channel2->CFGR |= DMA_CFGR1_EN;
	TIM2->DMAINTENR = T_UDE;
	dac_on = 1;
}

void hw_dac_stop(void)
{
	if (!dac_on)
		return;
	TIM2->DMAINTENR = 0;
	DMA1_Channel2->CFGR &= ~DMA_CFGR1_EN;
	NVIC_DisableIRQ(DMA1_Channel2_IRQn);
	TIM2->CTLR1 = 0;                                 /* back to edge-aligned counting for the DCO */
	TIM2->CH2CVR = 0;
	TIM2->CH1CVR = RESET_TICKS;                      /* the engine sets the DCO period at the next tick */
	TIM2->CNT = 0;
	TIM2->CTLR1 = T_ARPE | T_CEN;
	TIM2->INTFR = 0;
	TIM2->DMAINTENR = T_UIE;
	NVIC_EnableIRQ(TIM2_IRQn);
	dac_on = 0;
}

int hw_dac_active(void) { return dac_on; }

void hw_dac_poll(void (*fill)(uint8_t *dst, int n))
{
	if (!dac_on)
		return;
	uint32_t now = SysTick->CNT, gap = (now - dac_last_poll) / (F_CPU / 1000000);
	if (dac_last_poll && gap > dac_gap_max)
		dac_gap_max = gap > 65535 ? 65535 : gap;
	dac_last_poll = now;
	for (int h = 0; h < 2; h++) {
		if (dac_need & (1 << h)) {
			__disable_irq();
			dac_need &= ~(1 << h);
			__enable_irq();
			uint32_t t0 = SysTick->CNT;
			fill(dac_buf + h * DAC_HALF * DAC_EPS, DAC_HALF);
			uint32_t us = (SysTick->CNT - t0) / (F_CPU / 1000000);
			if (us > dac_fill_max)
				dac_fill_max = us > 65535 ? 65535 : us;
		}
	}
}

uint16_t hw_dac_count(void) { return dac_on ? DMA1_Channel2->CNTR : 0; }
void hw_dac_stats(uint16_t *o, uint16_t *m, uint16_t *g) { *o = dac_overruns; *m = dac_fill_max; *g = dac_gap_max; }
#else
void hw_dac_start(void) {}
void hw_dac_stop(void) {}
int hw_dac_active(void) { return 0; }
void hw_dac_poll(void (*fill)(uint8_t *dst, int n)) { (void)fill; }
uint16_t hw_dac_count(void) { return 0; }
void hw_dac_stats(uint16_t *o, uint16_t *m, uint16_t *g) { *o = *m = *g = 0; }
#endif

/* ------------------------------------------------------------------ 595 chain and mux select */
static void mux_select(int ch)
{
	GPIOC->BSHR = ((ch & 1) ? (1 << 3) : (1 << (3 + 16))) | ((ch & 2) ? (1 << 4) : (1 << (4 + 16)));
	GPIOD->BSHR = (ch & 4) ? (1 << 2) : (1 << (2 + 16));
}

static void sr_byte(uint8_t b)
{
	for (int i = 7; i >= 0; i--) {                 /* MSB first: bit 7 ends up on QH */
		GPIOC->BSHR = (b & (1 << i)) ? (1 << 3) : (1 << (3 + 16));
		GPIOC->BSHR = 1 << 4;                       /* SRCLK rising edge */
		GPIOC->BSHR = 1 << (4 + 16);
	}
}

/* chain: MCU -> U7 (LEDs 0-7) -> U8 (LEDs 8-15) -> U9 (trim DAC): the DAC byte goes first */
void hw_leds_dac(uint16_t leds, uint8_t dac)
{
	/* SRCLK is shared with mux select S1: a touch scan ends on channel 7 and leaves it high, so the first rising
	   edge would be missing and the first bit (DAC MSB) lost. Start from a low clock. */
	GPIOC->BSHR = 1 << (4 + 16);
	sr_byte(dac);
	sr_byte(leds >> 8);
	sr_byte(leds & 0xFF);
	GPIOD->BSHR = 1 << 4;                           /* RCLK: latch */
	GPIOD->BSHR = 1 << (4 + 16);
}

/* ------------------------------------------------------------------ touch */
/* mux select n on U5 reads pad n (keys 1-8), on U6 pad 8 + n (keys 9-16) */
void hw_touch_scan(uint32_t raw[16], int iterations)
{
	for (int ch = 0; ch < 8; ch++) {
		mux_select(ch);
		Delay_Us(5);                               /* CD4051 switching + settling */
		raw[ch] = ReadTouchPin(GPIOA, 2, ADC_CH_TOUCH_A, iterations);
		raw[8 + ch] = ReadTouchPin(GPIOA, 1, ADC_CH_TOUCH_B, iterations);
	}
}

/* ------------------------------------------------------------------ audio loopback capture */
uint32_t hw_capture(uint16_t *buf, int n, int period_us)
{
	return hw_capture_ch(ADC_CH_AUDIO, buf, n, period_us);
}

/* Sample time code 3 (~30 ADC clocks): the longest code (7) made one conversion ~11.8 us on the V006, so captures
   requested at 10 us ran slow. The 1 nF loopback capacitor supplies the sampling charge. */
#define CAP_SMP 3u
uint32_t hw_capture_ch(int ch, uint16_t *buf, int n, int period_us)
{
	ADC1->RSQR3 = ch;
	ADC1->SAMPTR2 = (ADC1->SAMPTR2 & ~(7u << (3 * ch))) | (CAP_SMP << (3 * ch));
	uint32_t t = SysTick->CNT, t0 = t;
	for (int i = 0; i < n; i++) {
		while ((int32_t)(SysTick->CNT - t) < 0)
			;
		t += (uint32_t)period_us * (F_CPU / 1000000);
#if defined(CH32V00x)
		ADC1->CTLR2 = ADC_ADON | ADC_EXTSEL;               /* V00x: re-arm before every software start, as the */
#endif                                                     /* touch library does (without it the V006 hung here) */
		ADC1->CTLR2 = ADC_SWSTART | ADC_ADON | ADC_EXTSEL;
		uint32_t guard = 10000;
		while (!(ADC1->STATR & ADC_EOC) && --guard)
			;
		buf[i] = guard ? ADC1->RDATAR : 0xFFFF;            /* 0xFFFF marks a conversion that never finished */
	}
	return (SysTick->CNT - t0) / (F_CPU / 1000000);       /* > n * period_us if the loop could not keep up */
}

/* ------------------------------------------------------------------ MIDI (USART1 RX on PD6, 31250 Bd) */
static volatile uint8_t midi_buf[32];
static volatile uint8_t midi_w, midi_r;

void USART1_IRQHandler(void) __attribute__((interrupt));
void USART1_IRQHandler(void)
{
	if (USART1->STATR & USART_STATR_RXNE) {
		uint8_t b = USART1->DATAR;
		uint8_t w = (midi_w + 1) & 31;
		if (w != midi_r) {
			midi_buf[midi_w] = b;
			midi_w = w;
		}
	}
}

int hw_midi_read(void)
{
	if (midi_r == midi_w)
		return -1;
	uint8_t b = midi_buf[midi_r];
	midi_r = (midi_r + 1) & 31;
	return b;
}

static void midi_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_USART1;
	USART1->BRR = F_CPU / 31250;
	USART1->CTLR1 = USART_CTLR1_UE | USART_CTLR1_RE | USART_CTLR1_RXNEIE;   /* receive only: PD5 is the ADC */
	NVIC_EnableIRQ(USART1_IRQn);
}

/* ------------------------------------------------------------------ init */
void hw_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOA | RCC_APB2Periph_GPIOC | RCC_APB2Periph_GPIOD |
	                  RCC_APB2Periph_AFIO | RCC_APB2Periph_ADC1;
	AFIO->PCFR1 = (AFIO->PCFR1 & ~REMAP_MASK) | REMAP_BITS;

	/* timer outputs */
	funPinMode(PIN_CV_AMP, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);
	funPinMode(PIN_CV_CUT, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);
	funPinMode(PIN_CV_RES, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);
	funPinMode(PIN_CV_VCA, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);
	funDigitalWrite(PIN_DCO_RST, 1);                /* idle high = reset switch off */
	funPinMode(PIN_DCO_RST, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);
	funPinMode(PIN_PULSE, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);
	/* GPIO outputs */
	funDigitalWrite(PIN_SUB, 0);    funPinMode(PIN_SUB, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
	funDigitalWrite(PIN_NOISE, 0);  funPinMode(PIN_NOISE, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
	funDigitalWrite(PIN_S0_DATA, 0); funPinMode(PIN_S0_DATA, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
	funDigitalWrite(PIN_S1_CLK, 0); funPinMode(PIN_S1_CLK, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
	funDigitalWrite(PIN_S2, 0);     funPinMode(PIN_S2, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
	funDigitalWrite(PIN_LATCH, 0);  funPinMode(PIN_LATCH, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
	/* inputs: loopback analog; MIDI RX with pull-up (the MIDI parts are not populated) */
	funPinMode(PIN_AUDIO, GPIO_CNF_IN_ANALOG);
	funPinMode(PIN_MIDI_RX, GPIO_CNF_IN_PUPD);
	funDigitalWrite(PIN_MIDI_RX, 1);

	hw_leds_dac(0, 128);                            /* LEDs off, trim DAC mid-scale */
	InitTouchADC();                                 /* ADC for touch and loopback (touch pins set up per read) */
	cv_init();
	dco_init();
	midi_init();
}
