/* Host stand-in for ch32fun.h (test/render_test.py): dsp.c only needs board.h's constants, no registers */
#ifndef CH32FUN_H
#define CH32FUN_H
#include <stdint.h>
#define CH32V00x 1
#define ADD_ARCH_ZICSR ""
#endif
