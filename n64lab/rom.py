"""ROM loading: byte order, header parsing, boot chip (CIC) detection, checksums.

An N64 cartridge image starts with a 0x40-byte header, followed by the IPL3
boot code (0x40..0x1000), followed by the game itself.  The console's boot
ROM runs IPL3, which copies the first 1 MiB of game code (ROM 0x1000..0x101000)
into RDRAM at the header's entry point and jumps to it.  That 1 MiB is the
"boot segment" this tool recompiles by default.
"""

import struct
import zlib
from dataclasses import dataclass

# ROM dumps come in three byte orders.  The first word of every N64 ROM is
# 0x80371240 when read in the console's native big-endian order.
MAGIC_Z64 = bytes.fromhex("80371240")  # big-endian (native)
MAGIC_V64 = bytes.fromhex("37804012")  # 16-bit byte-swapped (Doctor V64)
MAGIC_N64 = bytes.fromhex("40123780")  # 32-bit little-endian

HEADER_SIZE = 0x40
GAME_START = 0x1000
CHECKSUM_LENGTH = 0x100000

# CRC32 of the IPL3 boot code identifies which CIC lockout chip the cartridge
# was built for.  The CIC matters because two of them make IPL3 load the game
# at a different address than the header says, and each uses its own
# checksum seed.
CIC_BY_IPL3_CRC = {
    0x6170A4A1: "6101",
    0x90BB6CB5: "6102",
    0x0B050EE0: "6103",
    0x98BC2C86: "6105",
    0xACC8580A: "6106",
    0x009E9EA3: "7102",
    0x0E018159: "8303",
}

CIC_CHECKSUM_SEED = {
    "6101": 0xF8CA4DDC,
    "6102": 0xF8CA4DDC,
    "7102": 0xF8CA4DDC,
    "6103": 0xA3886759,
    "6105": 0xDF26F436,
    "6106": 0x1FEA617A,
}

# IPL3 for these chips subtracts an offset from the header's entry point.
CIC_ENTRY_ADJUST = {"6103": 0x100000, "6106": 0x200000}


class RomError(Exception):
    pass


def detect_format(data):
    magic = bytes(data[:4])
    if magic == MAGIC_Z64:
        return "z64"
    if magic == MAGIC_V64:
        return "v64"
    if magic == MAGIC_N64:
        return "n64"
    raise RomError("not an N64 ROM (unknown magic %s)" % magic.hex())


def to_big_endian(data):
    """Return the ROM in native (.z64) byte order."""
    fmt = detect_format(data)
    if fmt == "z64":
        return bytes(data)
    if len(data) % 4:  # a trimmed dump: pad to whole words so the swaps line up
        data = bytes(data) + bytes(4 - len(data) % 4)
    out = bytearray(data)
    if fmt == "v64":
        out[0::2], out[1::2] = data[1::2], data[0::2]
    else:
        n = len(out) & ~3
        for i in range(4):
            out[i:n:4] = data[3 - i:n:4]
    return bytes(out)


def _rol(value, amount):
    amount &= 31
    return ((value << amount) | (value >> (32 - amount))) & 0xFFFFFFFF


def compute_checksum(rom, cic):
    """Compute the two header CRC words the way IPL3 checks them."""
    if len(rom) < GAME_START + CHECKSUM_LENGTH:
        raise RomError("ROM too small to checksum (needs at least 1 MiB + 4 KiB)")
    seed = CIC_CHECKSUM_SEED.get(cic, CIC_CHECKSUM_SEED["6102"])
    t1 = t2 = t3 = t4 = t5 = t6 = seed
    words = struct.unpack_from(">%dI" % (CHECKSUM_LENGTH // 4), rom, GAME_START)
    for i, d in enumerate(words):
        if (t6 + d) & 0xFFFFFFFF < t6:
            t4 = (t4 + 1) & 0xFFFFFFFF
        t6 = (t6 + d) & 0xFFFFFFFF
        t3 ^= d
        r = _rol(d, d & 0x1F)
        t5 = (t5 + r) & 0xFFFFFFFF
        if t2 > d:
            t2 ^= r
        else:
            t2 ^= t6 ^ d
        if cic == "6105":
            offset = 0x0750 + ((i * 4) & 0xFF)
            t1 = (t1 + (struct.unpack_from(">I", rom, offset)[0] ^ d)) & 0xFFFFFFFF
        else:
            t1 = (t1 + (t5 ^ d)) & 0xFFFFFFFF
    if cic == "6103":
        return ((t6 ^ t4) + t3) & 0xFFFFFFFF, ((t5 ^ t2) + t1) & 0xFFFFFFFF
    if cic == "6106":
        return ((t6 * t4) + t3) & 0xFFFFFFFF, ((t5 * t2) + t1) & 0xFFFFFFFF
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


@dataclass
class Rom:
    data: bytes          # always big-endian
    source_format: str   # byte order of the file on disk
    title: str
    game_code: str       # e.g. "NSME" = N(cart) SM(Super Mario) E(USA)
    version: int
    header_entry: int    # entry point as written in the header
    entry: int           # entry point after the CIC adjustment
    header_crc: tuple
    cic: str             # "6102" etc., or "unknown"

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            raw = f.read()
        return cls.from_bytes(raw)

    @classmethod
    def from_bytes(cls, raw):
        if len(raw) < GAME_START:
            raise RomError("file is too small to be an N64 ROM")
        fmt = detect_format(raw)
        data = to_big_endian(raw)
        header_entry, crc1, crc2 = struct.unpack_from(">I4xII", data, 0x08)
        title = data[0x20:0x34].decode("ascii", "replace").rstrip(" \0")
        game_code = data[0x3B:0x3F].decode("ascii", "replace")
        version = data[0x3F]
        ipl3_crc = zlib.crc32(data[HEADER_SIZE:GAME_START]) & 0xFFFFFFFF
        cic = CIC_BY_IPL3_CRC.get(ipl3_crc, "unknown")
        entry = (header_entry - CIC_ENTRY_ADJUST.get(cic, 0)) & 0xFFFFFFFF
        return cls(data, fmt, title, game_code, version, header_entry, entry,
                   (crc1, crc2), cic)

    def checksum_ok(self):
        try:
            return compute_checksum(self.data, self.cic) == self.header_crc
        except RomError:
            return False

    def read_u32(self, offset):
        return struct.unpack_from(">I", self.data, offset)[0]

    def describe(self):
        regions = {"E": "USA", "J": "Japan", "P": "Europe", "D": "Germany",
                   "F": "France", "U": "Australia", "I": "Italy", "S": "Spain"}
        region = regions.get(self.game_code[3:4], "?")
        lines = [
            "Title        : %s" % (self.title or "(blank)"),
            "Game code    : %s (region: %s, revision %d)" % (self.game_code, region, self.version),
            "File format  : .%s%s" % (self.source_format,
                                      "" if self.source_format == "z64" else " (converted to big-endian)"),
            "Size         : %d bytes (%.1f MiB)" % (len(self.data), len(self.data) / 1048576),
            "CIC chip     : %s" % self.cic,
            "Header entry : 0x%08X" % self.header_entry,
        ]
        if self.entry != self.header_entry:
            lines.append("Real entry   : 0x%08X (CIC-%s loads 0x%X lower)"
                         % (self.entry, self.cic, self.header_entry - self.entry))
        lines.append("Checksum     : %08X %08X (%s)" % (
            self.header_crc[0], self.header_crc[1],
            "OK" if self.checksum_ok() else "MISMATCH"))
        return "\n".join(lines)
