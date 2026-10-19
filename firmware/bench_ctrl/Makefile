# Bench controller (CH32V203 development board):  make   (WSL, riscv64-unknown-elf-gcc)
all : build

TARGET:=bench_ctrl
TARGET_MCU:=CH32V203
PREFIX:=riscv64-unknown-elf
include ../ch32fun/ch32fun/ch32fun.mk

flash : cv_flash
clean : cv_clean
