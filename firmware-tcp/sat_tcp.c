/*
 * sat_tcp.c -- TCP SAT solver accelerator firmware for VexRiscv + lwIP
 *
 * Listens on TCP port 1234. On each connection the host sends a formula;
 * the firmware loads it into the BruteForceSAT Wishbone slave, polls for
 * completion (~20 µs worst case at 50 MHz), then sends the result back.
 *
 * Host -> FPGA packet format:
 *   0xAA           start marker
 *   N              number of variables (1 byte, 1..MAX_VARS)
 *   M              number of clauses   (1 byte, 1..MAX_CLAUSES)
 *   bytes...       literals and clause terminators:
 *                    bit7=1 -> negated, bits6-0 = variable number (1-based)
 *                    0x00  -> clause terminator (follows last literal of clause)
 *                    0xFF  -> end of formula marker
 *
 * FPGA -> Host response:
 *   SAT:   0x01 + N assignment bytes + 0xFF
 *          assignment byte: bit7 = variable value, bits6-0 = variable number (1-based)
 *   UNSAT: 0x00 + 0xFF
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

err_t ethernetif_init(struct netif *netif);
void  ethernetif_input(struct netif *netif);

/* ---- Network configuration --------------------------------------------- */

#define FPGA_IP0  192
#define FPGA_IP1  168
#define FPGA_IP2    1
#define FPGA_IP3  101

#define SAT_PORT  1234

/* ---- SAT slave register interface -------------------------------------- */

#define MAX_VARS    10
#define MAX_CLAUSES 20
#define CLAUSE_LEN  10

static volatile uint32_t *sat_reg = (volatile uint32_t *)SATSLAVE_BASE;

/* Word offsets into the SAT slave register file */
#define SAT_CTRL      0   /* W: bit0=start  R: bit0=done bit1=sat */
#define SAT_NVARS     1   /* W: number of variables (0-based count) */
#define SAT_NCLAUSES  2   /* W: number of clauses */
#define SAT_MODEL     3   /* R: satisfying assignment (bit i = value of var i+1) */
#define SAT_LIT_BASE  8   /* W: literal[c][l] at offset 8 + c*CLAUSE_LEN + l  */
                          /*    bits[3:0]=var(0-based) bit4=neg bit5=used       */

/* ---- Packet protocol constants ----------------------------------------- */

#define PROTO_START  0xAA
#define PROTO_END    0xFF
#define PROTO_TERM   0x00
#define RESP_SAT     0x01
#define RESP_UNSAT   0x00

/* ---- TCP receive callback ----------------------------------------------- */

