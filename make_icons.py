#!/usr/bin/env python3
"""Write the Home Screen icons (a white check mark on green) with the stdlib only."""
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BG = (31, 111, 92)
FG = (255, 255, 255)


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def icon(n):
    # check mark polyline in unit coordinates, stroke width as a fraction of n
    pts = [(0.27, 0.53), (0.43, 0.68), (0.74, 0.35)]
    w = 0.085 * n
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            px, py = x + 0.5, y + 0.5
            d = min(seg_dist(px, py, pts[i][0] * n, pts[i][1] * n, pts[i + 1][0] * n, pts[i + 1][1] * n)
                    for i in range(len(pts) - 1))
            a = max(0.0, min(1.0, w / 2 - d + 0.5))  # 1px anti-aliased edge
            row += bytes(round(BG[c] * (1 - a) + FG[c] * a) for c in range(3))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


if __name__ == "__main__":
    for n in (180, 192, 512):
        (ROOT / f"icon-{n}.png").write_bytes(icon(n))
