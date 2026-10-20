# Bench controller (CH32V203 development board):  make [BUS_BAUD=2000000] [USB=usbd] [USBH=1]   (WSL, riscv64-unknown-elf-gcc)
#   BUS_BAUD: voice bus baud rate (default 1000000; the cards must match: voice/Makefile)
#   USB: [2026-10-19] USB-MIDI + CDC (usb_common.h) on USBFS, PB6 / PB7 (usbdev_fs.c with ch32fun's fsusb.c): the
#        development board's USB-C; USB=usbd: on USBD, PA11 / PA12 (usbdev.c), the backplane's port.
#        Another USB ID: make EXTRA_CFLAGS="-DUSB_VID=0x... -DUSB_PID=0x..." (default: the pid.codes test ID
#        1209:0001, development only)
#   USBH=1: [2026-10-20] a USB-MIDI host on USBFS, PB6 / PB7 (usbhost.c: the backplane's host port), the USB device
#        then on USBD, PA11 / PA12 (usbdev.c). The build does not notice a changed option: make clean first.
all : build

TARGET:=bench_ctrl
TARGET_MCU:=CH32V203
# [2026-10-19] the C8T6 memory map: 64 KB flash, 20 KB SRAM (the default, F6P6, has 32 / 10 KB: the stack ran into .bss)
TARGET_MCU_PACKAGE:=CH32V203C8T6
PREFIX:=riscv64-unknown-elf
ifeq ($(USBH),1)
ADDITIONAL_C_FILES+=usbdev.c usbhost.c
EXTRA_CFLAGS+=-DUSBH=1
else ifeq ($(USB),usbd)
ADDITIONAL_C_FILES+=usbdev.c
else
ADDITIONAL_C_FILES+=usbdev_fs.c ../ch32fun/extralibs/fsusb.c
endif
ifdef BUS_BAUD
EXTRA_CFLAGS+=-DBUS_BAUD=$(BUS_BAUD)
endif
include ../ch32fun/ch32fun/ch32fun.mk

flash : cv_flash
clean : cv_clean
