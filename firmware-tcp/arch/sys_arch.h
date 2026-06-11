/*
 * arch/sys_arch.h -- lwIP OS/timer abstraction for bare-metal VexRiscV.
 *
 * NO_SYS=1 means there is no RTOS.  lwIP still needs sys_now() to return a
 * millisecond timestamp for its internal TCP timers (retransmission, TIME_WAIT,
 * keepalive).  We use the LiteX timer0 free-running counter, scaled from the
 * SYSTEM_CLOCK_FREQUENCY constant that variables.mak exports.
 *
 * sys_prot_t is required by lwIP's critical-section macros. On a single-core
 * bare-metal system there is nothing to protect, so the type is a placeholder.
 */
#ifndef LWIP_ARCH_SYS_ARCH_H
#define LWIP_ARCH_SYS_ARCH_H

#include <stdint.h>
#include <generated/csr.h>

typedef uint32_t sys_prot_t;

static inline uint32_t sys_now(void)
{
    /*
     * timer0 counts down from 0xFFFFFFFF. elapsed_ticks = ~timer0_value_read().
     * Divide by (SYSTEM_CLOCK_FREQUENCY / 1000) to get milliseconds.
     * value is a latched CSR: writing update_value captures the live count.
     */
    timer0_update_value_write(1);
    return ~timer0_value_read() / (CONFIG_CLOCK_FREQUENCY / 1000);
}

#endif
