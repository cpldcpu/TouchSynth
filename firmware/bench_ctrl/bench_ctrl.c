/* TouchSynth Poly bench controller (CH32V203 development board), step 1: an Ardulink-compatible SWIO programmer.
 *
 * minichlink on the lab PC flashes and debugs a CH32V006 through the V203, the path the backplane will use to
 * update the voice cards:   minichlink -C ardulink -c /dev/ttyACMx -w voice.bin flash -b
 *
 *   USART1  PA9 TX, PA10 RX   115200 8N1, Ardulink: '?' sync -> '!', 'w' reg val32 -> '+', 'r' reg -> val32,
 *                             'p' / 'P' (target power, not switchable here) -> '+'; values little-endian
 *   SWIO    PB13              open drain, external pull-up: WCH one-wire debug protocol, bit-banged
 *   NRST    PB12              open drain, released (the V006 runs)
 *   SYNC    PA8               TIM1 CH1, 1 kHz square: the frame clock of the voice bus (docs/bus.md), from
 *                             the 8 MHz crystal (HSE, PLL x18: 144 MHz)
 *
 * One-wire protocol (as PicoRVD's singlewire.pio), T = 125 ns = the target's 8 MHz debug clock: every bit is a low
 * pulse of 2 T (raw 0) or 8 T (raw 1), then 3 T released. A frame is a start pulse (2 T low, 3 T released), the
 * header ((~reg) << 1 | read) as 8 bits MSB first, then 32 data bits: a write sends ~value; a read pulls the line
 * low for 1 T per bit and samples at 5 T (the target holds the line low for a 0), 11 T per bit. Then at least 18 T
 * released. minichlink itself writes the debug-module setup (DMSHDWCFGR, DMCFGR, DMCONTROL) after the sync.
 */
#include "ch32fun.h"
#include <stdio.h>

#if FUNCONF_SYSTEM_CORE_CLOCK != 144000000
#error "the SWIO timing assumes HCLK = 144 MHz"
#endif

#define T        (FUNCONF_SYSTEM_CORE_CLOCK / 8000000)   /* 125 ns in SysTick (HCLK) ticks */
#define SWIO     (1u << 13)                               /* PB13 */
#define NRST     (1u << 12)                               /* PB12 */

static uint32_t t_;                                       /* running deadline: the bit timing does not accumulate jitter */

static inline uint32_t now(void) { return *(volatile uint32_t *)&SysTick->CNT; }
static inline void until(uint32_t t) { while ((int32_t)(now() - t) < 0) ; }
static inline void low_for(int n) { GPIOB->BCR = SWIO; t_ += n * T; until(t_); }
static inline void rel_for(int n) { GPIOB->BSHR = SWIO; t_ += n * T; until(t_); }

static void send_bits(uint32_t v, int n)
{
	for (int i = n - 1; i >= 0; i--) {
		low_for(((v >> i) & 1) ? 8 : 2);
		rel_for(3);
	}
}

static void frame_start(uint8_t header)
{
	t_ = now() + T;
	until(t_);
	low_for(2);                                       /* start */
	rel_for(3);
	send_bits(header, 8);
}

static void swio_write(uint8_t reg, uint32_t v)
{
	__disable_irq();
	frame_start((uint8_t)((~reg) << 1));
	send_bits(~v, 32);
	rel_for(18);
	__enable_irq();
}

static uint32_t swio_read(uint8_t reg)
{
	uint32_t v = 0;
	__disable_irq();
	frame_start((uint8_t)(((~reg) << 1) | 1));
	for (int i = 0; i < 32; i++) {
		uint32_t t0 = t_;
		GPIOB->BCR = SWIO;
		t_ = t0 + T;      until(t_);
		GPIOB->BSHR = SWIO;
		t_ = t0 + 5 * T;  until(t_);
		v = (v << 1) | ((GPIOB->INDR & SWIO) ? 1 : 0);
		t_ = t0 + 11 * T; until(t_);
	}
	rel_for(18);
	__enable_irq();
	return v;
}

static void swio_line_reset(void)                         /* about 8 us low, then idle (PicoRVD's reset) */
{
	GPIOB->BCR = SWIO;
	Delay_Us(8);
	GPIOB->BSHR = SWIO;
	Delay_Us(100);
}

static int uart_getc(void)
{
#ifdef UART_DIAG                                          /* wiring check: '#' every second, received bytes on the console */
	uint32_t t = now();
	while (!(USART1->STATR & USART_STATR_RXNE))
		if ((int32_t)(now() - t) > (int32_t)FUNCONF_SYSTEM_CORE_CLOCK) {
			USART1->DATAR = '#';
			t = now();
		}
	int c = USART1->DATAR & 0xff;
	printf("rx %02x\n", c);
	return c;
#else
	while (!(USART1->STATR & USART_STATR_RXNE)) ;
	return USART1->DATAR & 0xff;
#endif
}

static void uart_putc(int c)
{
	while (!(USART1->STATR & USART_STATR_TXE)) ;
	USART1->DATAR = (uint8_t)c;
}

