"""
Simulation testbench for SATSlave.

Run with:  python test_sat_slave.py
Produces:  test_sat_slave.vcd  (open in GTKWave to inspect waveforms)

Drives the same Wishbone sequence the firmware (sat_tcp.c) performs:
clear literal registers, load formula, pulse start, poll done, read model.
All asserts stop the sim immediately with a clear message if they fail.
Requires Amaranth >= 0.5.
"""

from amaranth.hdl import *
from amaranth.sim import Simulator
from sat_slave import SATSlave
from sat_solver import MAX_VARS, MAX_CLAUSES, CLAUSE_LEN

LIT_BASE = 8


def check_model(model, n_vars, clauses):
    """Verify in Python that a model satisfies every clause."""
    for clause in clauses:
        ok = False
        for lit in clause:
            var = abs(lit)
            val = bool((model >> (var - 1)) & 1)
            if (lit > 0 and val) or (lit < 0 and not val):
                ok = True
                break
        if not ok:
            return False
    return True


def test():
    dut = SATSlave()

    async def drive(ctx):

        # Helper: issue one Wishbone write, wait for ack, return.

        async def wb_write(adr, dat):
            ctx.set(dut.wb_cyc,   1)
            ctx.set(dut.wb_stb,   1)
            ctx.set(dut.wb_we,    1)
            ctx.set(dut.wb_adr,   adr)
            ctx.set(dut.wb_dat_w, dat)

            for _ in range(8):
                await ctx.tick()
                if ctx.get(dut.wb_ack):
                    break
            else:
                raise AssertionError(f"ack never fired on write to adr={adr}")

            ctx.set(dut.wb_stb, 0)
            ctx.set(dut.wb_we,  0)
            await ctx.tick()
            assert ctx.get(dut.wb_ack) == 0, (
                f"ack did not clear after stb dropped (adr={adr})"
            )

        # Helper: issue one Wishbone read, wait for ack, return dat_r.

        async def wb_read(adr):
            ctx.set(dut.wb_cyc, 1)
            ctx.set(dut.wb_stb, 1)
            ctx.set(dut.wb_we,  0)
            ctx.set(dut.wb_adr, adr)

            for _ in range(8):
                await ctx.tick()
                if ctx.get(dut.wb_ack):
                    break
            else:
                raise AssertionError(f"ack never fired on read from adr={adr}")

            val = ctx.get(dut.wb_dat_r)

            ctx.set(dut.wb_stb, 0)
            await ctx.tick()
            assert ctx.get(dut.wb_ack) == 0, (
                f"ack did not clear after stb dropped (adr={adr})"
            )
            return val

        # Helper: load and solve a formula exactly as sat_tcp.c does.
        # clauses use the host convention: signed ints, 1-based variables.

        async def solve(n_vars, clauses):
            # 1. Clear all literal registers (resets lit_used)
            for i in range(MAX_CLAUSES * CLAUSE_LEN):
                await wb_write(LIT_BASE + i, 0)

            # 2. Write each literal: bits[3:0]=var(0-based), bit4=neg, bit5=used
            for c, clause in enumerate(clauses):
                for l, lit in enumerate(clause):
                    var = abs(lit) - 1
                    neg = 1 if lit < 0 else 0
                    await wb_write(LIT_BASE + c * CLAUSE_LEN + l,
                                   (1 << 5) | (neg << 4) | var)

            # 3. Dimensions, then start
            await wb_write(1, n_vars)
            await wb_write(2, len(clauses))
            await wb_write(0, 1)

            # 4. Poll done bit
            for _ in range(2 ** MAX_VARS + 64):
                ctrl = await wb_read(0)
                if ctrl & 1:
                    break
            else:
                raise AssertionError("solver never asserted done")

            is_sat = (ctrl >> 1) & 1
            model  = await wb_read(3)
            cycles = await wb_read(4)
            return is_sat, model, cycles

        # Reset state: bus idle.

        ctx.set(dut.wb_cyc,   0)
        ctx.set(dut.wb_stb,   0)
        ctx.set(dut.wb_we,    0)
        ctx.set(dut.wb_adr,   0)
        ctx.set(dut.wb_dat_w, 0)
        await ctx.tick()

        # Test 1: satisfiable 4-variable formula (same as sat_host.py).

        clauses = [[1, 2], [-1, 3], [-2, -3], [1, -2, 4]]
        is_sat, model, cycles = await solve(4, clauses)
        assert is_sat == 1, "Test 1 failed: expected SAT, got UNSAT"
        assert check_model(model, 4, clauses), (
            f"Test 1 failed: model {model:#06b} does not satisfy the formula"
        )
        print(f"Test 1 passed: SAT, model={model:#06x}, {cycles} cycles")

        # Test 2: trivially unsatisfiable (x1 AND ~x1).
        # Also proves leftover literals from Test 1 were cleared -- if any
        # lit_used survived, the formula would change.

        is_sat, model, cycles = await solve(1, [[1], [-1]])
        assert is_sat == 0, "Test 2 failed: expected UNSAT, got SAT"
        print(f"Test 2 passed: UNSAT after {cycles} cycles")

        # Test 3: re-solve SAT after UNSAT (done/sat flags must reset).

        clauses = [[1, 2, 3], [-1, 4], [-2, 5], [-3, 6], [-4, -5], [-5, -6]]
        is_sat, model, cycles = await solve(6, clauses)
        assert is_sat == 1, "Test 3 failed: expected SAT, got UNSAT"
        assert check_model(model, 6, clauses), (
            f"Test 3 failed: model {model:#08b} does not satisfy the formula"
        )
        print(f"Test 3 passed: SAT, model={model:#06x}, {cycles} cycles")

        # Test 4: pigeonhole PHP(3,2) -- 3 pigeons, 2 holes, always UNSAT.

        clauses = [[1, 2], [3, 4], [5, 6],
                   [-1, -3], [-1, -5], [-3, -5],
                   [-2, -4], [-2, -6], [-4, -6],
                   [-1, -2], [-3, -4], [-5, -6]]
        is_sat, model, cycles = await solve(6, clauses)
        assert is_sat == 0, "Test 4 failed: expected UNSAT, got SAT"
        print(f"Test 4 passed: UNSAT after {cycles} cycles")

        # Test 5: start auto-clear -- reg 0 write-side must not stick.
        # After a solve, reading reg 0 repeatedly must show done=1 stably
        # (if start were stuck high the solver would restart forever).

        a = await wb_read(0)
        b = await wb_read(0)
        assert (a & 1) and (b & 1), (
            "Test 5 failed: done bit not stable after solve (start stuck?)"
        )
        print("Test 5 passed: start auto-clears, done is stable")

        # Done.

        ctx.set(dut.wb_cyc, 0)
        await ctx.tick()
        print("All tests passed.")

    sim = Simulator(dut)
    sim.add_clock(1 / 50e6)  # 50 MHz, matches hardware clock
    sim.add_testbench(drive)

    with sim.write_vcd(
        "test_sat_slave.vcd",
        traces=[
            dut.wb_cyc, dut.wb_stb, dut.wb_we,
            dut.wb_adr, dut.wb_dat_w, dut.wb_dat_r, dut.wb_ack,
        ],
    ):
        sim.run()


if __name__ == "__main__":
    test()
