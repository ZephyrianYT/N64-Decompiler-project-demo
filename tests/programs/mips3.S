# Hand-written tests for things C compilers for the N64 rarely emit, but
# real games contain: 64-bit (MIPS III) instructions, branch-likely, delay
# slots that change the branch condition, branches into delay slots,
# unaligned access, and division by zero.  Expected output:
# tests/programs/expected/mips3.txt

    .set noreorder
    .set noat
    .set mips3

    .data
    .align 2
bytes:
    .byte 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88

    .text
    .global mips3_tests
# void mips3_tests(unsigned int* out)
mips3_tests:
    addiu   $sp, $sp, -32
    sw      $ra, 28($sp)
    move    $t9, $a0

    # 1. 64-bit shifts
    lui     $t0, 0x1234
    ori     $t0, $t0, 0x5678
    dsll32  $t1, $t0, 0
    ori     $t1, $t1, 0x9ABC
    dsrl32  $t2, $t1, 0
    sw      $t2, 0($t9)
    sw      $t1, 4($t9)
    dsll    $t3, $t1, 4
    dsrl32  $t4, $t3, 0
    sw      $t4, 8($t9)
    sw      $t3, 12($t9)
    daddiu  $t5, $zero, -1
    dsrl    $t5, $t5, 4
    dsra32  $t6, $t5, 0
    sw      $t6, 16($t9)
    daddiu  $t7, $zero, -16
    dsra    $t7, $t7, 2
    dsrl32  $t8, $t7, 0
    sw      $t8, 20($t9)
    sw      $t7, 24($t9)

    # 2. 64-bit multiply and divide
    daddiu  $t0, $zero, -1
    daddiu  $t1, $zero, 2
    dmultu  $t0, $t1
    mfhi    $t2
    mflo    $t3
    sw      $t2, 28($t9)
    sw      $t3, 32($t9)
    dmult   $t0, $t1
    mfhi    $t2
    sw      $t2, 36($t9)
    dsll32  $t0, $t1, 0
    daddiu  $t0, $t0, 7
    daddiu  $t1, $zero, 3
    ddivu   $zero, $t0, $t1
    mflo    $t2
    mfhi    $t3
    sw      $t2, 40($t9)
    sw      $t3, 44($t9)

    # 3. 64-bit loads and stores
    sd      $t0, 8($sp)
    lw      $t4, 8($sp)
    lw      $t5, 12($sp)
    sll     $t4, $t4, 4
    addu    $t4, $t4, $t5
    sw      $t4, 48($t9)
    ld      $t6, 8($sp)
    dsrl32  $t6, $t6, 0
    sw      $t6, 52($t9)

    # 4. branch-likely: the delay slot only runs when the branch is taken
    addiu   $t0, $zero, 5
    addiu   $t1, $zero, 0
    beql    $t0, $zero, 1f
    addiu   $t1, $t1, 100
1:  bnel    $t0, $zero, 2f
    addiu   $t1, $t1, 1
    addiu   $t1, $t1, 1000
2:  sw      $t1, 56($t9)

    # 5. the delay slot overwrites the register the branch tests
    addiu   $t0, $zero, 1
    addiu   $t1, $zero, 0
    bnez    $t0, 3f
    move    $t0, $zero
    addiu   $t1, $t1, 50
3:  addiu   $t1, $t1, 7
    sll     $t0, $t0, 4
    addu    $t1, $t1, $t0
    sw      $t1, 60($t9)

    # 6. a branch target that is also another branch's delay slot
    addiu   $t0, $zero, 0
    addiu   $t1, $zero, 0
    b       6f
    nop
5:  bnez    $t1, 7f
6:  addiu   $t0, $t0, 10
    addiu   $t1, $zero, 1
    b       5b
    nop
7:  sw      $t0, 64($t9)

    # 7. unaligned access with lwl/lwr and swl/swr
    lui     $t0, %hi(bytes)
    addiu   $t0, $t0, %lo(bytes)
    lwl     $t1, 1($t0)
    lwr     $t1, 4($t0)
    sw      $t1, 68($t9)
    sw      $zero, 16($sp)
    sw      $zero, 20($sp)
    lui     $t3, 0xAABB
    ori     $t3, $t3, 0xCCDD
    swl     $t3, 17($sp)
    swr     $t3, 20($sp)
    lw      $t4, 16($sp)
    lw      $t5, 20($sp)
    sw      $t4, 72($t9)
    sw      $t5, 76($t9)

    # 8. calls through a register (jalr) and branch-and-link (bal)
    lui     $t0, %hi(helper_double)
    addiu   $t0, $t0, %lo(helper_double)
    addiu   $a0, $zero, 21
    jalr    $t0
    nop
    sw      $v0, 80($t9)
    addiu   $a0, $zero, 5
    bal     helper_double
    addiu   $a0, $a0, 1
    sw      $v0, 84($t9)

    # 9. division by zero gives defined results; signed/unsigned multiply
    addiu   $t0, $zero, 77
    div     $zero, $t0, $zero
    mflo    $t1
    mfhi    $t2
    sw      $t1, 88($t9)
    sw      $t2, 92($t9)
    addiu   $t0, $zero, -77
    div     $zero, $t0, $zero
    mflo    $t1
    sw      $t1, 96($t9)
    addiu   $t0, $zero, -3
    lui     $t1, 0x4000
    mult    $t0, $t1
    mfhi    $t2
    mflo    $t3
    sw      $t2, 100($t9)
    sw      $t3, 104($t9)
    multu   $t0, $t1
    mfhi    $t2
    sw      $t2, 108($t9)

    # 10. FPU compare + branch on the condition flag
    lui     $t0, 0x3FC0           # 1.5f
    mtc1    $t0, $f0
    lui     $t1, 0x4020           # 2.5f
    mtc1    $t1, $f2
    addiu   $t2, $zero, 0
    c.lt.s  $f0, $f2
    nop
    bc1t    8f
    addiu   $t2, $t2, 1
    addiu   $t2, $t2, 100
8:  c.lt.s  $f2, $f0
    nop
    bc1tl   9f
    addiu   $t2, $t2, 10
    addiu   $t2, $t2, 1000
9:  sw      $t2, 112($t9)
    add.s   $f4, $f0, $f2
    mfc1    $t3, $f4
    sw      $t3, 116($t9)
    cvt.d.s $f6, $f4
    mfc1    $t4, $f7
    sw      $t4, 120($t9)
    cvt.w.s $f8, $f2
    mfc1    $t5, $f8
    sw      $t5, 124($t9)

    # 11. a conditional branch straight into another function (a conditional tail call)
    jal     cond_tail
    addiu   $a0, $zero, 5          # taken: helper_double(5) = 10
    sw      $v0, 128($t9)
    jal     cond_tail
    addiu   $a0, $zero, 0          # not taken: falls through and returns 99
    sw      $v0, 132($t9)

    lw      $ra, 28($sp)
    jr      $ra
    addiu   $sp, $sp, 32

helper_double:
    jr      $ra
    sll     $v0, $a0, 1

# int cond_tail(int x) { return x ? helper_double(x) : 99; } with a branch, not a call
cond_tail:
    bnez    $a0, helper_double
    nop
    jr      $ra
    addiu   $v0, $zero, 99
