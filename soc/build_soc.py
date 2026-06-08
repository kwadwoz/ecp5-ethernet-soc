#!/usr/bin/env python3
"""
build_soc.py -- ECP5 Evaluation Board Ethernet Echo SoC

Steps:
  1. Exports EchoSlave (Amaranth HDL) to Verilog via yosys.
  2. Defines a LiteX SoC: VexRiscv + LiteEth RMII + EchoSlave Wishbone slave.
  3. Runs yosys + nextpnr-ecp5 + ecppack and writes a bitstream.

Board:  LFE5UM5G-85F-EVN  (device LFE5UM5G-85F-8BG381)
PHY:    Waveshare LAN8720 wired to J40  (Bank 6, LVCMOS33, 3.3V default)
Clock:  12 MHz FTDI oscillator at ball A10 -> ECP5 PLL -> 50 MHz sys + eth

J40 wiring:
  pin  1  K2   REFCLK   50 MHz output from FPGA to LAN8720
  pin  4  F1   TXD0
  pin  5  H2   TXD1
  pin  6  G1   TXEN
  pin  7  J4   RXD0
  pin  8  J5   RXD1
  pin  9  J3   CRS_DV
  pin 10  K3   MDIO
  pin 11  L4   MDC
  pin 12  L5   nRST
  pin 19  GND           LAN8720 GND
  pin 20  EXPCON_3V3    LAN8720 VCC (3.3V)

Clock note: the 12 MHz clock from FTDI is only present when the USB
programming cable is plugged into the board. Keep it connected during
operation.

Usage:
  cd soc && python build_soc.py
Output:
  build/gateware/ecp5_ethernet_soc.bit
"""

import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))



# 1. Export EchoSlave to Verilog

# Amaranth converts the design to RTLIL (its internal representation).
# Yosys reads that IR, optimises it, renames the top module from "top"
# to "echo_slave", and writes synthesisable Verilog. The file is added
# as a platform source before LiteX invokes synthesis so yosys picks it
# up during the full SoC build.

def export_echo_slave(out_dir):
    from amaranth.back.rtlil import convert
    from echo_slave import EchoSlave

    os.makedirs(out_dir, exist_ok=True)
    il_path = os.path.join(out_dir, "echo_slave.il")
    v_path  = os.path.join(out_dir, "echo_slave.v")

    dut = EchoSlave()
    with open(il_path, "w") as f:
        f.write(convert(dut, ports=dut.ports()))

    subprocess.run(
        [
            "yosys", "-q", "-p",
            (
                f"read_rtlil {il_path}; "
                f"hierarchy -check -top top; "
                f"proc; opt; "
                f"rename top echo_slave; "
                f"write_verilog {v_path}"
            ),
        ],
        check=True,
    )
    print(f"[export] {v_path}")
    return v_path



# 2. Platform: ECP5 Evaluation Board

# The platform object declares every pin the SoC will drive or sample.
# All RMII and UART signals land on J40 (Bank 6, VCCIO6 = 3.3V default),
# which is voltage-compatible with both the LAN8720 and the CP2102.
# LEDs are in Bank 1 (VCCIO1 = 2.5V default) and are active low.

from litex.build.generic_platform import Pins, IOStandard, Subsignal
from litex.build.lattice import LatticePlatform

_io = [
    # 12 MHz from FTDI U1. JP2 must be installed; JP1 must be removed.
    ("clk12", 0,
        Pins("A10"),
        IOStandard("LVCMOS33"),
    ),

    # LAN8720 RMII on J40, Bank 6, LVCMOS33.
    # LiteEth requires the clock pin in a separate "eth_clocks" record.
    # When refclk_cd is set, LiteEth drives ref_clk via a DDR output cell
    # to produce clean 50 MHz edges into the PHY's REFCLK input.
    ("eth_clocks", 0,
        Subsignal("ref_clk", Pins("K2")),
        IOStandard("LVCMOS33"),
    ),
    ("eth", 0,
        Subsignal("tx_data", Pins("F1 H2")),
        Subsignal("tx_en",   Pins("G1")),
        Subsignal("rx_data", Pins("J4 J5")),
        Subsignal("crs_dv",  Pins("J3")),
        Subsignal("mdio",    Pins("K3")),
        Subsignal("mdc",     Pins("L4")),
        Subsignal("rst_n",   Pins("L5")),
        IOStandard("LVCMOS33"),
    ),

    # Eight general-purpose LEDs, Bank 1, active low.
    ("user_led", 0, Pins("A13"), IOStandard("LVCMOS25")),
    ("user_led", 1, Pins("A12"), IOStandard("LVCMOS25")),
    ("user_led", 2, Pins("B19"), IOStandard("LVCMOS25")),
    ("user_led", 3, Pins("A18"), IOStandard("LVCMOS25")),
    ("user_led", 4, Pins("B18"), IOStandard("LVCMOS25")),
    ("user_led", 5, Pins("C17"), IOStandard("LVCMOS25")),
    ("user_led", 6, Pins("A17"), IOStandard("LVCMOS25")),
    ("user_led", 7, Pins("B17"), IOStandard("LVCMOS25")),
]


