/*
 * rom.ld -- linker script for firmware baked directly into FPGA ROM.
 *
 * Code and read-only data live in ROM at 0x00000000.
 * Writable data and BSS live in SRAM at 0x10000000.
 * crt0 copies .data from ROM to SRAM at startup.
 */

OUTPUT_FORMAT("elf32-littleriscv", "elf32-littleriscv", "elf32-littleriscv")
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
    rom (rx)  : ORIGIN = 0x00000000, LENGTH = 0x10000
    ram (rwx) : ORIGIN = 0x10000000, LENGTH = 0x4000
}

SECTIONS
{
    .text : {
        _ftext = .;
        KEEP(*(.text.start))
        *(.text .text.*)
        *(.gnu.linkonce.t.*)
        . = ALIGN(4);
    } > rom

    .rodata : {
        *(.rodata .rodata.*)
        *(.srodata .srodata.*)
        *(.gnu.linkonce.r.*)
        . = ALIGN(4);
        _etext = .;
    } > rom

    /* Store address in ROM where .data load copy begins. */
    _fdata_rom = .;

    .data : AT(_fdata_rom) {
        . = ALIGN(4);
        _fdata = .;
        *(.data .data.*)
        *(.gnu.linkonce.d.*)
        . = ALIGN(4);
        _edata = .;
    } > ram

    .bss : {
        . = ALIGN(4);
        _fbss = .;
        *(.bss .bss.*)
        *(.gnu.linkonce.b.*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > ram

    /DISCARD/ : {
        *(.comment)
        *(.eh_frame .eh_frame*)
    }
}
