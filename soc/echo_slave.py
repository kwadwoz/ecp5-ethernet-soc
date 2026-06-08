"""
Wishbone slave for the ethernet echo SoC.

Stores 32-bit words on write; returns the same words on read.
This is the only piece of the SoC that the user builds in hardware.
Everything else (LiteEth, VexRiscv, bus, firmware) is infrastructure.

Requires Amaranth >= 0.5.
"""

from amaranth.hdl import Elaboratable, Module, Signal
from amaranth.lib.memory import Memory

# 512 words x 4 bytes = 2048 bytes of storage.
# Covers the 1400-byte maximum payload used in the host latency sweep.
# 9-bit address (0..511) matches the depth exactly.
DEPTH = 512


class EchoSlave(Elaboratable):
    """
    Wishbone target (slave).

    Timing:
      Cycle N   : master asserts cyc+stb. For a write, wr.en fires
                  combinatorially so the data is captured at the rising
                  edge of cycle N+1.
      Cycle N+1 : ack goes high. For a read, dat_r is valid here because
                  the registered read port latches mem[adr_N] at this edge.
      Cycle N+2 : ack clears.

    The ~wb_ack guard prevents a held stb from generating repeated acks.
    Back-to-back transactions work: re-assert stb after ack clears.

    sel is accepted but ignored. All accesses are full 32-bit words.
    The VexRiscv firmware always uses sel=0xF, so byte granularity is
    never needed here.

    Port names below become Verilog port names after Amaranth RTLIL +
    yosys conversion. The LiteX Instance wrapper in build_soc.py must
    match them exactly.
    """

    def __init__(self, depth=DEPTH):
        self.depth = depth

        # (depth - 1).bit_length() = 9 for depth=512.
        # 9 bits addresses exactly 0..511.
        addr_bits = (depth - 1).bit_length()

        # Wishbone inputs (driven by the bus master / firmware).
        self.wb_cyc   = Signal()
        self.wb_stb   = Signal()
        self.wb_we    = Signal()
        self.wb_adr   = Signal(addr_bits)
        self.wb_dat_w = Signal(32)
        self.wb_sel   = Signal(4)

        # Wishbone outputs (driven by this slave).
        self.wb_dat_r = Signal(32)
        self.wb_ack   = Signal()

    def elaborate(self, platform):
        m = Module()

        # Memory without init so synthesis infers block RAM on ECP5.
        # Only Memory itself is a submodule; read/write ports are
        # wiring interfaces obtained from it, not separate submodules.
        m.submodules.mem = mem = Memory(shape=32, depth=self.depth, init=[])
        rd = mem.read_port(domain="sync", transparent_for=[])
        wr = mem.write_port(domain="sync")

        # Address and data: combinatorial wiring to the memory ports.
        m.d.comb += [
            rd.addr.eq(self.wb_adr),
            wr.addr.eq(self.wb_adr),
            wr.data.eq(self.wb_dat_w),
            self.wb_dat_r.eq(rd.data),
        ]

        # Write enable fires the cycle stb arrives. The write completes
        # on the next clock edge, the same edge ack fires. ~wb_ack stops
        # a second write if the master holds stb across the ack cycle.
        m.d.comb += wr.en.eq(
            self.wb_cyc & self.wb_stb & self.wb_we & ~self.wb_ack
        )

        # Ack: assert one cycle after cyc+stb, then clear.
        with m.If(self.wb_cyc & self.wb_stb & ~self.wb_ack):
            m.d.sync += self.wb_ack.eq(1)
        with m.Else():
            m.d.sync += self.wb_ack.eq(0)

        return m

    def ports(self):
        """Top-level ports for Verilog generation via rtlil + yosys."""
        return [
            self.wb_cyc, self.wb_stb, self.wb_we,
            self.wb_adr, self.wb_dat_w, self.wb_sel,
            self.wb_dat_r, self.wb_ack,
        ]
