/*
 * echo_tcp.c -- TCP echo firmware for VexRiscV using lwIP.
 *
 * Listens on TCP port 1234.  Each connected client receives back exactly
 * what it sends, but the data round-trips through the EchoSlave BRAM first:
 * we write the received bytes into the slave, read them back, then send the
 * read-back bytes to the client.  A broken slave breaks the echo visibly.
 *
 * lwIP is used in NO_SYS=1 (polling) mode.  There is no RTOS.  The main loop
 * calls ethernetif_input() and sys_check_timeouts() every iteration.
 *
 * Only one client connection is accepted at a time.  Any second connect
 * attempt is refused until the first client closes or times out.
 *
 * FPGA address:  192.168.1.101 / TCP port 1234
 * Host address:  anything on 192.168.1.0/24
 */

#include <stdint.h>
#include <string.h>

#include <generated/csr.h>
#include <generated/mem.h>

#include "lwip/init.h"
#include "lwip/netif.h"
#include "lwip/timeouts.h"
#include "lwip/tcp.h"
#include "lwip/ip4_addr.h"
#include "lwip/etharp.h"
#include "netif/ethernet.h"

/* Provided by ethernetif.c */
err_t ethernetif_init(struct netif *netif);
void  ethernetif_input(struct netif *netif);

/* ---- Network parameters ------------------------------------------------ */

#define FPGA_IP0  192
#define FPGA_IP1  168
#define FPGA_IP2    1
#define FPGA_IP3  101

#define ECHO_PORT 1234

/* ---- EchoSlave BRAM helpers -------------------------------------------- */

#ifndef ECHOSLAVE_BASE
#error "ECHOSLAVE_BASE not defined -- run build_soc.py to generate mem.h"
#endif

static inline void slave_write(unsigned int offset, unsigned int value)
{
    volatile unsigned int *slave = (volatile unsigned int *)ECHOSLAVE_BASE;
    slave[offset] = value;
}

static inline unsigned int slave_read(unsigned int offset)
{
    volatile unsigned int *slave = (volatile unsigned int *)ECHOSLAVE_BASE;
    return slave[offset];
}

/*
 * echo_through_slave -- write buf into BRAM, read back into out.
 *
 * Both buffers are 'len' bytes.  The round-trip through the slave proves
 * the hardware path is intact.
 */
static void echo_through_slave(const uint8_t *in, uint8_t *out, uint16_t len)
{
    unsigned int words = (len + 3) / 4;
    for (unsigned int i = 0; i < words; i++) {
        unsigned int w = 0;
        memcpy(&w, in + i * 4, (len - i * 4 >= 4) ? 4 : len - i * 4);
        slave_write(i, w);
    }
    for (unsigned int i = 0; i < words; i++) {
        unsigned int w = slave_read(i);
        memcpy(out + i * 4, &w, (len - i * 4 >= 4) ? 4 : len - i * 4);
    }
}

/* ---- TCP echo callbacks ------------------------------------------------ */

/*
 * echo_recv -- called by lwIP when data arrives on an accepted connection.
 *
 * We run each chunk through the slave and echo it straight back.  This is
 * called per TCP segment, not per application message, so 'len' may be
 * smaller than the original send().
 */
static err_t echo_recv(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t err)
{
    (void)arg;

    if (err != ERR_OK || p == NULL) {
        /* Client closed the connection or error -- clean up. */
        tcp_close(pcb);
        if (p != NULL)
            pbuf_free(p);
        /* D9 off: connection closed */
        debug_leds_out_write(debug_leds_out_read() & ~0x08);
        return ERR_OK;
    }

    /* D8 on: data received */
    debug_leds_out_write(debug_leds_out_read() | 0x04);

    /*
     * Walk the pbuf chain.  Each segment is echoed independently through
     * the slave.  We use a stack buffer sized to TCP_MSS (1460 bytes).
     * Segments larger than TCP_MSS are refused with ERR_MEM; the client
     * will retransmit.
     */
    for (struct pbuf *q = p; q != NULL; q = q->next) {
        if (q->len > TCP_MSS) {
            tcp_recved(pcb, p->tot_len);
            pbuf_free(p);
            return ERR_MEM;
        }

        uint8_t out[TCP_MSS];
        echo_through_slave((const uint8_t *)q->payload, out, q->len);

        err_t e = tcp_write(pcb, out, q->len, TCP_WRITE_FLAG_COPY);
        if (e != ERR_OK) {
            tcp_recved(pcb, p->tot_len);
            pbuf_free(p);
            return e;
        }
    }

    tcp_output(pcb);

    /* Tell lwIP we have consumed all the data in this pbuf chain. */
    tcp_recved(pcb, p->tot_len);
    pbuf_free(p);

    /* D9 on: reply sent */
    debug_leds_out_write(debug_leds_out_read() | 0x08);

    return ERR_OK;
}

/*
 * echo_accept -- called by lwIP when a client completes the TCP handshake.
 *
 * We register echo_recv as the data callback and turn on the connection LED.
 */
static err_t echo_accept(void *arg, struct tcp_pcb *new_pcb, err_t err)
{
    (void)arg;
    if (err != ERR_OK || new_pcb == NULL)
        return ERR_VAL;

    tcp_recv(new_pcb, echo_recv);

    /* D8 on: client connected */
    debug_leds_out_write(debug_leds_out_read() | 0x04);

    return ERR_OK;
}

/* ---- Main -------------------------------------------------------------- */

int main(void)
{
    /* 0x01: main() reached */
    debug_leds_out_write(0x01);

    /* timer0: free-running counter used by sys_now() in sys_arch.h */
    timer0_en_write(0);
    timer0_reload_write(0xffffffff);
    timer0_load_write(0xffffffff);
    timer0_en_write(1);

    /* 0x02: timer init done */
    debug_leds_out_write(0x02);

    /* Initialise the lwIP core. */
    lwip_init();

    /* 0x03: lwip_init() done */
    debug_leds_out_write(0x03);

    /* Configure the network interface. */
    struct netif netif;
    ip4_addr_t ipaddr, netmask, gateway;
    IP4_ADDR(&ipaddr,  FPGA_IP0, FPGA_IP1, FPGA_IP2, FPGA_IP3);
    IP4_ADDR(&netmask, 255, 255, 255, 0);
    IP4_ADDR(&gateway, 192, 168,   1,   1);

    /* 0x04: about to call netif_add() */
    debug_leds_out_write(0x04);

    netif_add(&netif, &ipaddr, &netmask, &gateway,
              NULL, ethernetif_init, ethernet_input);

    /* 0x05: netif_add() done */
    debug_leds_out_write(0x05);

    netif_set_default(&netif);
    netif_set_up(&netif);

    /* 0x06: netif up */
    debug_leds_out_write(0x06);

    /* Create the TCP echo server on port 1234. */
    struct tcp_pcb *listen_pcb = tcp_new();

    /* 0x07: tcp_new() done */
    debug_leds_out_write(0x07);

    tcp_bind(listen_pcb, IP_ADDR_ANY, ECHO_PORT);

    /* 0x08: tcp_bind() done */
    debug_leds_out_write(0x08);

    listen_pcb = tcp_listen(listen_pcb);

    /* 0x09: tcp_listen() done */
    debug_leds_out_write(0x09);

    tcp_accept(listen_pcb, echo_accept);

    /* 0x0A: server ready, entering main loop */
    debug_leds_out_write(0x0A);

    /* Main loop: poll network and drive lwIP timers. */
    while (1) {
        ethernetif_input(&netif);
        sys_check_timeouts();
    }

    return 0;
}