class ECP5EvalPlatform(LatticePlatform):
    def __init__(self):
        LatticePlatform.__init__(
            self,
            "LFE5UM5G-85F-8BG381",
            _io,
            toolchain="trellis",
        )

# 3. CRG: 12 MHz -> ECP5 PLL -> 50 MHz

# Two clock domains are produced from one PLL output:
#   cd_sys: CPU, bus interconnect, EchoSlave, MAC FIFOs.
#   cd_eth: LiteEth RMII pads; also driven out on ref_clk so the LAN8720
#           uses the same 50 MHz reference as the FPGA fabric.
# Both domains run at exactly 50 MHz, so no clock-domain crossing is
# needed between the MAC FIFO boundary and the rest of the SoC.

from migen import *
from litex.soc.cores.clock import ECP5PLL

SYS_CLK_FREQ = int(50e6)


class CRG(Module):
    def __init__(self, platform):
        self.rst = Signal()
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_eth = ClockDomain()

        clk12 = platform.request("clk12")

        self.submodules.pll = pll = ECP5PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk12, 12e6)
        pll.create_clkout(self.cd_sys, SYS_CLK_FREQ)
        pll.create_clkout(self.cd_eth, 50e6)



# 4. EchoSlave Wishbone wrapper
# Thin Migen shim around the Amaranth-generated echo_slave.v.
# Amaranth makes every clock domain explicit in the RTLIL it emits, so
# the generated Verilog has "clk" and "rst" as top-level input ports.
# These are tied to cd_sys so the slave runs in the main SoC clock domain.
# The 9-bit address bus covers words 0..511 (the full 512-word BRAM depth).

from litex.soc.interconnect import wishbone


class EchoSlaveWrapper(Module):
    def __init__(self):
        self.bus = bus = wishbone.Interface(data_width=32, adr_width=9)

        self.specials += Instance(
            "echo_slave",
            i_clk      = ClockSignal("sys"),
            i_rst      = ResetSignal("sys"),
            i_wb_cyc   = bus.cyc,
            i_wb_stb   = bus.stb,
            i_wb_we    = bus.we,
            i_wb_adr   = bus.adr,
            i_wb_dat_w = bus.dat_w,
            i_wb_sel   = bus.sel,
            o_wb_dat_r = bus.dat_r,
            o_wb_ack   = bus.ack,
        )



# 5. SoC

# Memory map:
#   0x00000000  ROM       32 KB  boot firmware (integrated BRAM)
#   0x10000000  SRAM      16 KB  stack and heap (integrated BRAM)
#   0x90000000  EchoSlave  2 KB  512 x 32-bit echo BRAM
#   0xB0000000  LiteEth    8 KB  MAC TX + RX SRAMs (wishbone slave)
#
# The firmware uses the LiteEth MAC wishbone slave to read received frames
# from the RX SRAM, copy payload words into EchoSlave via the echo address,
# read them back, write to the TX SRAM, then trigger transmit.

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import Builder
from litex.soc.integration.common import get_mem_data
from liteeth.phy.rmii import LiteEthPHYRMII
from liteeth.mac import LiteEthMAC

ECHO_BASE = 0x90000000
MAC_BASE  = 0xB0000000   # RX at +0x0000, TX at +0x1000


