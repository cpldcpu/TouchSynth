# Voice firmware:  make [TARGET_MCU=CH32V006|CH32V003|CH32V002] [DAC_DUAL=1]   (WSL, riscv64-unknown-elf-gcc)
#                  make flash     (WCH-LinkE via minichlink)
#   DAC_DUAL=1: dual-PWM DAC (TIM2 CH2 high byte, CH4 low byte on PC1; hw.h)
all : build

TARGET:=touchsynth
TARGET_MCU?=CH32V006
PREFIX:=riscv64-unknown-elf
ADDITIONAL_C_FILES:=hw.c synth.c console.c dsp.c
DAC_DUAL?=0
EXTRA_CFLAGS+=-DDAC_DUAL=$(DAC_DUAL)
include ../ch32fun/ch32fun/ch32fun.mk

tables.h : gen_tables.py ../../docs/results/s1_cal.csv ../../docs/results/s3_cutoff.csv ../../sim/behav/tunes.py
	python3 gen_tables.py

flash : cv_flash
clean : cv_clean
