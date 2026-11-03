"""Dessine l'icône de LANa (PNG 1024 px) sans dépendance : le logo du panneau, en grand, sur un carré arrondi."""
import struct
import sys
import zlib

SIZE, SS = 1024, 3                       # sur-échantillonnage pour lisser les bords arrondis
BG = (0x7C, 0x4D, 0xFF)                  # --acc du thème LANa
A2, OK = (0xD9, 0xCC, 0xFF), (0x4F, 0xF0, 0xA6)
INSET, RADIUS = 100, 185                 # gabarit des icônes macOS : carré de 824 px, coins de 185 px
# Le logo du panneau : grille 8×8 (voir web/index.html, .brand), avec les pavés pleins et les barres à 55 %.
CELLS = [(1, 1, 3, 3, A2, 1.0), (4, 4, 3, 3, OK, 1.0), (4, 1, 3, 1, A2, 0.55), (1, 5, 3, 1, A2, 0.55)]


def inside_rounded(x, y):
    lo, hi = INSET, SIZE - INSET
    if not (lo <= x < hi and lo <= y < hi):
        return False
    cx = min(max(x, lo + RADIUS), hi - RADIUS)
    cy = min(max(y, lo + RADIUS), hi - RADIUS)
    return (x - cx) ** 2 + (y - cy) ** 2 <= RADIUS ** 2


def color_at(x, y):
    unit = (SIZE - 2 * INSET) / 8.0
    gx, gy = (x - INSET) / unit, (y - INSET) / unit
    for cx, cy, w, h, col, alpha in CELLS:
        if cx <= gx < cx + w and cy <= gy < cy + h:
            return tuple(round(c * alpha + b * (1 - alpha)) for c, b in zip(col, BG))
    return BG


def main(path):
    rows = []
    for y in range(SIZE):
        row = bytearray(b"\x00")
        for x in range(SIZE):
            hits, acc = 0, [0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    px, py = x + (sx + 0.5) / SS, y + (sy + 0.5) / SS
                    if inside_rounded(px, py):
                        hits += 1
                        c = color_at(px, py)
                        acc = [a + v for a, v in zip(acc, c)]
            if hits:
                row += bytes(round(a / hits) for a in acc) + bytes([round(255 * hits / SS ** 2)])
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
                 + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


if __name__ == "__main__":
    main(sys.argv[1])
