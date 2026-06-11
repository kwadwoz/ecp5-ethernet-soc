/*
 * lwipopts.h -- compile-time configuration for lwIP on VexRiscV bare metal.
 *
 * Every option here is deliberate.  Defaults are in lwip/src/include/lwip/opt.h.
 */
#ifndef LWIPOPTS_H
#define LWIPOPTS_H

/* ---- OS / threading ---------------------------------------------------- */
#define NO_SYS                  1   /* bare metal, no RTOS */
#define SYS_LIGHTWEIGHT_PROT    0   /* single core, no critical sections needed */

/* ---- APIs -------------------------------------------------------------- */
#define LWIP_SOCKET             0   /* disable BSD socket API */
#define LWIP_NETCONN            0   /* disable netconn API */

/* ---- Protocols --------------------------------------------------------- */
#define LWIP_TCP                1
#define LWIP_UDP                0   /* we only need TCP for this firmware */
#define LWIP_ICMP               1   /* keep ping working */
#define LWIP_ARP                1
#define LWIP_DHCP               0
#define LWIP_AUTOIP             0
#define LWIP_IGMP               0
#define LWIP_DNS                0
#define LWIP_RAW                0

/* ---- Memory ------------------------------------------------------------ */
/*
 * The VexRiscV SRAM is only 16 KB (0x4000).  Every byte counts.
 *
 * Budget breakdown (approximate):
 *   PBUF_POOL (4 * 1524 + pbuf overhead) ~6.3 KB  -- statically in BSS
 *   lwIP memp pools (PCBs, segments)     ~0.9 KB  -- statically in BSS
 *   MEM_SIZE heap                        ~3.0 KB  -- statically in BSS
 *   Stack + globals                      ~1.5 KB
 *   -----------------------------------------------
 *   Total                               ~11.7 KB  (fits in 16 KB)
 */
#define MEM_LIBC_MALLOC         0
#define MEM_SIZE                (3 * 1024)

/*
 * VexRiscv (rv32i) traps on misaligned 32-bit accesses. lwIP's default
 * MEM_ALIGNMENT of 1 lets heap and pbuf payloads start at any byte offset,
 * which crashes the CPU on the first word-sized store into a packet buffer.
 */
#define MEM_ALIGNMENT           4

/*
 * PBUF_POOL_BUFSIZE = 1524 means one pbuf slot holds a full Ethernet frame
 * (1500 byte payload + 14 byte Ethernet header, rounded up).  This avoids
 * chaining pbufs for incoming frames and keeps the receive path simple.
 *
 * PBUF_POOL_SIZE = 4 gives 4 * (1524 - 54) = 5880 bytes of receive window
 * capacity, which is just enough to satisfy the TCP_WND sanity check below.
 */
#define MEMP_NUM_PBUF           8
#define MEMP_NUM_TCP_PCB        2
#define MEMP_NUM_TCP_PCB_LISTEN 1
#define MEMP_NUM_TCP_SEG        16
#define MEMP_NUM_NETBUF         0
#define MEMP_NUM_NETCONN        0
#define PBUF_POOL_SIZE          4
#define PBUF_POOL_BUFSIZE       1524

/* ---- TCP tuning -------------------------------------------------------- */
/*
 * TCP_WND must be <= PBUF_POOL_SIZE * (PBUF_POOL_BUFSIZE - 54 header bytes).
 * 4 * (1524 - 54) = 5880 >= TCP_WND = 4 * 1460 = 5840.  Passes by 40 bytes.
 * On a 10baseT link the window doesn't affect throughput anyway.
 */
#define TCP_MSS                 1460
#define TCP_SND_BUF             (2 * TCP_MSS)
#define TCP_SND_QUEUELEN        (4 * TCP_SND_BUF / TCP_MSS)
#define TCP_WND                 (4 * TCP_MSS)

/* ---- Checksums --------------------------------------------------------- */
/*
 * Hardware preamble/CRC is present (CSR_ETHMAC_PREAMBLE_CRC_ADDR defined),
 * but IP/TCP checksums are still computed in software.  All four must stay on.
 */
#define CHECKSUM_GEN_IP         1
#define CHECKSUM_GEN_UDP        1
#define CHECKSUM_GEN_TCP        1
#define CHECKSUM_CHECK_IP       1
#define CHECKSUM_CHECK_UDP      1
#define CHECKSUM_CHECK_TCP      1

/* ---- IP reassembly ----------------------------------------------------- */
#define IP_REASSEMBLY           0   /* no fragmented packets expected; saves memp */
#define IP_FRAG                 0

/* ---- Misc -------------------------------------------------------------- */
#define LWIP_STATS              0   /* disable counters to save ROM */
#define LWIP_LOOPBACK_INTERFACE 0
#define LWIP_HAVE_LOOPIF        0
#define LWIP_NETIF_HOSTNAME     0

#endif
