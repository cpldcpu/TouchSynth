#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

#define FUNCONF_USE_HSE          1     /* 8 MHz crystal: SYNC is the pitch reference of every voice */
#define FUNCONF_USE_HSI          0
#define FUNCONF_SYSTICK_USE_HCLK 1     /* SysTick at 144 MHz: the SWIO bit timing */
#define FUNCONF_USE_DEBUGPRINTF  1     /* console over the V203's own debug link (minichlink -T) */

#endif
