"""
measure_tcp.py -- TCP round-trip latency sweep for the ECP5 echo SoC.

Usage:
    python host/measure_tcp.py

Connects once to the FPGA TCP echo server and sweeps payload sizes from
8 to 1400 bytes, measuring round-trip time for each.  Saves a plot to
host/latency_tcp.png alongside the UDP plot for comparison.

Requirements:
    pip install matplotlib
"""

import os
import socket
import time
import statistics
import sys

try:
    import matplotlib.pyplot as plt
except ImportError:
    print("Install matplotlib first:  pip install matplotlib")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FPGA_IP   = "192.168.1.101"
FPGA_PORT = 1234
TIMEOUT   = 5.0    # seconds -- TCP needs more headroom than UDP
SAMPLES   = 20     # round-trips per payload size
WARMUP    = 3      # discard first N packets (TCP slow-start warmup)

SIZES = [8, 16, 32, 64, 128, 256, 512, 768, 1024, 1280, 1400]
# ---------------------------------------------------------------------------


def recv_exact(sock, n):
    """
    Receive exactly n bytes from sock.

    TCP is a byte stream -- a single recv() call may return less than n bytes
    even if the other side sent exactly n.  We loop until we have all of them.
    Returns the bytes, or raises socket.timeout if the deadline is hit.
    """
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed by FPGA")
        buf += chunk
    return buf


def measure_rtt(sock, payload_size, samples, warmup):
    """Send packets over the open TCP connection and return RTTs in microseconds."""
    pattern = bytes(range(256))
    payload = (pattern * (payload_size // 256 + 1))[:payload_size]
    rtts = []

    for i in range(samples + warmup):
        t0 = time.perf_counter()
        sock.sendall(payload)
        try:
            data = recv_exact(sock, payload_size)
            t1 = time.perf_counter()
        except socket.timeout:
            print(f"  timeout at size={payload_size} sample={i}")
            continue

        if data != payload:
            print(f"  PAYLOAD MISMATCH at size={payload_size} sample={i} "
                  f"(got {len(data)} bytes)")
            continue

        if i >= warmup:
            rtts.append((t1 - t0) * 1e6)

    return rtts


def main():
    print(f"Connecting to {FPGA_IP}:{FPGA_PORT} (TCP)...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)

    try:
        sock.connect((FPGA_IP, FPGA_PORT))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (socket.timeout, ConnectionRefusedError) as e:
        print(f"Could not connect: {e}")
        print("Check that the FPGA is running the TCP firmware and is reachable.")
        sys.exit(1)

    print("Connected.")
    print(f"{'Size (B)':>10}  {'Min (us)':>10}  {'Mean (us)':>10}  {'Max (us)':>10}  {'Stdev':>8}  {'Mbps':>8}")
    print("-" * 70)

    means   = []
    mins    = []
    maxs    = []
    stdevs  = []
    valid_sizes = []

    try:
        for size in SIZES:
            rtts = measure_rtt(sock, size, SAMPLES, WARMUP)
            if not rtts:
                print(f"{size:>10}  no replies")
                continue

            mn   = min(rtts)
            mx   = max(rtts)
            avg  = statistics.mean(rtts)
            sd   = statistics.stdev(rtts) if len(rtts) > 1 else 0.0
            mbps = (size * 8) / (avg * 1e-6) / 1e6

            print(f"{size:>10}  {mn:>10.1f}  {avg:>10.1f}  {mx:>10.1f}  {sd:>8.1f}  {mbps:>8.3f}")

            valid_sizes.append(size)
            means.append(avg)
            mins.append(mn)
            maxs.append(mx)
            stdevs.append(sd)
    finally:
        sock.close()

    if not valid_sizes:
        print("No replies received.  Check the FPGA firmware.")
        return

    # -----------------------------------------------------------------------
    # Plot
    # -----------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(valid_sizes, means,  "b-o", label="Mean RTT",  linewidth=2, markersize=6)
    ax.fill_between(valid_sizes,
                    [m - s for m, s in zip(means, stdevs)],
                    [m + s for m, s in zip(means, stdevs)],
                    alpha=0.2, color="blue", label="±1 stdev")
    ax.plot(valid_sizes, mins,   "g--", label="Min RTT",   linewidth=1)
    ax.plot(valid_sizes, maxs,   "r--", label="Max RTT",   linewidth=1)

    ax.set_xlabel("Payload size (bytes)", fontsize=13)
    ax.set_ylabel("Round-trip latency (µs)", fontsize=13)
    ax.set_title("ECP5 Ethernet Echo SoC -- TCP Round-Trip Latency\n"
                 f"(data travels: Mac → FPGA → EchoSlave BRAM → FPGA → Mac)",
                 fontsize=13)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.4)
    ax.set_xscale("log", base=2)
    ax.set_xticks(valid_sizes)
    ax.set_xticklabels([str(s) for s in valid_sizes], rotation=45)

    plt.tight_layout()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latency_tcp.png")
    plt.savefig(out, dpi=150)
    print(f"\nPlot saved to {out}")
    plt.show()


if __name__ == "__main__":
    main()
