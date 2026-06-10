# Makefile for the echo firmware
#
# Targets:
#   firmware_rom.bin  -- ROM firmware baked into the FPGA bitstream (default)
#   firmware.bin      -- SRAM firmware loaded via litex_term (legacy)
#   clean             -- remove build artefacts

BUILD_DIR    := /tmp/ecp5-soc-build
GENERATED    := $(BUILD_DIR)/software/include/generated

include $(GENERATED)/variables.mak

# SOC_DIRECTORY is set by variables.mak; derive the software tree from it.
LITEX_SWDIR  := $(SOC_DIRECTORY)/software

CC      := $(TRIPLE)-gcc
AS      := $(TRIPLE)-gcc
OBJCOPY := $(TRIPLE)-objcopy
SIZE    := $(TRIPLE)-size

# Common include paths and defines.
CFLAGS  := $(CPUFLAGS)
CFLAGS  += -Os -ffunction-sections -fdata-sections
CFLAGS  += -I$(BUILD_DIR)/software/include
CFLAGS  += -I$(LITEX_SWDIR)/include
CFLAGS  += -I$(LITEX_SWDIR)
CFLAGS  += -I$(CPU_DIRECTORY)
CFLAGS  += -I$(PICOLIBC_DIRECTORY)/libc/include
CFLAGS  += -I$(BUILD_DIR)/software/libc
CFLAGS  += -DETHMAC_SLOT_SIZE=2048 -DETHMAC_RX_SLOTS=2 -DETHMAC_TX_SLOTS=2

LIBS    := $(BUILD_DIR)/software/libliteeth/libliteeth.a \
           $(BUILD_DIR)/software/libbase/libbase.a \
           $(BUILD_DIR)/software/libcompiler_rt/libcompiler_rt.a \
           $(BUILD_DIR)/software/libc/libc.a

# ---------------------------------------------------------------------------
# ROM firmware: code lives at 0x00000000, runs directly from FPGA ROM.
# This is the primary target -- baked into the bitstream by build_soc.py.
# ---------------------------------------------------------------------------
# -nostdlib: suppress all toolchain default libraries (-lc, -lgloss, etc.).
# The LiteX-built picolibc (libc.a above) is linked explicitly instead.
ROM_LDFLAGS := -nostdlib -T rom.ld -Wl,--gc-sections

all: firmware_rom.bin

firmware_rom.bin: firmware_rom.elf
	$(OBJCOPY) -O binary $< $@
	$(SIZE) $<
	@echo "[ok] firmware_rom.bin ready"

firmware_rom.elf: echo.o crt0.o $(LIBS)
	$(CC) $(ROM_LDFLAGS) -o $@ $^

crt0.o: crt0.S
	$(AS) $(CFLAGS) -c -o $@ $<

echo.o: echo.c
	$(CC) $(CFLAGS) -c -o $@ $<

# ---------------------------------------------------------------------------
# SRAM firmware (legacy): loaded via litex_term --kernel.
# ---------------------------------------------------------------------------
SRAM_LDSCRIPT := $(GENERATED)/output_format.ld
SRAM_LDFLAGS  := -nostartfiles -T $(SRAM_LDSCRIPT)

firmware.bin: firmware.elf
	$(OBJCOPY) -O binary $< $@
	$(SIZE) $<

firmware.elf: echo_sram.o $(LIBS)
	$(CC) $(SRAM_LDFLAGS) -o $@ $^

echo_sram.o: echo.c
	$(CC) $(CFLAGS) -c -o $@ $<

# ---------------------------------------------------------------------------

clean:
	rm -f *.o *.elf *.bin

.PHONY: all clean
