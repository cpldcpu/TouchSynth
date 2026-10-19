# Voice firmware:  make [TARGET_MCU=CH32V006|CH32V003|CH32V002] [DAC_DUAL=1] [BOARD=card]   (WSL, riscv64-unknown-elf-gcc)
#   BOARD=card: the voice card's pin map (board.h), else board 1
#                  make flash     (WCH-LinkE via minichlink)
#   DAC_DUAL=1: dual-PWM DAC (TIM2 CH2 high byte, CH4 low byte on PC1; hw.h)
#   BUS_TX_PP=1: card on the bench: the bus return line (PD5) push-pull during replies (no 1 kOhm pull-up; hw.c)
#   BUS_EARLY=0: card: foreign bus packets decoded and CRC-checked before they are dropped (default 1: dropped at
#                their dst byte; bus.c)
#   BUS_BAUD=2000000: card: voice bus baud rate (default 1000000; the controller must match: bench_ctrl/Makefile)
all : build

TARGET:=touchsynth
TARGET_MCU?=CH32V006
PREFIX:=riscv64-unknown-elf
ADDITIONAL_C_FILES:=hw.c synth.c console.c dsp.c bus.c
DAC_DUAL?=0
BOARD?=board1
BUS_TX_PP?=0
BUS_EARLY?=1
EXTRA_CFLAGS+=-DDAC_DUAL=$(DAC_DUAL) -DBUS_TX_PP=$(BUS_TX_PP) -DBUS_EARLY=$(BUS_EARLY)
ifeq ($(BOARD),card)
EXTRA_CFLAGS+=-DBOARD_CARD=1
endif
ifdef BUS_BAUD
EXTRA_CFLAGS+=-DBUS_BAUD=$(BUS_BAUD)
endif
include ../ch32fun/ch32fun/ch32fun.mk

tables.h : gen_tables.py ../../docs/results/s1_cal.csv ../../docs/results/s3_cutoff.csv ../../sim/behav/tunes.py
	python3 gen_tables.py

flash : cv_flash
clean : cv_clean