class EchoSoC(SoCCore):
    def __init__(self, platform, rom_init=[]):
        SoCCore.__init__(
            self,
            platform,
            clk_freq             = SYS_CLK_FREQ,
            cpu_type             = "vexriscv",
            cpu_variant          = "standard",
            integrated_rom_size  = 0x10000,   # 64 KB -- holds firmware_rom.bin
            integrated_rom_init  = rom_init,   # firmware baked in at build time
            integrated_sram_size = 0x4000,
            ident                = "ECP5 Ethernet Echo SoC",
            ident_version        = True,
            with_uart            = False,
            with_ctrl            = False,
        )

        # Clock and reset
        self.submodules.crg = CRG(platform)

        # Ethernet PHY: RMII, LAN8720, 50 MHz driven out from cd_eth
        self.submodules.ethphy = LiteEthPHYRMII(
            clock_pads = platform.request("eth_clocks"),
            pads       = platform.request("eth"),
            refclk_cd  = "eth",
        )

        # Ethernet MAC: CPU-driven wishbone interface.
        # With interface="wishbone", the MAC exposes two separate buses:
        #   bus_rx: CPU reads received frames from RX SRAM slots
        #   bus_tx: CPU writes frames to TX SRAM slots then triggers send
        # Each bus covers 2 slots x ceil(1530/4) = 2 x 383 words ~ 0x1000 bytes.
        self.submodules.ethmac = LiteEthMAC(
            phy               = self.ethphy,
            dw                = 32,
            interface         = "wishbone",
            endianness        = "big",
            with_preamble_crc = True,
        )
        # The region named "ethmac" generates ETHMAC_BASE in mem.h, which is
        # what libliteeth/udp.c uses to address RX and TX SRAM slots. TX slots
        # are at ETHMAC_BASE + ETHMAC_RX_SLOTS*ETHMAC_SLOT_SIZE = 0xB0001000.
        self.bus.add_slave("ethmac", self.ethmac.bus_rx,
                           SoCRegion(origin=MAC_BASE,          size=0x1000, cached=False))
        self.bus.add_slave("ethmac_tx", self.ethmac.bus_tx,
                           SoCRegion(origin=MAC_BASE + 0x1000, size=0x1000, cached=False))
        self.add_csr("ethmac")

        # Echo BRAM: 512 words x 4 bytes at ECHO_BASE
        self.submodules.echoslave = EchoSlaveWrapper()
        self.bus.add_slave("echoslave", self.echoslave.bus,
                           SoCRegion(origin=ECHO_BASE, size=0x800, cached=False))

        # Heartbeat: LED 0 blinks at ~1.5 Hz to confirm the SoC is running.
        # LED is active low, so ctr[25] = 0 means ON, 1 means OFF.
        led = platform.request("user_led", 0)
        ctr = Signal(26)
        self.sync += ctr.eq(ctr + 1)
        self.comb += led.eq(ctr[25])

        # Debug LEDs: firmware-controlled via CSR (active low, so hardware inverts).
        # Writing 1 to a bit turns the LED ON.
        # Bit 0 -> D6 (user_led 1, A12): main() reached
        # Bit 1 -> D7 (user_led 2, B19): udp_start() returned
        # Bit 2 -> D8 (user_led 3, A18): RX callback fired on port 1234
        # Bit 3 -> D9 (user_led 4, B18): reply sent
        # D11/D12 (user_led 6/7) left free.
        from litex.soc.cores.gpio import GPIOOut
        debug_sigs = Signal(4)
        self.submodules.debug_leds = GPIOOut(debug_sigs)
        self.add_csr("debug_leds")
        for i in range(4):
            dled = platform.request("user_led", i + 1)
            self.comb += dled.eq(~debug_sigs[i])



# 6. Build


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    build_dir    = os.path.join(root, "build")
    firmware_dir = os.path.join(root, "..", "firmware")
    firmware_rom = os.path.join(firmware_dir, "firmware_rom.bin")

    # Step 0: Export EchoSlave Verilog (needed by both passes).
    v_path = export_echo_slave(os.path.join(build_dir, "gateware"))

    # Step 1: Generate CSR headers without running synthesis.
    # The firmware includes generated/csr.h, so the headers must exist and
    # reflect the current SoC (including debug_leds CSR) before make runs.
    print("[headers] generating CSR headers ...")
    platform0 = ECP5EvalPlatform()
    platform0.add_source(v_path)
    soc0 = EchoSoC(platform0)
    Builder(soc0, output_dir=build_dir,
            compile_gateware=False, compile_software=False).build(
        build_name="ecp5_ethernet_soc", run=False)

    # Step 2: Compile firmware with the freshly generated CSR headers.
    print("[firmware] compiling firmware_rom.bin ...")
    subprocess.run(["make", "-C", firmware_dir, "firmware_rom.bin"], check=True)

    # Step 3: Load firmware binary as ROM init data.
    rom_init = get_mem_data(firmware_rom, data_width=32, endianness="little")
    print(f"[firmware] {len(rom_init)*4} bytes loaded into ROM")

    # Step 4: Build full gateware with firmware baked in.
    platform = ECP5EvalPlatform()
    platform.add_source(v_path)
    soc = EchoSoC(platform, rom_init=rom_init)
    Builder(soc, output_dir=build_dir,
            compile_gateware=True, compile_software=False).build(
        build_name="ecp5_ethernet_soc")
    print("[done] build/gateware/ecp5_ethernet_soc.bit")
