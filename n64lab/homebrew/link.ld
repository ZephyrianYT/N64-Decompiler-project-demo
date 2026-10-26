/* Lay the program out where IPL3 will load it: the ROM's entry point. */
ENTRY(_start)

SECTIONS
{
    . = 0x80000400;
    .text : { *(.text.start) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) *(.sdata .sdata.*) }
    . = ALIGN(8);
    __bss_start = .;
    .bss (NOLOAD) : { *(.bss .bss.*) *(.sbss .sbss.*) *(COMMON) }
    . = ALIGN(8);
    __bss_end = .;
    __stack_top = 0x803FFFF0;

    /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.comment) *(.pdr) *(.mdebug*) *(.gnu.attributes) }
}