static void hw_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_AFIO | RCC_APB2Periph_GPIOA | RCC_APB2Periph_GPIOB | RCC_APB2Periph_USART1 |
	                  RCC_APB2Periph_TIM1;
	/* PA8 TIM1 CH1 and PA9 USART1 TX: AF push-pull 50 MHz; PA10 USART1 RX: floating input */
	GPIOA->CFGHR = (GPIOA->CFGHR & ~0xfffu) | 0xb | (0xb << 4) | (0x4 << 8);
	/* PB12 NRST, PB13 SWIO: open drain 50 MHz, released */
	GPIOB->BSHR = SWIO | NRST;
	GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xffu << 16)) | (0x7 << 16) | (0x7 << 20);

	USART1->BRR = FUNCONF_SYSTEM_CORE_CLOCK / 115200;     /* APB2 = HCLK */
	USART1->CTLR1 = USART_CTLR1_UE | USART_CTLR1_TE | USART_CTLR1_RE;

	/* voice bus: USART3 PB10 TX (AF push-pull) -> card RX (PD6), PB11 RX (pull-up) <- card TX (PD5); 31250 Bd for
	   now (the voice firmware still has board 1's MIDI receiver), 1 Mbaud with the bus protocol */
	RCC->APB1PCENR |= RCC_APB1Periph_USART3;
	GPIOB->BSHR = 1u << 11;
	GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xffu << 8)) | (0xb << 8) | (0x8 << 12);
	USART3->BRR = FUNCONF_SYSTEM_CORE_CLOCK / 2 / 31250;  /* APB1 = HCLK / 2 */
	USART3->CTLR1 = USART_CTLR1_UE | USART_CTLR1_TE | USART_CTLR1_RE;

	TIM1->PSC = FUNCONF_SYSTEM_CORE_CLOCK / 1000000 - 1;  /* 1 MHz */
	TIM1->ATRLR = 999;                                    /* 1 kHz */
	TIM1->CH1CVR = 500;
	TIM1->CHCTLR1 = TIM_OC1M_2 | TIM_OC1M_1 | TIM_OC1PE;  /* PWM mode 1 */
	TIM1->CCER = TIM_CC1E;
	TIM1->BDTR = TIM_MOE;
	TIM1->SWEVGR = 1;                                     /* UG: load the preloads */
	TIM1->CTLR1 = TIM_CEN;
}

int main(void)
{
	SystemInit();
	hw_init();
	printf("bench_ctrl: Ardulink SWIO programmer on USART1, SYNC 1 kHz on PA8\n");
	for (;;) {
		int c = uart_getc();
		if (c == '?') {
			swio_line_reset();
			uart_putc('!');
		} else if (c == 'w') {
			uint8_t reg = (uint8_t)uart_getc();
			uint32_t v = 0;
			for (int i = 0; i < 4; i++)
				v |= (uint32_t)uart_getc() << (8 * i);
			swio_write(reg, v);
			uart_putc('+');
		} else if (c == 'r') {
			uint32_t v = swio_read((uint8_t)uart_getc());
			for (int i = 0; i < 4; i++)
				uart_putc((v >> (8 * i)) & 0xff);
		} else if (c == 'p' || c == 'P') {
			uart_putc('+');
		} else if (c == 'm') {                    /* bench (not Ardulink): 'm' n bytes -> sent on the voice bus, '+' */
			int n = uart_getc();
			for (int i = 0; i < n; i++) {
				int b = uart_getc();
				while (!(USART3->STATR & USART_STATR_TXE)) ;
				USART3->DATAR = (uint8_t)b;
			}
			while (!(USART3->STATR & USART_STATR_TC)) ;
			uart_putc('+');
		} else if (c == 'q') {                    /* bench check: PB10 as input with pull-up, its level ('0' / '1') */
			GPIOB->BSHR = 1u << 10;
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 8)) | (0x8 << 8);
			Delay_Us(100);
			int lv = (GPIOB->INDR & (1u << 10)) ? '1' : '0';
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 8)) | (0xb << 8);
			uart_putc(lv);
		} else if (c == 'z') {                    /* bench check: PB10 held low for 4 s (find where the bus wire lands) */
			uart_putc('+');
			GPIOB->BCR = 1u << 10;
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 8)) | (0x3 << 8);   /* GPIO push-pull, low */
			Delay_Ms(4000);
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 8)) | (0xb << 8);   /* back to USART3 TX */
		} else if (c == 'y') {                    /* bench check: send 0x00 on the bus, sample PB10: low / high counts */
			uint32_t lo = 0, hi = 0;
			for (int i = 0; i < 4; i++) {
				while (!(USART3->STATR & USART_STATR_TXE)) ;
				USART3->DATAR = 0;
				for (int k = 0; k < 2000; k++)
					(GPIOB->INDR & (1u << 10)) ? hi++ : lo++;
			}
			uart_putc(lo > 255 ? 255 : lo);
			uart_putc(hi > 255 ? 255 : hi);
			uart_putc((GPIOB->CFGHR >> 8) & 0xff);
		} else if (c == 'x') {                    /* bench check (not Ardulink): SWIO level released, then with pull-up */
			int open = (GPIOB->INDR & SWIO) ? '1' : '0';
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 20)) | (0x8 << 20);   /* input with pull-up (OUTDR = 1) */
			Delay_Us(200);
			int pulled = (GPIOB->INDR & SWIO) ? '1' : '0';
			GPIOB->CFGHR = (GPIOB->CFGHR & ~(0xfu << 20)) | (0x7 << 20);   /* back to open drain */
			uart_putc(open);
			uart_putc(pulled);
		}
	}
}
