# ECP5-5G EVN + LAN8720A — Baseline Test Findings

Hardware-verified wiring and PHY behaviour for the LAN8720A breakout
connected to the Lattice ECP5-5G Evaluation Board (LFE5UM5G-85F / BG381).

This document details findings from a separate experiment with manually getting SMI working on our LAN module with the same FPGA.

---

## Board Identity

| Parameter | Value |
|-----------|-------|
| Device    | LFE5UM5G-85F |
| Package   | BG381 |
| Speed grade | 8 |
| System clock | 12 MHz crystal, pin **A10** (always populated on EVN board) |
| 50 MHz OSC footprint | **B11** — **not populated** by default on EVN board |

---

## Pin Assignment — LAN8720A ↔ ECP5

| Signal | ECP5 Pin | Direction | Notes |
|--------|----------|-----------|-------|
| REF_CLK | **J4** | Input | 50 MHz from PHY; PL50A / GR_PCLK6_0 (global-clock-capable) |
| MDIO | **L4** | Bidir | SMI data; requires 1.5 kΩ pull-up on breakout |
| MDC | **K4** | Output | SMI clock; used at 2 MHz |
| RXD[0] | **G1** | Input | RMII receive bit 0 |
| RXD[1] | **N5** | Input | RMII receive bit 1 |
| CRS_DV | **L5** | Input | Carrier sense / data valid (RMII multiplexed) |
| TXEN | **J5** | Output | RMII transmit enable |
| TXD[0] | **K2** | Output | RMII transmit bit 0 |
| TXD[1] | **M5** | Output | RMII transmit bit 1 |

All signals: IO_TYPE = LVCMOS33.

## Pin Assignment — LEDs (active-low, PinsN)

| LED | Pin | Confirmed use in baseline test |
|-----|-----|-------------------------------|
| LED0 | A13 | Heartbeat (~2 Hz) — confirms FPGA and 12 MHz clock alive |
| LED1 | A12 | CRS_DV raw — asserts during Ethernet frame reception |
| LED2 | B19 | REF_CLK present — >1 000 transitions on J4 per 0.5 s |
| LED3 | A18 | SMI OK — PHY ID reg 2 returned something other than 0xFFFF |
| LED4 | B18 | SMI FAIL — PHY ID reg 2 returned 0xFFFF |
| LED5 | C17 | Link Status (reg 1 bit 2) — see latch-low note below |
| LED6 | A17 | Autoneg Complete (reg 1 bit 5) — **confirmed working** |
| LED7 | B17 | Unused |

---

## SMI / MDIO Findings

### Protocol (Clause-22)

64-bit serial frame transmitted MSB-first on MDIO:

```
| 32× preamble (1) | ST=01 | OP=10 (read) | PHYAD[4:0] | REGAD[4:0] | TA=Z0 | DATA[15:0] |
```

- MDC max rate: 2.5 MHz per LAN8720A datasheet.  Design used **2 MHz** (12 MHz ÷ 6).
- MDIO is open-drain; the **1.5 kΩ pull-up on the breakout board is required**.  Omitting it causes all reads to return 0xFFFF.

### PHY Address

**PHY address = 1**, not 0.

The LAN8720A breakout board ties PHYAD0 HIGH.  Using address 0 causes every SMI read to return 0xFFFF.  Confirmed by switching to address 1 and observing LED3 (SMI OK) light.

### Register Behaviour

| Register | Address | Key findings |
|----------|---------|--------------|
| PHY Identifier 1 | 2 | Returns **0x0007** (LAN8720A OUI upper 16 bits). Confirmed PHY alive and MDIO wired. |
| Basic Status | 1 | Bit 5 (Auto-Neg Complete) = plain RO — **worked reliably**. Bit 2 (Link Status) = latch-low — see below. |
| PHY Special Control/Status | 31 | Returned **0xFFFF** (no response) in testing. Root cause unknown. |

### Latch-Low on Link Status (Reg 1 Bit 2)

Register 1 bit 2 is type **LL (Latch Low)**: it clears to 0 whenever the link drops, and stays 0 until the register is read.  Each SMI read clears the latch.  Because the LAN8720A's Energy Detect Power-Down (EDPWRDOWN, reg 17 bit 13) cycles the PHY in and out of low-power mode, the link-down event re-latches bit 2 faster than a 500 ms polling interval can catch it.

**Result:** LED5 (link status) was persistently dark even with a live link.

**Workaround confirmed:** LED6 (autoneg complete, bit 5 — plain RO, no latch) lit reliably and is **sufficient evidence of an established link**.

---

## REF_CLK Confirmation

The LAN8720A drives a 50 MHz reference clock on J4 (REF_CLK output) once it has power.  Verified by counting edge transitions in a 0.5 s window at 12 MHz:

- Threshold used: > 1 000 transitions per window (well below the ~25 million expected at 50 MHz)
- LED2 lit reliably once Ethernet cable was connected and PHY powered

J4 = **PL50A / GR_PCLK6_0** — a global-clock-capable pin on the ECP5.  For any design clocking logic from REF_CLK, route through the ECP5 global clock network (nextpnr-ecp5 does this automatically when the signal is used as a clock domain source).

---

## Mac Host Setup (for direct-connect testing)

The physical Ethernet adapter when using a USB Gigabit dongle is typically **en12** (identified by its universally-administered OUI MAC address, versus the `c2:` locally-administered prefix on Thunderbolt virtual interfaces).

```bash
# Assign a local IP on the same subnet as the FPGA
sudo ifconfig en12 192.168.1.1 netmask 255.255.255.0

# Add a static ARP entry (bypasses ARP for the FPGA IP)
sudo arp -s 192.168.1.100 de:ad:be:ef:00:01

# Verify
arp -n 192.168.1.100
```

These settings are lost on reboot.  Specify the interface explicitly if `arp -s` complains "cannot intuit interface".

---

## Amaranth 0.5 I/O Pattern

Every physical pin requires an `io.Buffer` submodule:

```python
phy = platform.request("lan8720", 0, dir="-")          # raw Port
buf = io.Buffer("i", phy.ref_clk)                       # adds IOB
m.submodules.ref_clk_buf = buf
# use buf.i / buf.o / buf.oe — NOT the resource directly
```

`PinsN` resources invert so that `buf.o = 1` drives the pin LOW → LED on.