static err_t sat_recv(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t err)
{
    (void)arg;

    if (err != ERR_OK || p == NULL) {
        tcp_close(pcb);
        if (p != NULL)
            pbuf_free(p);
        return ERR_OK;
    }

    /* Bit 2 (D8): data received */
    debug_leds_out_write(debug_leds_out_read() | 0x04);

    /* Flatten the pbuf chain into a local buffer */
    uint8_t buf[512];
    uint16_t total = 0;
    for (struct pbuf *q = p; q != NULL; q = q->next) {
        uint16_t copy = q->len;
        if (total + copy > sizeof(buf))
            copy = sizeof(buf) - total;
        memcpy(buf + total, q->payload, copy);
        total += copy;
        if (total >= sizeof(buf))
            break;
    }

    tcp_recved(pcb, p->tot_len);
    pbuf_free(p);

    /* Validate header */
    if (total < 4 || buf[0] != PROTO_START)
        return ERR_OK;

    uint8_t n_vars    = buf[1];
    uint8_t n_clauses = buf[2];
    if (n_vars == 0 || n_vars > MAX_VARS || n_clauses == 0 || n_clauses > MAX_CLAUSES)
        return ERR_OK;

    /* Clear all literal registers (resets lit_used for the previous formula) */
    for (int i = 0; i < MAX_CLAUSES * CLAUSE_LEN; i++)
        sat_reg[SAT_LIT_BASE + i] = 0;

    /* Parse literals (pos starts after header byte, n_vars byte, n_clauses byte) */
    int clause = 0, lit = 0;
    for (int pos = 3; pos < total && clause < n_clauses; pos++) {
        uint8_t b = buf[pos];
        if (b == PROTO_END)
            break;
        if (b == PROTO_TERM) {
            clause++;
            lit = 0;
        } else if (lit < CLAUSE_LEN) {
            uint8_t var = (b & 0x7F) - 1;   /* convert 1-based to 0-based */
            uint8_t neg = (b >> 7) & 1;
            sat_reg[SAT_LIT_BASE + clause * CLAUSE_LEN + lit] =
                (1u << 5) | ((uint32_t)neg << 4) | var;
            lit++;
        }
    }

    /* Load formula dimensions and start solving */
    sat_reg[SAT_NVARS]    = n_vars;
    sat_reg[SAT_NCLAUSES] = n_clauses;
    sat_reg[SAT_CTRL]     = 1;   /* start -- hardware auto-clears next cycle */

    /* Poll done bit; worst case is 2^MAX_VARS = 1024 cycles (~20 µs at 50 MHz) */
    while (!(sat_reg[SAT_CTRL] & 1))
        ;

    /* Read result */
    uint32_t ctrl  = sat_reg[SAT_CTRL];
    uint32_t model = sat_reg[SAT_MODEL];
    int is_sat = (ctrl >> 1) & 1;

    /* Build response */
    uint8_t resp[MAX_VARS + 3];
    int rlen = 0;
    if (is_sat) {
        resp[rlen++] = RESP_SAT;
        for (int i = 0; i < n_vars; i++) {
            uint8_t val = (model >> i) & 1;
            resp[rlen++] = (uint8_t)((val << 7) | ((i + 1) & 0x7F));
        }
        resp[rlen++] = PROTO_END;
    } else {
        resp[rlen++] = RESP_UNSAT;
        resp[rlen++] = PROTO_END;
    }

    tcp_write(pcb, resp, rlen, TCP_WRITE_FLAG_COPY);
    tcp_output(pcb);

    /* Bit 3 (D9): reply sent */
    debug_leds_out_write(debug_leds_out_read() | 0x08);

    return ERR_OK;
}

static err_t sat_accept(void *arg, struct tcp_pcb *new_pcb, err_t err)
{
    (void)arg;
    if (err != ERR_OK || new_pcb == NULL)
        return ERR_VAL;

    tcp_recv(new_pcb, sat_recv);
    return ERR_OK;
}

/* ---- Main -------------------------------------------------------------- */

int main(void)
{
    /* Bit 0 (D6): main() reached */
    debug_leds_out_write(0x01);

    timer0_en_write(0);
    timer0_reload_write(0xffffffff);
    timer0_load_write(0xffffffff);
    timer0_en_write(1);

    lwip_init();

    /* Bit 1 (D7): lwIP initialised */
    debug_leds_out_write(0x03);

    struct netif netif;
    ip4_addr_t ipaddr, netmask, gateway;
    IP4_ADDR(&ipaddr,  FPGA_IP0, FPGA_IP1, FPGA_IP2, FPGA_IP3);
    IP4_ADDR(&netmask, 255, 255, 255, 0);
    IP4_ADDR(&gateway, 192, 168,   1,   1);

    netif_add(&netif, &ipaddr, &netmask, &gateway,
              NULL, ethernetif_init, ethernet_input);
    netif_set_default(&netif);
    netif_set_up(&netif);

    struct tcp_pcb *listen_pcb = tcp_new();
    tcp_bind(listen_pcb, IP_ADDR_ANY, SAT_PORT);
    listen_pcb = tcp_listen(listen_pcb);
    tcp_accept(listen_pcb, sat_accept);

    /* Bits 0+1+3 (D6+D7+D9): init complete, listening */
    debug_leds_out_write(0x0B);

    while (1) {
        ethernetif_input(&netif);
        sys_check_timeouts();
    }

    return 0;
}
