/* TouchSynth hardware drivers (CH32V003 / CH32V00x, ch32fun) */
#include "board.h"
#include "hw.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#include "ch32v00x_touch.h"                         /* InitTouchADC: ADC clock, calibration (loopback capture) */
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
uint16_t hw_scratch[HW_SCRATCH / 2];
#define dac_buf ((uint8_t *)hw_scratch)
_Static_assert(DAC_RING <= HW_SCRATCH, "DAC ring larger than the shared buffer");
static uint16_t dac_on;                             /* arr of the running carrier, 0 = off */
static uint16_t dac_half;                           /* carrier periods per buffer half */
static uint16_t dac_len;                            /* ring length, bytes */
static uint32_t dac_period;                         /* CPU cycles per buffer half (TIM2 at HCLK: half x 2 arr) */
static uint32_t dac_last;                           /* SysTick at the last render */
static void (*dac_fill)(uint8_t *dst, int n);
static volatile uint8_t dac_busy;                   /* a render is running */
static volatile dac_stats_t dac_st;

static void dac_stats_clear(void)
{
	dac_st.renders = dac_st.fill_max = dac_st.overruns = 0;
	dac_st.slack_min = 0xFFFF;
}

static void tim2_reset(void)                        /* TIM2 back to its reset state: no flag, request or burst state */
{                                                   /* of the previous mode survives */
	RCC->PB1PRSTR |= RCC_TIM2RST;
	RCC->PB1PRSTR &= ~RCC_TIM2RST;
}

/* DMA1 channel 1 (TIM2_CH3 request): half / full transfer = a buffer half has played; render it again. Lowest
   interrupt priority (touchsynth.c): the control tick, the CV interrupt and the UART preempt it, and the main loop
   (console) cannot delay it. The half to render is the one the DMA is not in, so a late interrupt cannot pick the
   wrong one. Overruns: a render that ends after the DMA has entered its half, and halves that played without a
   render (more than 1.5 halves since the last one: the interrupt was blocked). */
void DMA1_Channel1_IRQHandler(void) __attribute__((interrupt));
void DMA1_Channel1_IRQHandler(void)
{
	uint32_t f = DMA1->INTFR;
	DMA1->INTFCR = DMA_CGIF1 | DMA_CHTIF1 | DMA_CTCIF1;
	if (!(f & (DMA_HTIF1 | DMA_TCIF1)) || !dac_on)
		return;
	uint16_t lh = dac_len / 2;
	int h = dac_len - DMA1_Channel1->CNTR < lh;     /* DMA in the first half: render the second */
	dac_busy = 1;
	uint32_t t0 = SysTick->CNT, dt = t0 - dac_last;
	if (dt > dac_period + dac_period / 2)
		dac_st.overruns += (dt + dac_period / 2) / dac_period - 1;
	dac_last = t0;
	dac_fill(dac_buf + h * lh, dac_half);
	uint32_t c = SysTick->CNT - t0;
	uint16_t pos = dac_len - DMA1_Channel1->CNTR;
	dac_busy = 0;
	if ((pos >= lh) == h) {
		dac_st.overruns++;
	} else {
		uint16_t left = (h ? lh - pos : dac_len - pos) / DAC_BPP;
		if (left < dac_st.slack_min)
			dac_st.slack_min = left;
	}
	dac_st.renders++;
	if (c > dac_st.fill_max)
		dac_st.fill_max = c;
}

/* Start sequence: TIM2 from reset, configured while stopped; the DMA channel armed and the CC3 request enabled
   while the counter stands at 0, so the first request is the first compare match after CEN (no stale request can
   be served); the first code is written on that up-count and loaded at the top. */
