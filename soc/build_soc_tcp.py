#!/usr/bin/env python3
"""
build_soc_tcp.py -- ECP5 Evaluation Board Ethernet SAT Solver SoC

Steps:
  1. Exports SATSlave (Amaranth HDL) to Verilog via yosys.
  2. Defines a LiteX SoC: VexRiscv + LiteEth RMII + SATSlave Wishbone slave.
  3. Runs yosys + nextpnr-ecp5 + ecppack and writes a bitstream.

Board:  LFE5UM5G-85F-EVN  (device LFE5UM5G-85F-8BG381)
PHY:    LAN8720A breakout
Clock:  12 MHz FTDI oscillator at A10 -> PLL -> 50 MHz cd_sys
        PHY drives 50 MHz REF_CLK on J4 (GR_PCLK6_0) -> cd_eth

Hardware-verified pin assignments (see baseline_tests/FINDINGS.md):
  J4   REF_CLK  Input  50 MHz from PHY; global-clock-capable (GR_PCLK6_0)
  L4   MDIO     Bidir  1.5 kΩ pull-up on breakout required
  K4   MDC      Output SMI clock
  G1   RXD[0]   Input
  N5   RXD[1]   Input
  L5   CRS_DV   Input
  J5   TXEN     Output
  K2   TXD[0]   Output
  M5   TXD[1]   Output
  nRST not wired; pulled high on breakout board.

Clock note: the 12 MHz clock from FTDI is only present when the USB
programming cable is plugged into the board. Keep it connected during
operation.

Usage:
  cd soc && python build_soc_tcp.py
Output:
  /tmp/ecp5-soc-build-tcp/gateware/ecp5_ethernet_soc.bit
"""

import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))



# 1. Export SATSlave to Verilog

# Amaranth converts the design to RTLIL (its internal representation).
# Yosys reads that IR, optimises it, renames the top module from "top"
# to "sat_slave", and writes synthesisable Verilog. The file is added
# as a platform source before LiteX invokes synthesis so yosys picks it
# up during the full SoC build.

def export_sat_slave(out_dir):
    from amaranth.back.rtlil import convert
    from sat_slave import SATSlave

    os.makedirs(out_dir, exist_ok=True)
    il_path = os.path.join(out_dir, "sat_slave.il")
    v_path  = os.path.join(out_dir, "sat_slave.v")

    dut = SATSlave()
    with open(il_path, "w") as f:
        f.write(convert(dut, ports=dut.ports()))

    ys_path = os.path.join(out_dir, "sat_slave.ys")
    with open(ys_path, "w") as f:
        f.write(f'read_rtlil "{il_path}"\n')
        f.write('hierarchy -check -top top\n')
        f.write('proc; opt\n')
        f.write('rename top sat_slave\n')
        f.write(f'write_verilog "{v_path}"\n')

    subprocess.run(["yosys", "-q", "-s", ys_path], check=True)
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

    # LAN8720A RMII. REF_CLK is an INPUT: the PHY drives 50 MHz on J4
    # (PL50A / GR_PCLK6_0 -- global-clock-capable). The FPGA receives this
    # and uses it as cd_eth. refclk_cd=None in LiteEthPHYRMII prevents the
    # FPGA from trying to drive it back out.
    ("eth_clocks", 0,
        Subsignal("ref_clk", Pins("J4")),
        IOStandard("LVCMOS33"),
    ),
    ("eth", 0,
        Subsignal("tx_data", Pins("K2 M5")),
        Subsignal("tx_en",   Pins("J5")),
        Subsignal("rx_data", Pins("G1 N5")),
        Subsignal("crs_dv",  Pins("L5")),
        Subsignal("mdio",    Pins("L4")),
        Subsignal("mdc",     Pins("K4")),
        # rst_n omitted: nRST not wired; pulled high on breakout.
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

# 3. CRG: 12 MHz -> ECP5 PLL -> 50 MHz (cd_sys)
#         PHY REF_CLK on J4 -> cd_eth
#
# cd_sys: CPU, bus interconnect, SATSlave, MAC FIFOs -- from local PLL.
# cd_eth: LiteEth RMII TX/RX pads -- clocked by the PHY's 50 MHz REF_CLK
#         output on J4 (GR_PCLK6_0). The two 50 MHz domains are asynchronous;
#         LiteEthMAC's FIFOs handle the crossing.
#
# The CRG requests eth_clocks so the same pad record can be forwarded to
# LiteEthPHYRMII without a second platform.request() call.

from migen import *
from litex.soc.cores.clock import ECP5PLL

SYS_CLK_FREQ = int(50e6)


class CRG(Module):
    def __init__(self, platform):
        self.rst = Signal()
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_eth = ClockDomain()

        clk12 = platform.request("clk12")
        self.eth_clocks = platform.request("eth_clocks")

        self.submodules.pll = pll = ECP5PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk12, 12e6)
        pll.create_clkout(self.cd_sys, SYS_CLK_FREQ)

        # cd_eth is driven by the PHY's 50 MHz REF_CLK on J4 (GR_PCLK6_0).
        # nextpnr-ecp5 routes PCLK-capable input pins through the global clock
        # network automatically when the signal feeds a clock domain.
        self.comb += self.cd_eth.clk.eq(self.eth_clocks.ref_clk)



