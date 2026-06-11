/*
 * sys_arch.c -- lwIP platform glue for bare-metal VexRiscV.
 *
 * This file provides three things that lwIP needs but the stripped-down
 * LiteX picolibc build does not supply:
 *
 *   sys_now()  -- millisecond timestamp for TCP timers
 *   rand()     -- pseudo-random number used for TCP ISN generation
 *   memcmp()   -- byte comparison used by lwIP's Ethernet input
 */

#include <stdint.h>
#include <stddef.h>
#include <generated/csr.h>
#include "lwip/arch.h"

/* ---- sys_now ----------------------------------------------------------- */
/*
 * sys_now -- return a millisecond timestamp.
 *
 * timer0 is a free-running down-counter loaded with 0xFFFFFFFF in main().
 * ~timer0_value_read() gives elapsed ticks since reset.
 * Dividing by (clock_freq / 1000) converts to milliseconds.
 *
 * lwIP only uses differences between consecutive sys_now() calls, so
 * 32-bit wrap-around is harmless.
 */
u32_t sys_now(void)
{
    /* value is a latched CSR: writing update_value captures the live count. */
    timer0_update_value_write(1);
    return ~timer0_value_read() / (CONFIG_CLOCK_FREQUENCY / 1000);
}

/* ---- rand -------------------------------------------------------------- */
/*
 * rand -- minimal LCG PRNG seeded from the timer.
 *
 * lwIP calls LWIP_RAND() (= rand()) once during tcp_init() to set the
 * initial TCP sequence number.  Quality of randomness is not critical here;
 * we just need something that changes between power cycles.
 */
static unsigned int _rand_state;

int rand(void)
{
    if (_rand_state == 0)
        _rand_state = (unsigned int)~timer0_value_read() ^ 0xdeadbeef;
    _rand_state = _rand_state * 1664525u + 1013904223u;
    return (int)((_rand_state >> 16) & 0x7fff);
}

/* ---- memcmp ------------------------------------------------------------ */
/*
 * memcmp -- byte-by-byte memory comparison.
 *
 * lwIP's ethernet_input() uses memcmp() to compare MAC addresses.
 * The stripped LiteX picolibc does not export memcmp as a symbol, so
 * we provide a simple implementation here.
 */
int memcmp(const void *s1, const void *s2, size_t n)
{
    const unsigned char *a = (const unsigned char *)s1;
    const unsigned char *b = (const unsigned char *)s2;
    for (size_t i = 0; i < n; i++) {
        if (a[i] != b[i])
            return (int)a[i] - (int)b[i];
    }
    return 0;
}
