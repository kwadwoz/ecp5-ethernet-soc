/*
 * ethernetif.c -- lwIP netif driver for the LiteEth MAC DMA.
 *
 * This file is the only piece of code that touches the Ethernet hardware
 * directly.  Everything above (IP, ARP, TCP) is handled by lwIP.
 *
 * Hardware layout (from generated/mem.h and lwipopts.h):
 *
 *   ETHMAC_BASE
 *   +-----------+
 *   | RX slot 0 |  ETHMAC_SLOT_SIZE bytes  (DMA writer: network -> SRAM)
 *   | RX slot 1 |
 *   +-----------+
 *   | TX slot 0 |  ETHMAC_SLOT_SIZE bytes  (DMA reader: SRAM -> network)
 *   | TX slot 1 |
 *   +-----------+
 *
 * The hardware handles preamble and CRC (CSR_ETHMAC_PREAMBLE_CRC_ADDR is
 * defined), so frames in the DMA slots start directly at the destination MAC.
 *
 * TX path:  flatten the lwIP pbuf chain into the next TX slot, set length,
 *           trigger the DMA reader, advance the slot index.
 *
 * RX path:  poll the DMA writer event flag; if set, copy the frame out of
 *           the RX slot into a freshly allocated pbuf, clear the flag, hand
 *           the pbuf to ethernet_input().
 */

#include <string.h>

#include <generated/csr.h>
#include <generated/mem.h>
#include <system.h>

/* Event bit for both the RX writer and TX reader interrupt pending registers. */
#define ETHMAC_EV_SRAM_WRITER  0x1
#define ETHMAC_EV_SRAM_READER  0x1

#include "lwip/opt.h"
#include "lwip/pbuf.h"
#include "lwip/netif.h"
#include "lwip/etharp.h"
#include "netif/ethernet.h"

/* ---- MAC address ------------------------------------------------------- */

static const uint8_t fpga_mac[6] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x01};

/* ---- TX state ---------------------------------------------------------- */

static uint32_t txslot = 0;

static inline uint8_t *tx_buf(void)
{
    return (uint8_t *)(ETHMAC_BASE + ETHMAC_SLOT_SIZE * (ETHMAC_RX_SLOTS + txslot));
}

/* ---- Transmit ---------------------------------------------------------- */

/*
 * low_level_output -- called by lwIP when it wants to send an Ethernet frame.
 *
 * p is a pbuf chain.  We flatten the entire chain into one DMA slot and
 * trigger transmission.  The chain total length must not exceed ETHMAC_SLOT_SIZE.
 */
static err_t low_level_output(struct netif *netif, struct pbuf *p)
{
    (void)netif;

    /* 0x0E: entered low_level_output, waiting for TX ready */
    debug_leds_out_write(0x0E);

    /* Wait until the DMA reader is free. */
    while (!ethmac_sram_reader_ready_read())
        ;

    /* 0x0F: TX ready, about to copy and send */
    debug_leds_out_write(0x0F);
    (void)0;

    uint8_t *dst = tx_buf();
    uint32_t len = 0;

    /* Walk the pbuf chain and copy each segment into the TX DMA slot. */
    for (struct pbuf *q = p; q != NULL; q = q->next) {
        if (len + q->len > ETHMAC_SLOT_SIZE)
            return ERR_BUF;   /* frame too large -- should not happen */
        memcpy(dst + len, q->payload, q->len);
        len += q->len;
    }

    /* CPU wrote the frame; flush dcache so the DMA reader sees the new data. */
    flush_cpu_dcache();

    ethmac_sram_reader_slot_write(txslot);
    ethmac_sram_reader_length_write(len);
    ethmac_sram_reader_start_write(1);

    txslot = (txslot + 1) % ETHMAC_TX_SLOTS;

    /* 0x0B: TX triggered successfully */
    debug_leds_out_write(0x0B);

    return ERR_OK;
}

/* ---- Receive ----------------------------------------------------------- */

/*
 * low_level_input -- poll the DMA writer for a received frame.
 *
 * Returns a pbuf containing the frame, or NULL if nothing arrived.
 * The caller owns the pbuf and must call pbuf_free() when done.
 */
static struct pbuf *low_level_input(struct netif *netif)
{
    (void)netif;

    if (!(ethmac_sram_writer_ev_pending_read() & ETHMAC_EV_SRAM_WRITER))
        return NULL;

    uint32_t rxslot = ethmac_sram_writer_slot_read();
    uint32_t rxlen  = ethmac_sram_writer_length_read();

    uint8_t *src = (uint8_t *)(ETHMAC_BASE + ETHMAC_SLOT_SIZE * rxslot);

    /* DMA wrote this frame; flush dcache so the CPU sees the new data. */
    flush_cpu_dcache();

    struct pbuf *p = pbuf_alloc(PBUF_RAW, rxlen, PBUF_POOL);
    if (p != NULL) {
        uint32_t copied = 0;
        for (struct pbuf *q = p; q != NULL; q = q->next) {
            uint32_t chunk = (copied + q->len <= rxlen) ? q->len : rxlen - copied;
            memcpy(q->payload, src + copied, chunk);
            copied += chunk;
        }
    }

    /* Clear the event flag -- this frees the RX slot for the next frame. */
    ethmac_sram_writer_ev_pending_write(ETHMAC_EV_SRAM_WRITER);

    return p;
}

/*
 * ethernetif_input -- call this from the main loop every iteration.
 *
 * Polls for a received frame and, if one arrived, passes it up to lwIP's
 * ethernet_input() which dispatches to ARP, IP, and then TCP.
 */
void ethernetif_input(struct netif *netif)
{
    struct pbuf *p = low_level_input(netif);
    if (p == NULL)
        return;

    if (netif->input(p, netif) != ERR_OK)
        pbuf_free(p);
}

/* ---- Initialisation ---------------------------------------------------- */

/*
 * ethernetif_init -- passed to netif_add() as the init callback.
 *
 * Fills in the netif fields that lwIP needs: the MAC address, interface
 * flags, and the two function pointers for ARP output and raw frame output.
 */
err_t ethernetif_init(struct netif *netif)
{
    netif->hwaddr_len = ETH_HWADDR_LEN;
    for (int i = 0; i < ETH_HWADDR_LEN; i++)
        netif->hwaddr[i] = fpga_mac[i];

    netif->mtu   = 1500;
    netif->flags = NETIF_FLAG_BROADCAST | NETIF_FLAG_ETHARP | NETIF_FLAG_LINK_UP;

    netif->output     = etharp_output;   /* lwIP ARP -> IP output */
    netif->linkoutput = low_level_output; /* raw frame -> hardware */

    /* Clear the event flags so we start from a clean state. */
    ethmac_sram_writer_ev_pending_write(ETHMAC_EV_SRAM_WRITER);
    ethmac_sram_reader_ev_pending_write(ETHMAC_EV_SRAM_READER);

    txslot = 0;

    return ERR_OK;
}