# 4. SATSlave Wishbone wrapper
# Thin Migen shim around the Amaranth-generated sat_slave.v.
# Amaranth makes every clock domain explicit in the RTLIL it emits, so
# the generated Verilog has "clk" and "rst" as top-level input ports.
# These are tied to cd_sys so the slave runs in the main SoC clock domain.
# The 9-bit address bus covers words 0..511; SAT registers occupy 0..207.

from litex.soc.interconnect import wishbone


class SATSlaveWrapper(Module):
    def __init__(self):
        self.bus = bus = wishbone.Interface(data_width=32, adr_width=9)

        self.specials += Instance(
            "sat_slave",
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
#   0x00000000  ROM       64 KB  boot firmware (integrated BRAM)
#   0x10000000  SRAM      16 KB  stack and heap (integrated BRAM)
#   0x90000000  SATSlave   2 KB  SAT solver register file
#   0xB0000000  LiteEth    8 KB  MAC TX + RX SRAMs (wishbone slave)
#
# The firmware (sat_tcp.c, via lwIP) parses SAT formulas from TCP, loads
# the SATSlave registers, polls the done bit, and replies with the result.

from litex.soc.integration.soc_core import SoCCore
from litex.soc.integration.soc import SoCRegion
from litex.soc.integration.builder import Builder
from litex.soc.integration.common import get_mem_data
from liteeth.phy.rmii import LiteEthPHYRMII
from liteeth.mac import LiteEthMAC

SAT_BASE = 0x90000000
MAC_BASE = 0xB0000000   # RX at +0x0000, TX at +0x1000


class SATSoC(SoCCore):
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
            ident                = "ECP5 Ethernet SAT Solver SoC",
            ident_version        = True,
            with_uart            = False,
            with_ctrl            = False,
        )

        # Clock and reset
        self.submodules.crg = CRG(platform)

        # Ethernet PHY: RMII, LAN8720A.
        # clock_pads is the pad already requested by CRG (avoids double-request).
        # refclk_cd=None: PHY drives REF_CLK; FPGA does not generate it.
        self.submodules.ethphy = LiteEthPHYRMII(
            clock_pads = self.crg.eth_clocks,
            pads       = platform.request("eth"),
            refclk_cd  = None,
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
            endianness        = "little",
            with_preamble_crc = True,
        )
        # The region named "ethmac" generates ETHMAC_BASE in mem.h, which is
        # what libliteeth/udp.c uses to address RX and TX SRAM slots. TX slots
        # are at ETHMAC_BASE + ETHMAC_RX_SLOTS*ETHMAC_SLOT_SIZE = 0xB0001000.
        self.bus.add_slave("ethmac", self.ethmac.bus_rx,
                           SoCRegion(origin=MAC_BASE,          size=0x1000, cached=False))
        self.bus.add_slave("ethmac_tx", self.ethmac.bus_tx,
                           SoCRegion(origin=MAC_BASE + 0x1000, size=0x1000, cached=False))

        # SAT slave: register file (same address the echo BRAM used to occupy)
        self.submodules.satslave = SATSlaveWrapper()
        self.bus.add_slave("satslave", self.satslave.bus,
                           SoCRegion(origin=SAT_BASE, size=0x800, cached=False))

        # Heartbeat: LED 0 blinks at ~1.5 Hz to confirm the SoC is running.
        # LED is active low, so ctr[25] = 0 means ON, 1 means OFF.
        led = platform.request("user_led", 0)
        ctr = Signal(26)
        self.sync += ctr.eq(ctr + 1)
        self.comb += led.eq(ctr[25])

        # Debug LEDs: firmware-controlled via CSR (active low, so hardware inverts).
        # Writing 1 to a bit turns the LED ON.
        # Bit 0 -> D6 (user_led 1, A12): main() reached
        # Bit 1 -> D7 (user_led 2, B19): lwIP netif up
        # Bit 2 -> D8 (user_led 3, A18): TCP data received
        # Bit 3 -> D9 (user_led 4, B18): TCP reply sent / connection active
        # D11/D12 (user_led 6/7) left free.
        from litex.soc.cores.gpio import GPIOOut
        debug_sigs = Signal(4)
        self.submodules.debug_leds = GPIOOut(debug_sigs)
        for i in range(4):
            dled = platform.request("user_led", i + 1)
            self.comb += dled.eq(~debug_sigs[i])



