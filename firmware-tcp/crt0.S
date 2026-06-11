/*
 * crt0.S -- minimal RISC-V startup for direct ROM execution.
 *
 * The CPU resets to address 0x00000000 (ROM base). This code:
 *   1. Disables interrupts and sets a trap handler.
 *   2. Sets the stack pointer to the top of SRAM.
 *   3. Copies .data from ROM to SRAM.
 *   4. Zeroes .bss in SRAM.
 *   5. Calls main().
 */

.global _start
.section ".text.start"

_start:
    /* Disable machine-mode interrupts. */
    csrw    mie, zero

    /* Point trap vector at a safe infinite loop. */
    la      t0, _trap_handler
    csrw    mtvec, t0

    /* Stack grows down from the top of SRAM (0x10000000 + 0x4000). */
    li      sp, 0x10004000

    /* Copy .data section from ROM load address to SRAM run address. */
    la      a0, _fdata_rom
    la      a1, _fdata
    la      a2, _edata
1:  beq     a1, a2, 2f
    lw      t0, 0(a0)
    sw      t0, 0(a1)
    addi    a0, a0, 4
    addi    a1, a1, 4
    j       1b
2:
    /* Zero .bss. */
    la      a0, _fbss
    la      a1, _ebss
3:  beq     a0, a1, 4f
    sw      zero, 0(a0)
    addi    a0, a0, 4
    j       3b
4:
    call    main

    /* main() should never return, but loop if it does. */
5:  j       5b

_trap_handler:
    j       _trap_handler
