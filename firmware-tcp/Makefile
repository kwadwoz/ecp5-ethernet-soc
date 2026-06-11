# Makefile for the TCP echo firmware (lwIP-based)
#
# Targets:
#   firmware_rom.bin  -- ROM firmware baked into the FPGA bitstream (default)
#   clean             -- remove build artefacts

BUILD_DIR    := /tmp/ecp5-soc-build-tcp
GENERATED    := $(BUILD_DIR)/software/include/generated

include $(GENERATED)/variables.mak

LITEX_SWDIR  := $(SOC_DIRECTORY)/software

CC      := $(TRIPLE)-gcc
AS      := $(TRIPLE)-gcc
OBJCOPY := $(TRIPLE)-objcopy
SIZE    := $(TRIPLE)-size

LWIP_SRC := lwip/src

# ---------------------------------------------------------------------------
# Include paths
#
# The order matters: our arch/ and firmware-tcp/ directories come first so
# that our lwipopts.h, arch/cc.h, and arch/sys_arch.h shadow any defaults
# that might be in the lwIP tree.
# ---------------------------------------------------------------------------
CFLAGS  := $(CPUFLAGS)
CFLAGS  += -Os -ffunction-sections -fdata-sections
CFLAGS  += -I$(BUILD_DIR)/software/include      # generated/csr.h, generated/mem.h
CFLAGS  += -I$(LITEX_SWDIR)/include             # libbase headers, system.h
CFLAGS  += -I$(LITEX_SWDIR)                     # libliteeth (only for inet.h macros)
CFLAGS  += -I$(CPU_DIRECTORY)
CFLAGS  += -I$(PICOLIBC_DIRECTORY)/libc/include
CFLAGS  += -I$(BUILD_DIR)/software/libc
CFLAGS  += -I.                                  # lwipopts.h lives here
CFLAGS  += -Iarch                               # cc.h, sys_arch.h
CFLAGS  += -I$(LWIP_SRC)/include                # all lwIP public headers
CFLAGS  += -DETHMAC_SLOT_SIZE=2048 -DETHMAC_RX_SLOTS=2 -DETHMAC_TX_SLOTS=2

# ---------------------------------------------------------------------------
# lwIP source files
#
# We compile only the modules we use.  The full list of what each file
# provides is next to each entry.
# ---------------------------------------------------------------------------
LWIP_CORE_OBJS := \
    $(LWIP_SRC)/core/def.o          \
    $(LWIP_SRC)/core/inet_chksum.o  \
    $(LWIP_SRC)/core/init.o         \
    $(LWIP_SRC)/core/ip.o           \
    $(LWIP_SRC)/core/mem.o          \
    $(LWIP_SRC)/core/memp.o         \
    $(LWIP_SRC)/core/netif.o        \
    $(LWIP_SRC)/core/pbuf.o         \
    $(LWIP_SRC)/core/sys.o          \
    $(LWIP_SRC)/core/tcp.o          \
    $(LWIP_SRC)/core/tcp_in.o       \
    $(LWIP_SRC)/core/tcp_out.o      \
    $(LWIP_SRC)/core/timeouts.o     \
    $(LWIP_SRC)/core/ipv4/etharp.o  \
    $(LWIP_SRC)/core/ipv4/icmp.o    \
    $(LWIP_SRC)/core/ipv4/ip4.o     \
    $(LWIP_SRC)/core/ipv4/ip4_addr.o \
    $(LWIP_SRC)/core/ipv4/ip4_frag.o \
    $(LWIP_SRC)/netif/ethernet.o

APP_OBJS := sat_tcp.o ethernetif.o sys_arch.o crt0.o

ALL_OBJS := $(APP_OBJS) $(LWIP_CORE_OBJS)

# ---------------------------------------------------------------------------
# Libraries -- note: libliteeth.a is intentionally excluded.
# We are not using libliteeth at all; lwIP replaces it entirely.
# ---------------------------------------------------------------------------
LIBS := \
    $(BUILD_DIR)/software/libbase/libbase.a \
    $(BUILD_DIR)/software/libcompiler_rt/libcompiler_rt.a \
    $(BUILD_DIR)/software/libc/libc.a

ROM_LDFLAGS := -nostdlib -T rom.ld -Wl,--gc-sections

# ---------------------------------------------------------------------------
all: firmware_rom.bin

firmware_rom.bin: firmware_rom.elf
	$(OBJCOPY) -O binary $< $@
	$(SIZE) $<
	@echo "[ok] firmware_rom.bin ready"

firmware_rom.elf: $(ALL_OBJS) $(LIBS)
	$(CC) $(ROM_LDFLAGS) -o $@ $(ALL_OBJS) \
	    -Wl,--start-group $(LIBS) -Wl,--end-group

crt0.o: crt0.S
	$(AS) $(CFLAGS) -c -o $@ $<

sat_tcp.o: sat_tcp.c
	$(CC) $(CFLAGS) -c -o $@ $<

ethernetif.o: ethernetif.c
	$(CC) $(CFLAGS) -c -o $@ $<

sys_arch.o: sys_arch.c
	$(CC) $(CFLAGS) -c -o $@ $<

# Pattern rule for all lwIP source files.
$(LWIP_SRC)/%.o: $(LWIP_SRC)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

# ---------------------------------------------------------------------------
clean:
	rm -f *.o *.elf *.bin $(LWIP_CORE_OBJS)
	@# Remove any leftover echo_tcp.o from previous builds
	rm -f echo_tcp.o

.PHONY: all clean
