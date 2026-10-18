/* TouchSynth board definition: pins from hw/design.py (MCU U3, TSSOP-20), remap codes per chip family.
 *
 *  pin port  net          use                         pin port  net          use
 *   1  PD4   LATCH        74HC595 RCLK (GPIO)          11  PC1   SUB          sub-oscillator (GPIO)
 *   2  PD5   ADC_AUDIO    ADC IN5 <- audio loopback    12  PC2   PULSE        TIM2 CH2
 *   3  PD6   MIDI_RX      USART1 RX                    13  PC3   S0_DATA      mux S0 / 595 SER
 *   4  PD7   NRST                                      14  PC4   S1_CLK       mux S1 / 595 SRCLK
 *   5  PA1   TOUCH_B      mux B common, ADC IN1        15  PC5   DCO_RST      TIM2 CH1 (active low)
 *   6  PA2   TOUCH_A      mux A common, ADC IN0        16  PC6   PWM_AMP      TIM1 CH1
 *   8  PD0   NOISE        noise (GPIO)                 17  PC7   PWM_CUT      TIM1 CH2
 *  10  PC0   PWM_RES      TIM1 CH3                     18  PD1   SWIO
 *                                                       19  PD2   S2           mux S2 (GPIO)
 *                                                       20  PD3   PWM_VCA      TIM1 CH4
 *
 * Timer remaps (checked against the CH32V003 reference header and the CH32V002 datasheet pin table):
 *   CH32V003: TIM1 partial remap 1 (01b): CH1 PC6, CH2 PC7, CH3 PC0, CH4 PD3
 *             TIM2 partial remap 1 (01b): CH1 PC5, CH2 PC2
 *   CH32V00x: TIM1_RM = 0010b: TIM1_CH1_2 PC6, TIM1_CH2_2 PC7, TIM1_CH3_2 PC0, TIM1_CH4_2 PD3
 *             TIM2_RM = 010b:  TIM2_CH1_ETR_2 PC5, TIM2_CH2_2 PC2
 * The complementary / break functions these remaps also route (TIM1 CH1N PC3, CH2N PC4, CH3N PD1, BKIN PC1,
 * TIM2 CH3 PD2, CH4 PC1) are never enabled.
 */
#ifndef BOARD_H
#define BOARD_H

#include "ch32fun.h"

#define PIN_LATCH    PD4
#define PIN_AUDIO    PD5
#define PIN_MIDI_RX  PD6
#define PIN_TOUCH_B  PA1
#define PIN_TOUCH_A  PA2
#define PIN_NOISE    PD0
#define PIN_CV_RES   PC0
#define PIN_SUB      PC1
#define PIN_PULSE    PC2
#define PIN_S0_DATA  PC3
#define PIN_S1_CLK   PC4
#define PIN_DCO_RST  PC5
#define PIN_CV_AMP   PC6
#define PIN_CV_CUT   PC7
#define PIN_S2       PD2
#define PIN_CV_VCA   PD3

#define ADC_CH_TOUCH_A 0
#define ADC_CH_TOUCH_B 1
#define ADC_CH_AUDIO   5

#if defined(CH32V003)
#define CHIP_NAME "CH32V003"
#define REMAP_MASK   (AFIO_PCFR1_TIM1_REMAP | AFIO_PCFR1_TIM2_REMAP)
#define REMAP_BITS   (AFIO_PCFR1_TIM1_REMAP_PARTIALREMAP1 | AFIO_PCFR1_TIM2_REMAP_PARTIALREMAP1)
#elif defined(CH32V00x)
#if defined(CH32V002)
#define CHIP_NAME "CH32V002"
#elif defined(CH32V006)
#define CHIP_NAME "CH32V006"
#else
#define CHIP_NAME "CH32V00x"
#endif
#define REMAP_MASK   (AFIO_PCFR1_TIM1_RM | AFIO_PCFR1_TIM2_RM)
#define REMAP_BITS   (AFIO_PCFR1_TIM1_RM_1 | AFIO_PCFR1_TIM2_RM_1)       /* TIM1_RM = 0010b, TIM2_RM = 010b */
#else
#error "unsupported MCU"
#endif

/* timer register bits (identical on both families; the vendor headers name them differently) */
#define T_CEN      0x0001
#define T_UDIS     0x0002
#define T_ARPE     0x0080
#define T_CMS1     0x0020   /* centre-aligned mode 1 (counts up and down) */
#define T_UIE      0x0001
#define T_UIF      0x0001
#define T_UDE      0x0100   /* DMAINTENR: DMA request on update */
#define T_UG       0x0001
#define T_MOE      0x8000
#define T_OC_PWM1_LO  0x0068   /* OCxM = 110 (PWM1) + OCxPE, channel 1 / 3 half of CHCTLRx */
#define T_OC_PWM1_HI  0x6800   /* same for channel 2 / 4 */
#define T_CC1E     0x0001
#define T_CC1P     0x0002
#define T_CC2E     0x0010
#define T_CC3E     0x0100
#define T_CC4E     0x1000

#define F_CPU      48000000UL
#define RESET_TICKS 144        /* DCO reset pulse: 3 us at 48 MHz (same as RESET_COUNTS in tables.h) */
#define CV_PWM_TOP 1023        /* TIM1: 10 bit at 46.875 kHz, 2 more bits by dithering */

#endif
