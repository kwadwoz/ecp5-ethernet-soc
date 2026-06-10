"""
measure.py -- UDP round-trip latency sweep for the ECP5 echo SoC.

Usage:
    python measure.py

The script sends UDP packets of increasing payload sizes to the FPGA echo
server, measures round-trip time for each, and plots latency vs payload size.

Requirements:
    pip install matplotlib
"""

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
FPGA_IP      = "192.168.1.101"
FPGA_PORT    = 1234
SRC_PORT     = 5000
TIMEOUT      = 2.0        # seconds to wait for each reply
SAMPLES      = 20         # round-trips measured per payload size
WARMUP       = 3          # discard first N packets (ARP + pipeline warmup)

# Payload sizes to sweep (bytes).
SIZES = [8, 16, 32, 64, 128, 256, 512, 768, 1024, 1280, 1400]
# ---------------------------------------------------------------------------


def measure_rtt(sock, payload_size, samples, warmup):
    """Send packets and return list of RTT measurements in microseconds."""
    payload = bytes(range(payload_size % 256)) * (payload_size // 256 + 1)
    payload = payload[:payload_size]
    rtts = []

    for i in range(samples + warmup):
        t0 = time.perf_counter()
        sock.sendto(payload, (FPGA_IP, FPGA_PORT))
        try:
            data, addr = sock.recvfrom(4096)
            t1 = time.perf_counter()
        except socket.timeout:
            print(f"  timeout at size={payload_size} sample={i}")
            continue

        if data != payload:
            print(f"  PAYLOAD MISMATCH at size={payload_size} sample={i} "
                  f"(got {len(data)} bytes from {addr})")
            continue

        if i >= warmup:
            rtts.append((t1 - t0) * 1e6)  # convert to microseconds

    return rtts


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", SRC_PORT))
    sock.settimeout(TIMEOUT)

    print(f"Sending to {FPGA_IP}:{FPGA_PORT}")
    print(f"{'Size (B)':>10}  {'Min (us)':>10}  {'Mean (us)':>10}  {'Max (us)':>10}  {'Stdev':>8}  {'Mbps':>8}")
    print("-" * 70)

    means   = []
    mins    = []
    maxs    = []
    stdevs  = []
    valid_sizes = []

    for size in SIZES:
        rtts = measure_rtt(sock, size, SAMPLES, WARMUP)
        if not rtts:
            print(f"{size:>10}  no replies")
            continue

        mn   = min(rtts)
        mx   = max(rtts)
        avg  = statistics.mean(rtts)
        sd   = statistics.stdev(rtts) if len(rtts) > 1 else 0.0
        # One-way effective throughput: payload crosses the link twice per RTT.
        mbps = (size * 8) / (avg * 1e-6) / 1e6

        print(f"{size:>10}  {mn:>10.1f}  {avg:>10.1f}  {mx:>10.1f}  {sd:>8.1f}  {mbps:>8.3f}")

        valid_sizes.append(size)
        means.append(avg)
        mins.append(mn)
        maxs.append(mx)
        stdevs.append(sd)

    sock.close()

    if not valid_sizes:
        print("No replies received. Check wiring and IP address.")
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
    ax.set_title("ECP5 Ethernet Echo SoC -- UDP Round-Trip Latency\n"
                 f"(data travels: Mac → FPGA → EchoSlave BRAM → FPGA → Mac)",
                 fontsize=13)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.4)
    ax.set_xscale("log", base=2)
    ax.set_xticks(valid_sizes)
    ax.set_xticklabels([str(s) for s in valid_sizes], rotation=45)

    plt.tight_layout()
    out = "latency.png"
    plt.savefig(out, dpi=150)
    print(f"\nPlot saved to {out}")
    plt.show()


if __name__ == "__main__":
    main()
