"""
sat_slave.py -- Wishbone slave wrapping BruteForceSAT (Amaranth HDL 0.5.x)

Register map (32-bit word offsets):
  0    W: bit0=start (auto-clears next cycle)   R: bit0=done, bit1=sat
  1    W: n_vars  (4 bits, 1..MAX_VARS)
  2    W: n_clauses (5 bits, 1..MAX_CLAUSES)
  3    R: model   (MAX_VARS bits -- bit i = value of variable i+1)
  4    R: cycles  (20 bits, diagnostic)
  8 + c*CLAUSE_LEN + l   W: literal register
      bits[3:0] = var (0-based), bit4 = neg, bit5 = used

Address width: 9 bits (matches EchoSlave).
"""

from amaranth import *
from sat_solver import BruteForceSAT, MAX_VARS, MAX_CLAUSES, CLAUSE_LEN

_LIT_COUNT = MAX_CLAUSES * CLAUSE_LEN   # 200 literal registers
_LIT_BASE  = 8


class SATSlave(Elaboratable):
    def __init__(self):
        self.wb_cyc   = Signal()
        self.wb_stb   = Signal()
        self.wb_we    = Signal()
        self.wb_adr   = Signal(9)
        self.wb_dat_w = Signal(32)
        self.wb_sel   = Signal(4)
        self.wb_dat_r = Signal(32)
        self.wb_ack   = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.sat = sat = BruteForceSAT()

        # Control registers
        start_r     = Signal()
        n_vars_r    = Signal(range(MAX_VARS + 1))
        n_clauses_r = Signal(range(MAX_CLAUSES + 1))

        # Literal registers: packed as {used[5], neg[4], var[3:0]}
        lit_regs = [Signal(6, name=f"lit_{i}") for i in range(_LIT_COUNT)]

        # Wire registers to BruteForceSAT
        m.d.comb += [
            sat.start.eq(start_r),
            sat.n_vars.eq(n_vars_r),
            sat.n_clauses.eq(n_clauses_r),
        ]
        for c in range(MAX_CLAUSES):
            for l in range(CLAUSE_LEN):
                reg = lit_regs[c * CLAUSE_LEN + l]
                m.d.comb += sat.lit_var[c][l].eq(reg[:4])
                m.d.comb += sat.lit_neg[c][l].eq(reg[4])
                m.d.comb += sat.lit_used[c][l].eq(reg[5])

        # Auto-clear start after one cycle
        with m.If(start_r):
            m.d.sync += start_r.eq(0)

        # Ack: registered 1 cycle after cyc&stb, cleared otherwise (matches EchoSlave)
        with m.If(self.wb_cyc & self.wb_stb & ~self.wb_ack):
            m.d.sync += self.wb_ack.eq(1)
        with m.Else():
            m.d.sync += self.wb_ack.eq(0)

        # Write (fires on the cycle before ack)
        active_write = Signal()
        m.d.comb += active_write.eq(
            self.wb_cyc & self.wb_stb & self.wb_we & ~self.wb_ack
        )

        with m.If(active_write):
            with m.Switch(self.wb_adr):
                with m.Case(0):
                    m.d.sync += start_r.eq(self.wb_dat_w[0])
                with m.Case(1):
                    m.d.sync += n_vars_r.eq(self.wb_dat_w[:4])
                with m.Case(2):
                    m.d.sync += n_clauses_r.eq(self.wb_dat_w[:5])
                for i in range(_LIT_COUNT):
                    with m.Case(_LIT_BASE + i):
                        m.d.sync += lit_regs[i].eq(self.wb_dat_w[:6])

        # Read (combinatorial)
        with m.Switch(self.wb_adr):
            with m.Case(0):
                m.d.comb += self.wb_dat_r.eq(Cat(sat.done, sat.sat))
            with m.Case(3):
                m.d.comb += self.wb_dat_r.eq(sat.model)
            with m.Case(4):
                m.d.comb += self.wb_dat_r.eq(sat.cycles)
            with m.Default():
                m.d.comb += self.wb_dat_r.eq(0)

        return m

    def ports(self):
        return [
            self.wb_cyc, self.wb_stb, self.wb_we,
            self.wb_adr, self.wb_dat_w, self.wb_sel,
            self.wb_dat_r, self.wb_ack,
        ]