# 6. Build


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    # Build into /tmp to avoid spaces in the project path breaking make rules
    # inside the LiteX libc Makefile (make splits on spaces in target names).
    build_dir    = "/tmp/ecp5-soc-build-tcp"
    firmware_dir = os.path.join(root, "..", "firmware-tcp")
    firmware_rom = os.path.join(firmware_dir, "firmware_rom.bin")

    # Step 0: Export SATSlave Verilog (needed by both passes).
    v_path = export_sat_slave(os.path.join(build_dir, "gateware"))

    # Step 1: Generate CSR headers without running synthesis.
    # The firmware includes generated/csr.h, so the headers must exist and
    # reflect the current SoC (including debug_leds CSR) before make runs.
    print("[headers] generating CSR headers and building LiteX libraries ...")
    platform0 = ECP5EvalPlatform()
    platform0.add_source(v_path)
    soc0 = SATSoC(platform0)
    try:
        Builder(soc0, output_dir=build_dir,
                compile_gateware=False, compile_software=True).build(
            build_name="ecp5_ethernet_soc", run=False)
    except subprocess.CalledProcessError:
        # The LiteX BIOS fails to link with with_uart=False (uart_read_nonblock
        # is undefined). That's expected — we use custom firmware, not the BIOS.
        # Abort only if the libraries our firmware actually needs are missing.
        missing = [
            lib for lib in [
                "libc/libc.a",
                "libcompiler_rt/libcompiler_rt.a",
                "libbase/libbase.a",
            ]
            if not os.path.exists(os.path.join(build_dir, "software", lib))
        ]
        if missing:
            raise RuntimeError(f"Required libraries not built: {missing}")
        print("[libs] BIOS skipped (no UART); required libraries present.")

    # Step 2: Compile firmware with the freshly generated CSR headers.
    print("[firmware] compiling firmware_rom.bin ...")
    subprocess.run(["make", "-C", firmware_dir, "firmware_rom.bin"], check=True)

    # Step 3: Load firmware binary as ROM init data.
    rom_init = get_mem_data(firmware_rom, data_width=32, endianness="little")
    print(f"[firmware] {len(rom_init)*4} bytes loaded into ROM")

    # Step 4: Build full gateware with firmware baked in.
    platform = ECP5EvalPlatform()
    platform.add_source(v_path)
    soc = SATSoC(platform, rom_init=rom_init)
    Builder(soc, output_dir=build_dir,
            compile_gateware=True, compile_software=False).build(
        build_name="ecp5_ethernet_soc")
    print("[done] /tmp/ecp5-soc-build-tcp/gateware/ecp5_ethernet_soc.bit")
