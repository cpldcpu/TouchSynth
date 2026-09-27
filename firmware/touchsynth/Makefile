# TouchSynth firmware:  make [TARGET_MCU=CH32V003|CH32V002|CH32V006]   (WSL, riscv64-unknown-elf-gcc)
#                       make flash     (WCH-LinkE via minichlink)
all : build

TARGET:=touchsynth
TARGET_MCU?=CH32V003
PREFIX:=riscv64-unknown-elf
ADDITIONAL_C_FILES:=hw.c synth.c ui.c console.c
include ../ch32fun/ch32fun/ch32fun.mk

tables.h : gen_tables.py ../../docs/results/s1_cal.csv ../../docs/results/s3_cutoff.csv ../../sim/behav/tunes.py
	python3 gen_tables.py

flash : cv_flash
clean : cv_clean