void hw_dac_start(uint16_t arr, uint16_t half, void (*fill)(uint8_t *dst, int n))
{
	if (half > DAC_HALF)
		half = DAC_HALF;
	if (dac_on == arr && dac_half == half && dac_fill == fill)
		return;
	hw_dac_stop();
	dac_half = half;
	dac_len = 2 * DAC_BPP * half;
	dac_period = (uint32_t)half * 2 * arr;
	dac_fill = fill;
	for (int i = 0; i < dac_len; i += DAC_BPP) {    /* mid-scale until the first render */
		dac_buf[i] = arr / 2;
#if DAC_DUAL
		dac_buf[i + 1] = arr / 2;                   /* CH3: the request compare */
		dac_buf[i + 2] = 0;                         /* CH4: low byte */
#endif
	}
	NVIC_DisableIRQ(TIM2_IRQn);                      /* no sub-oscillator */
	sub_on = 0;
	funDigitalWrite(PIN_SUB, 0);
	TIM2->DMAINTENR = 0;
	tim2_reset();
	TIM2->ATRLR = arr;                               /* up 0...arr, down again: 2 arr ticks (128: 187.5 kHz) */
	TIM2->CHCTLR1 = T_OC_PWM1_LO | T_OC_PWM1_HI;     /* CH1 reset, CH2 pulse: PWM1, preload */
	TIM2->CHCTLR2 = T_OC_FRZ_LO | (DAC_DUAL ? T_OC_PWM1_HI : 0);   /* CH3 compare only, CH4 low byte */
	TIM2->CH1CVR = 0xFFFF;                           /* CH1 (inverted) stays low: DCO held in reset */
	TIM2->CH2CVR = arr / 2;
	TIM2->CH3CVR = arr / 2;                          /* the DMA request, on the up-count (CMS = 10) */
	TIM2->CH4CVR = 0;
	TIM2->CCER = T_CC1E | T_CC1P | T_CC2E | (DAC_DUAL ? T_CC4E : 0);   /* never CC3E: its pin is PD2 (mux S2) */
#if DAC_DUAL
	TIM2->DMACFGR = (2 << 8) | 14;                   /* burst: DBL = 2 (3 transfers) from DBA = 14 (CH2CVR) */
	funPinMode(PIN_SUB, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);   /* PC1 = TIM2 CH4 */
#endif
	TIM2->SWEVGR = T_UG;                             /* load the preloads */
	TIM2->INTFR = 0;
	RCC->AHBPCENR |= RCC_AHBPeriph_DMA1;
	DMA1_Channel1->CFGR = 0;
	DMA1_Channel1->PADDR = DAC_DUAL ? (uint32_t)&TIM2->DMAADR : (uint32_t)&TIM2->CH2CVR;
	DMA1_Channel1->MADDR = (uint32_t)dac_buf;
	DMA1_Channel1->CNTR = dac_len;
	DMA1->INTFCR = DMA_CGIF1 | DMA_CHTIF1 | DMA_CTCIF1;
	DMA1_Channel1->CFGR = DMA_DIR_PeripheralDST | DMA_CFGR1_MINC | DMA_CFGR1_CIRC | DMA_CFGR1_PSIZE_0 |
	                      DMA_CFGR1_PL_1 | DMA_CFGR1_HTIE | DMA_CFGR1_TCIE | DMA_CFGR1_EN;   /* bytes -> 16 bit */
	TIM2->DMAINTENR = TIM2_DMAINTENR_CC3DE;
	dac_stats_clear();
	NVIC_ClearPendingIRQ(DMA1_Channel1_IRQn);
	NVIC_EnableIRQ(DMA1_Channel1_IRQn);
	dac_on = arr;
	dac_last = SysTick->CNT;                         /* the first half has played one dac_period from now */
	TIM2->CTLR1 = T_ARPE | T_CMS2 | T_CEN;
}

void hw_dac_stop(void)
{
	if (!dac_on)
		return;
	TIM2->DMAINTENR = 0;
	DMA1_Channel1->CFGR = 0;
	NVIC_DisableIRQ(DMA1_Channel1_IRQn);
	DMA1->INTFCR = DMA_CGIF1 | DMA_CHTIF1 | DMA_CTCIF1;
	dac_on = 0;
#if DAC_DUAL
	funPinMode(PIN_SUB, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
#endif
	tim2_reset();
	dco_init();                                      /* the engine sets the DCO period at the next tick */
}

int hw_dac_active(void) { return dac_on; }
int hw_dac_rendering(void) { return dac_busy; }
uint16_t hw_dac_count(void) { return dac_on ? DMA1_Channel1->CNTR : 0; }

void hw_dac_stats(dac_stats_t *s, int clear)        /* main loop only (blocks the interrupts) */
{
	__disable_irq();
	if (s) {
		s->renders = dac_st.renders;
		s->fill_max = dac_st.fill_max;
		s->overruns = dac_st.overruns;
		s->slack_min = dac_st.slack_min;
		s->half = dac_on ? dac_half : 0;
	}
	if (clear)
		dac_stats_clear();
	__enable_irq();
}
#else
void hw_dac_start(uint16_t arr, uint16_t half, void (*fill)(uint8_t *dst, int n)) { (void)arr; (void)half; (void)fill; }
void hw_dac_stop(void) {}
int hw_dac_active(void) { return 0; }
int hw_dac_rendering(void) { return 0; }
uint16_t hw_dac_count(void) { return 0; }
void hw_dac_stats(dac_stats_t *s, int clear) { (void)clear; if (s) *s = (dac_stats_t){ 0 }; }
#endif

/* ------------------------------------------------------------------ 595 chain */
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
	/* SRCLK is shared with mux select S1 (CD4051 of the rev 0.1 touch pads): start from a low clock, or the first
	   rising edge would be missing and the first bit (DAC MSB) lost */
	GPIOC->BSHR = 1 << (4 + 16);
	sr_byte(dac);
	sr_byte(leds >> 8);
	sr_byte(leds & 0xFF);
	GPIOD->BSHR = 1 << 4;                           /* RCLK: latch */
	GPIOD->BSHR = 1 << (4 + 16);
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
	/* inputs: loopback analog; MIDI RX with pull-up (the MIDI parts are not populated); the touch pads stay
	   floating inputs (no touch UI in the voice firmware) */
	funPinMode(PIN_AUDIO, GPIO_CNF_IN_ANALOG);
	funPinMode(PIN_MIDI_RX, GPIO_CNF_IN_PUPD);
	funDigitalWrite(PIN_MIDI_RX, 1);

	hw_leds_dac(0, 128);                            /* LEDs off, trim DAC mid-scale */
	InitTouchADC();                                 /* ADC for the loopback capture */
	cv_init();
	dco_init();
	midi_init();
}
