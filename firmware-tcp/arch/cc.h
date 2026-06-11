/*
 * arch/cc.h -- lwIP compiler/platform types for riscv-none-elf-gcc.
 *
 * lwIP requires this file to know the exact integer widths for this target.
 * RISC-V bare-metal GCC defines uint32_t as "unsigned long", not "unsigned
 * int", so we use <stdint.h> instead of assuming any type width.
 */
#ifndef LWIP_ARCH_CC_H
#define LWIP_ARCH_CC_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef uint8_t   u8_t;
typedef int8_t    s8_t;
typedef uint16_t  u16_t;
typedef int16_t   s16_t;
typedef uint32_t  u32_t;
typedef int32_t   s32_t;
typedef uintptr_t mem_ptr_t;

#define U16_F "u"
#define S16_F "d"
#define X16_F "x"
#define U32_F "u"
#define S32_F "d"
#define X32_F "x"
#define SZT_F "zu"

#define PACK_STRUCT_FIELD(x)  x
#define PACK_STRUCT_STRUCT    __attribute__((packed))
#define PACK_STRUCT_BEGIN
#define PACK_STRUCT_END

#define LWIP_PLATFORM_DIAG(x)    do { printf x; } while(0)
#define LWIP_PLATFORM_ASSERT(x)  do { for(;;); } while(0)

#define LWIP_RAND() ((u32_t)rand())

#endif
