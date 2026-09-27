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
void hw_capture(uint16_t *buf, int n, int period_us)
{
	ADC1->RSQR3 = ADC_CH_AUDIO;
	ADC1->SAMPTR2 = (ADC1->SAMPTR2 & ~ADC_SMP5) | (ADC_SMP5 & (7 << (3 * ADC_CH_AUDIO)));
	uint32_t t = SysTick->CNT;
	for (int i = 0; i < n; i++) {
		while ((int32_t)(SysTick->CNT - t) < 0)
			;
		t += (uint32_t)period_us * (F_CPU / 1000000);
		ADC1->CTLR2 = ADC_SWSTART | ADC_ADON | ADC_EXTSEL;   /* same start sequence as the touch library */
		while (!(ADC1->STATR & ADC_EOC))
			;
		buf[i] = ADC1->RDATAR;
	}
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
