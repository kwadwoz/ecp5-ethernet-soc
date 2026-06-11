"""
sat_solver.py -- Brute-force SAT solver hardware module (Amaranth HDL 0.5.x)

Copied verbatim from Andrew-Bonilla/fpga-sat-solver.

How it works:
Every clock cycle all clauses are evaluated combinationally in parallel against
the current candidate assignment. A binary counter increments the assignment
each cycle. When a satisfying assignment is found, done and sat go high. When
all 2^n_vars assignments have been tried with no solution, done goes high and
sat stays low.
"""

from amaranth import *

MAX_VARS    = 10
MAX_CLAUSES = 20
CLAUSE_LEN  = 10


class BruteForceSAT(Elaboratable):
    """
    Ports

    Inputs:
      start          1 bit   pulse high for 1 cycle to begin or restart
      n_vars         4 bits  number of variables (1 to MAX_VARS)
      n_clauses      5 bits  number of clauses (1 to MAX_CLAUSES)
      lit_var[c][l]  4 bits  which variable (0-based) is in clause c, slot l
      lit_neg[c][l]  1 bit   1 = this literal is negated
      lit_used[c][l] 1 bit   1 = this slot is occupied

    Outputs:
      done           1 bit   goes high when search is finished
      sat            1 bit   1 = satisfiable (only valid when done=1)
      model          10 bits satisfying assignment -- bit i = value of var i+1
      cycles         20 bits clock cycles taken (diagnostic)
    """

    def __init__(self):
        self.start     = Signal()
        self.n_vars    = Signal(range(MAX_VARS + 1))
        self.n_clauses = Signal(range(MAX_CLAUSES + 1))

        self.lit_var  = [[Signal(range(MAX_VARS), name=f"lv_{c}_{l}")
                          for l in range(CLAUSE_LEN)] for c in range(MAX_CLAUSES)]
        self.lit_neg  = [[Signal(name=f"ln_{c}_{l}")
                          for l in range(CLAUSE_LEN)] for c in range(MAX_CLAUSES)]
        self.lit_used = [[Signal(name=f"lu_{c}_{l}")
                          for l in range(CLAUSE_LEN)] for c in range(MAX_CLAUSES)]

        self.done   = Signal()
        self.sat    = Signal()
        self.model  = Signal(MAX_VARS)
        self.cycles = Signal(20)

    def elaborate(self, platform):
        m = Module()

        assignment = Signal(MAX_VARS)
        running    = Signal()
        done_r     = Signal()
        sat_r      = Signal()
        model_r    = Signal(MAX_VARS)
        cycles_r   = Signal(20)

        clause_sat = [Signal(name=f"cs_{c}") for c in range(MAX_CLAUSES)]

        for c in range(MAX_CLAUSES):
            lit_vals = []
            for l in range(CLAUSE_LEN):
                var_val = Signal(name=f"vv_{c}_{l}")
                lit_val = Signal(name=f"lval_{c}_{l}")
                m.d.comb += var_val.eq(assignment.word_select(self.lit_var[c][l], 1))
                m.d.comb += lit_val.eq(
                    Mux(self.lit_neg[c][l], ~var_val, var_val) & self.lit_used[c][l]
                )
                lit_vals.append(lit_val)
            m.d.comb += clause_sat[c].eq(Cat(*lit_vals).any())

        all_sat      = Signal()
        results_vec  = Signal(MAX_CLAUSES)
        inactive_vec = Signal(MAX_CLAUSES)

        for ci in range(MAX_CLAUSES):
            m.d.comb += results_vec[ci].eq(clause_sat[ci])
            m.d.comb += inactive_vec[ci].eq(ci >= self.n_clauses)

        m.d.comb += all_sat.eq((results_vec | inactive_vec).all())

        max_assign = Signal(MAX_VARS)
        m.d.comb += max_assign.eq((1 << self.n_vars) - 1)

        with m.If(self.start):
            m.d.sync += [
                assignment.eq(0),
                done_r.eq(0),
                sat_r.eq(0),
                model_r.eq(0),
                cycles_r.eq(0),
                running.eq(1),
            ]
        with m.Elif(running):
            m.d.sync += cycles_r.eq(cycles_r + 1)
            with m.If(all_sat):
                m.d.sync += [
                    done_r.eq(1),
                    sat_r.eq(1),
                    model_r.eq(assignment),
                    running.eq(0),
                ]
            with m.Elif(assignment == max_assign):
                m.d.sync += [
                    done_r.eq(1),
                    sat_r.eq(0),
                    running.eq(0),
                ]
            with m.Else():
                m.d.sync += assignment.eq(assignment + 1)

        m.d.comb += [
            self.done.eq(done_r),
            self.sat.eq(sat_r),
            self.model.eq(model_r),
            self.cycles.eq(cycles_r),
        ]

        return m
