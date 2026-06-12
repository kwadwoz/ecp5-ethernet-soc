"""
sat_host.py -- TCP SAT solver client for the ECP5 SAT accelerator.

Sends CNF formulas to the FPGA over TCP and prints the result.

Usage:
    python sat_host.py              # run built-in test cases
    python sat_host.py formula.cnf  # solve a DIMACS CNF file

Protocol (host -> FPGA):
    0xAA          start marker
    N             number of variables (1 byte)
    M             number of clauses   (1 byte)
    [literals]    one byte each: bit7=neg, bits6-0=var number (1-based)
    0x00          clause terminator  (after each clause)
    0xFF          end marker

Protocol (FPGA -> host):
    0x01 + assignments + 0xFF   (SAT)
    0x00 + 0xFF                 (UNSAT)
"""

import socket
import sys
import time

FPGA_IP   = "192.168.1.101"
FPGA_PORT = 1234
TIMEOUT   = 5.0

PROTO_START  = 0xAA
PROTO_END    = 0xFF
PROTO_TERM   = 0x00
RESP_SAT     = 0x01
RESP_UNSAT   = 0x00


def encode_packet(n_vars, clauses):
    """Encode a CNF formula (list of lists of signed ints) into binary format."""
    pkt = bytearray([PROTO_START, n_vars & 0xFF, len(clauses) & 0xFF])
    for clause in clauses:
        for lit in clause:
            # bit7=1 if negated, bits6-0 = variable number (1-based)
            if lit > 0:
                pkt.append(lit & 0x7F)
            else:
                pkt.append((-lit & 0x7F) | 0x80)
        pkt.append(PROTO_TERM)
    pkt.append(PROTO_END)
    return bytes(pkt)


def decode_response(data, n_vars):
    """Decode the FPGA response bytes into a result dict."""
    if not data:
        return {"result": "TIMEOUT"}
    if data[0] == RESP_UNSAT:
        return {"result": "UNSAT"}
    if data[0] == RESP_SAT:
        assignment = {}
        for b in data[1:]:
            if b == PROTO_END:
                break
            assignment[f"x{b & 0x7F}"] = bool((b >> 7) & 1)
        return {"result": "SAT", "assignment": assignment}
    return {"result": "ERROR", "raw": data.hex()}


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def solve(n_vars, clauses, label=""):
    """Send a formula to the FPGA, return the decoded result, and print it."""
    packet = encode_packet(n_vars, clauses)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(TIMEOUT)

    t0 = time.perf_counter()
    try:
        sock.connect((FPGA_IP, FPGA_PORT))
        sock.sendall(packet)

        # Read result byte first to determine SAT vs UNSAT
        first = _recv_exact(sock, 1)
        if not first:
            result = {"result": "TIMEOUT"}
        elif first[0] == RESP_UNSAT:
            _recv_exact(sock, 1)  # consume 0xFF
            result = decode_response(first + bytes([PROTO_END]), n_vars)
        elif first[0] == RESP_SAT:
            rest = _recv_exact(sock, n_vars + 1)  # assignments + 0xFF
            result = decode_response(first + rest, n_vars)
        else:
            result = {"result": "ERROR", "raw": first.hex()}
    except socket.timeout:
        result = {"result": "TIMEOUT"}
    finally:
        sock.close()

    elapsed_us = (time.perf_counter() - t0) * 1e6

    tag = f"[{label}] " if label else ""
    print(f"{tag}n_vars={n_vars}, n_clauses={len(clauses)}  ({elapsed_us:.0f} µs RTT)")
    print(f"  Result: {result['result']}")
    if result.get("assignment"):
        asgn = result["assignment"]
        # Print assignment sorted by variable number
        print("  Assignment:", " ".join(
            f"x{k[1:]}={'T' if v else 'F'}" for k, v in sorted(asgn.items(), key=lambda x: int(x[0][1:]))
        ))
    print()

    return result


def _parse_dimacs(path):
    """Parse a DIMACS CNF file. Returns (n_vars, clauses)."""
    n_vars = 0
    clauses = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p cnf"):
                parts = line.split()
                n_vars = int(parts[2])
                continue
            lits = list(map(int, line.split()))
            if lits and lits[-1] == 0:
                lits = lits[:-1]
            if lits:
                clauses.append(lits)
    return n_vars, clauses


def main():
    if len(sys.argv) > 1:
        n_vars, clauses = _parse_dimacs(sys.argv[1])
        solve(n_vars, clauses, label=sys.argv[1])
        return

    # Built-in test cases
    # 4-variable satisfiable formula: x1 V x2, ~x1 V x3, ~x2 V ~x3, x1 V ~x2 V x4
    solve(4, [[1, 2], [-1, 3], [-2, -3], [1, -2, 4]], label="4var_sat")

    # Trivially unsatisfiable: x1 AND ~x1
    solve(1, [[1], [-1]], label="1var_unsat")

    # Pigeonhole PHP(3,2): 3 pigeons into 2 holes -- always UNSAT
    solve(6,
          [[1, 2], [3, 4], [5, 6],          # each pigeon in some hole
           [-1, -3], [-1, -5], [-3, -5],    # at most one pigeon per hole 0
           [-2, -4], [-2, -6], [-4, -6],    # at most one pigeon per hole 1
           [-1, -2], [-3, -4], [-5, -6]],   # each pigeon in at most one hole
          label="php32_unsat")

    # 6-variable satisfiable formula
    solve(6, [[1, 2, 3], [-1, 4], [-2, 5], [-3, 6], [-4, -5], [-5, -6]], label="6var_sat")


if __name__ == "__main__":
    main()
