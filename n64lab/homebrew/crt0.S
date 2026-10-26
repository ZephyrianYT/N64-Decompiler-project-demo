# crt0.S - the first code that runs.  IPL3 copies the first 1 MiB of the
# ROM to 0x80000400 and jumps here.  We set up a stack, zero .bss, call
# main(), and then stop with BREAK (which n64lab's runtime treats as "done").

    .set noreorder
    .section .text.start, "ax"
    .global _start
_start:
    lui     $sp, %hi(__stack_top)
    addiu   $sp, $sp, %lo(__stack_top)
    lui     $t0, %hi(__bss_start)
    addiu   $t0, $t0, %lo(__bss_start)
    lui     $t1, %hi(__bss_end)
    addiu   $t1, $t1, %lo(__bss_end)
1:  beq     $t0, $t1, 2f
    nop
    sw      $zero, 0($t0)
    b       1b
    addiu   $t0, $t0, 4
2:  jal     main
    nop
    break   0
3:  b       3b
    nop
