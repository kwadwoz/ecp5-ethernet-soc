"""
Simulation testbench for Echo.

Run with:  python test_echo_slave.py
Produces:  test_echo_slave.vcd  (open in GTKWave to inspect waveforms)

All asserts stop the sim immediately with a clear message if they fail.
Passing this test is a prerequisite before running build_soc.py.
Requires Amaranth >= 0.5.
"""

from amaranth.hdl import *
from amaranth.sim import Simulator
from echo_slave import EchoSlave


def test():
    dut = EchoSlave()

    async def drive(ctx):
        #
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

            # Drop stb; ack must clear on the next cycle.
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

      
        # Reset state: bus idle.
        
        ctx.set(dut.wb_cyc,   0)
        ctx.set(dut.wb_stb,   0)
        ctx.set(dut.wb_we,    0)
        ctx.set(dut.wb_adr,   0)
        ctx.set(dut.wb_dat_w, 0)
        await ctx.tick()

       
        # Test 1: write 0xDEADBEEF to address 0, read it back.
      
        await wb_write(0, 0xDEAD_BEEF)
        got = await wb_read(0)
        assert got == 0xDEAD_BEEF, (
            f"Test 1 failed: expected 0xDEADBEEF at adr=0, got {got:#010x}"
        )


        # Test 2: write 0xCAFEBABE to address 1. Confirm address 0 is
        # unchanged (no aliasing between adjacent slots).

        await wb_write(1, 0xCAFE_BABE)

        got = await wb_read(0)
        assert got == 0xDEAD_BEEF, (
            f"Test 2 aliasing: adr=0 changed after write to adr=1, got {got:#010x}"
        )

        got = await wb_read(1)
        assert got == 0xCAFE_BABE, (
            f"Test 2 failed: expected 0xCAFEBABE at adr=1, got {got:#010x}"
        )

        
        # Test 3: overwrite address 0, confirm address 1 is unchanged.
       
        await wb_write(0, 0x1234_5678)

        got = await wb_read(1)
        assert got == 0xCAFE_BABE, (
            f"Test 3 aliasing: adr=1 changed after write to adr=0, got {got:#010x}"
        )

        got = await wb_read(0)
        assert got == 0x1234_5678, (
            f"Test 3 failed: expected 0x12345678 at adr=0, got {got:#010x}"
        )

        
        # Done.
    
        ctx.set(dut.wb_cyc, 0)
        await ctx.tick()
        print("All tests passed.")

    sim = Simulator(dut)
    sim.add_clock(1 / 50e6)  # 50 MHz, matches hardware clock
    sim.add_testbench(drive)

    with sim.write_vcd(
        "test_echo_slave.vcd",
        gtkw_file="test_echo_slave.gtkw",
        traces=[
            dut.wb_cyc, dut.wb_stb, dut.wb_we,
            dut.wb_adr, dut.wb_dat_w, dut.wb_dat_r, dut.wb_ack,
        ],
    ):
        sim.run()


if __name__ == "__main__":
    test()