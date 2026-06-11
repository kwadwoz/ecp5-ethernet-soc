# SAT Solver Integration (TCP)

This branch (`sat-solver`) replaces the TCP **echo** SoC with a TCP **SAT solver accelerator**.
The EchoSlave BRAM passthrough is swapped out for `BruteForceSAT` — a brute-force SAT
solver in hardware (from [Andrew-Bonilla/fpga-sat-solver](https://github.com/Andrew-Bonilla/fpga-sat-solver)) —
exposed to the CPU as a Wishbone register file. The host sends CNF formulas over TCP;
the FPGA solves them in hardware and replies SAT (with a satisfying assignment) or UNSAT.

Built on top of the `tcp` branch: lwIP firmware (`firmware-tcp/`), TCP build script
(`soc/build_soc_tcp.py`).

---

## Data Flow

```
Host (sat_host.py)
  │  TCP port 1234: 0xAA n_vars n_clauses [literals 0x00]... 0xFF
  ▼
lwIP firmware (sat_tcp.c on VexRiscv)
  │  parses packet, writes registers over Wishbone
  ▼
SATSlave register file @ 0x90000000  (soc/sat_slave.py)
  │  start pulse → solver runs
  ▼
BruteForceSAT (soc/sat_solver.py)
  │  tries all 2^n_vars assignments, ≤1024 cycles ≈ 20 µs @ 50 MHz
  ▼
firmware polls done bit, reads model, sends TCP reply
  │  SAT:   0x01 [assignment bytes] 0xFF
  │  UNSAT: 0x00 0xFF
  ▼
Host prints result
```

---

## New Files

### `soc/sat_solver.py`
`BruteForceSAT` Amaranth module, copied verbatim from the fpga-sat-solver repo.
Evaluates **all clauses combinationally in parallel** every cycle while a binary
counter sweeps candidate assignments. Limits: `MAX_VARS=10`, `MAX_CLAUSES=20`,
`CLAUSE_LEN=10` (literals per clause).

### `soc/sat_slave.py`
`SATSlave` — Amaranth Wishbone slave wrapping `BruteForceSAT`. Same port names,
ack timing (registered 1-cycle ack), and 9-bit address width as the old
`echo_slave.py`, so the LiteX integration pattern is unchanged.

**Register map (32-bit word offsets from `SATSLAVE_BASE = 0x90000000`):**

| Offset | Access | Contents |
|--------|--------|----------|
| 0 | W | bit 0 = start (auto-clears next cycle) |
| 0 | R | bit 0 = done, bit 1 = sat |
| 1 | W | n_vars (4 bits) |
| 2 | W | n_clauses (5 bits) |
| 3 | R | model — bit *i* = value of variable *i+1* |
| 4 | R | cycles taken (20 bits, diagnostic) |
| 8 + c·10 + l | W | literal for clause *c*, slot *l*: bits[3:0] = var (0-based), bit 4 = negated, bit 5 = slot used |

Literal registers occupy words 8–207. Writing 0 to a literal register clears its
`used` bit (this is how stale clauses from a previous formula are erased).

### `firmware-tcp/sat_tcp.c`
Replaces `echo_tcp.c` logic. Same lwIP skeleton (NO_SYS=1 polling loop, timer0,
netif setup, TCP listen on port 1234), but the receive callback now:

1. Flattens the pbuf chain into a flat buffer
2. Parses the packet (see protocol below); rejects bad header / out-of-range sizes
3. Clears all 200 literal registers
4. Writes each literal as `(1<<5) | (neg<<4) | var0based`
5. Writes `n_vars`, `n_clauses`, then `start`
6. **Busy-polls the done bit** — safe because solving takes ≤ ~20 µs; no
   deferred-reply pattern needed (unlike the UDP ARP situation)
7. Builds and sends the response with `tcp_write()` + `tcp_output()`

### `host/sat_host.py`
TCP client. Opens a connection per formula (`TCP_NODELAY` set), sends the encoded
packet, decodes the reply, prints result + assignment + round-trip time.

- `python3 host/sat_host.py` — runs 4 built-in tests: 4-var SAT, trivial UNSAT
  (`x1 ∧ ¬x1`), pigeonhole PHP(3,2) UNSAT, 6-var SAT
- `python3 host/sat_host.py formula.cnf` — solves a DIMACS CNF file

---

## Modified Files

### `soc/build_soc_tcp.py`
| Before | After |
|--------|-------|
| `export_echo_slave()` → `echo_slave.v` | `export_sat_slave()` → `sat_slave.v` (yosys renames top to `sat_slave`) |
| `EchoSlaveWrapper` (Migen `Instance("echo_slave", ...)`) | `SATSlaveWrapper` (`Instance("sat_slave", ...)`) — identical port hookup |
| region `"echoslave"` @ 0x90000000 | region `"satslave"` @ 0x90000000 (generates `SATSLAVE_BASE` in `generated/mem.h`) |

Address, size (0x800), build flow, and build dir (`/tmp/ecp5-soc-build-tcp`) are unchanged.

### `firmware-tcp/Makefile`
- `APP_OBJS`: `echo_tcp.o` → `sat_tcp.o`
- Compile rule `echo_tcp.o: echo_tcp.c` → `sat_tcp.o: sat_tcp.c`
- `clean` also removes any leftover `echo_tcp.o`

`echo_tcp.c` itself is left in the tree untouched (just no longer compiled).

---

## Wire Protocol

### Host → FPGA (request)

| Byte(s) | Meaning |
|---------|---------|
| `0xAA` | start marker |
| 1 byte | n_vars (1–10) |
| 1 byte | n_clauses (1–20) |
| ... | literals: bit 7 = negated, bits 6–0 = variable number (**1-based**) |
| `0x00` | clause terminator (after each clause's literals) |
| `0xFF` | end of formula |

Example — `(x1 ∨ ¬x2) ∧ (x2)`:
`AA 02 02 01 82 00 02 00 FF`

### FPGA → Host (response)

| Result | Bytes |
|--------|-------|
| SAT | `0x01`, then one byte per variable (bit 7 = value, bits 6–0 = var number, 1-based), then `0xFF` |
| UNSAT | `0x00 0xFF` |

This is the same binary protocol used by `sat_dynamic.py` over UART in the
original fpga-sat-solver repo — only the transport changed (UART → TCP).

---

## Build & Run

> **Prerequisite:** `firmware-tcp/lwip/` must contain the lwIP source tree
> (git clone, not vendored — see README). Without it, the firmware compile
> fails with `fatal error: lwip/init.h: No such file or directory`.

```sh
conda activate litex-ecp5
cd soc && python build_soc_tcp.py
openFPGALoader -b ecpix5 /tmp/ecp5-soc-build-tcp/gateware/ecp5_ethernet_soc.bit
```

Network setup is identical to the echo SoC (see README, "Network Setup"):

```sh
sudo ifconfig en5 192.168.1.1 netmask 255.255.255.0
sudo arp -s 192.168.1.101 02:00:00:00:00:01
ping 192.168.1.101
```

Then:

```sh
python3 host/sat_host.py
```

Expected output: `4var_sat` and `6var_sat` report SAT with valid assignments;
`1var_unsat` and `php32_unsat` report UNSAT.

### LED codes (D6 = bit 0 … D9 = bit 3)

| State | LEDs |
|-------|------|
| `main()` reached | D6 |
| lwIP initialised | D6 + D7 |
| Init complete, listening (healthy idle = `0x0B`) | D6 + D7 + D9 |
| TCP data received | + D8 |
| Reply sent | + D9 |

D5 blinking at ~1.5 Hz throughout = SoC clock alive.

---

## Design Notes

- **Synchronous polling, not deferred reply.** The UDP echo firmware needed a
  deferred-reply pattern because `udp_arp_resolve()` re-enters the receive path.
  Here the solver finishes in ≤1024 cycles, so the receive callback simply
  busy-waits on the done bit — no lwIP calls happen while waiting.
- **One formula per packet.** The firmware assumes the full formula arrives in
  one TCP segment (true for any formula within the 10-var/20-clause limits —
  max packet is ~224 bytes, far under one MSS).
- **Memory map unchanged.** SATSlave reuses the EchoSlave region
  (0x90000000, 2 KB), so nothing else in the SoC moved.
