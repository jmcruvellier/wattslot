"""Icône et logo de l'extension Home Assistant (lots 6t.3 et 7.1).

Motif « Créneau » de WattSlot (choisi le 18/10/2026, comme le favicon
``app/frontend/public/favicon.svg``) : les pistes du Planning des équipements, un créneau doré mis
en avant et un éclair. ``icon.png`` (128 x 128) : le carré du favicon ; ``logo.png`` (250 x 100) :
le même motif en long. Couleurs du thème Ivoire (``app/frontend/src/theme/themes.css``), fond
sombre lisible sur les thèmes clair et sombre de HA. Dessin vectoriel simple, sans dépendance
(pas de Pillow) : suréchantillonnage 4 x 4 puis moyenne, PNG écrit avec ``zlib``.

Depuis ``dev/`` : ``python -m tools.addon_images``.
"""

import struct
import zlib
from collections.abc import Callable
from pathlib import Path

TILE = (0x17, 0x19, 0x1C)  # fond sombre du favicon
TRACK = (0x3A, 0x3D, 0x43)  # pistes du Planning des équipements
GOLD = (0xF2, 0xC2, 0x6B)  # créneau mis en avant (--accent du thème Graphite)
SAMPLES = 4  # par côté de pixel
ADDON = Path(__file__).resolve().parents[2] / "ha-addon" / "wattslot"

Shape = Callable[[float, float], bool]
Layer = tuple[Shape, tuple[int, int, int]]


def rounded_rect(x: float, y: float, w: float, h: float, r: float) -> Shape:
    """Rectangle aux coins arrondis de rayon ``r``."""

    def inside(px: float, py: float) -> bool:
        if not (x <= px <= x + w and y <= py <= y + h):
            return False
        cx = min(max(px, x + r), x + w - r)
        cy = min(max(py, y + r), y + h - r)
        return (px - cx) ** 2 + (py - cy) ** 2 <= r * r

    return inside


def polygon(points: list[tuple[float, float]]) -> Shape:
    """Polygone (règle pair-impair)."""

    def inside(px: float, py: float) -> bool:
        found = False
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True):
            if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                found = not found
        return found

    return inside


def bolt(x: float, y: float, scale: float) -> Shape:
    """Éclair du favicon (``M36 27.5l-5 6h3.5l-1.5 3.5 5-6h-3.5z``), placé en ``x``, ``y``."""
    path = [(36, 27.5), (31, 33.5), (34.5, 33.5), (33, 37), (38, 31), (34.5, 31)]
    return polygon([(x + (px - 31) * scale, y + (py - 27.5) * scale) for px, py in path])


def render(width: int, height: int, layers: list[Layer]) -> bytes:
    """Pixels RGBA, ligne par ligne (dernier calque au-dessus)."""
    rows = bytearray()
    step = 1 / SAMPLES
    for py in range(height):
        rows.append(0)  # filtre PNG : aucun
        for px in range(width):
            totals = [0.0, 0.0, 0.0]
            covered = 0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    x, y = px + (sx + 0.5) * step, py + (sy + 0.5) * step
                    for shape, color in reversed(layers):
                        if shape(x, y):
                            for i in range(3):
                                totals[i] += color[i]
                            covered += 1
                            break
            if covered:
                rows += bytes(round(t / covered) for t in totals)
                rows.append(round(255 * covered / SAMPLES**2))
            else:
                rows += b"\0\0\0\0"
    return bytes(rows)


def png(width: int, height: int, rows: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # RGBA 8 bits
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def icon() -> list[Layer]:
    """Le favicon (64 x 64) à l'échelle 2."""
    k = 2.0
    return [
        (rounded_rect(0, 0, 64 * k, 64 * k, 14 * k), TILE),
        *((rounded_rect(12 * k, y * k, 40 * k, 6 * k, 3 * k), TRACK) for y in (16, 29, 42)),
        (rounded_rect(26 * k, 26 * k, 18 * k, 12 * k, 4 * k), GOLD),
        (bolt(31 * k, 27.5 * k, k), TILE),
    ]


def logo() -> list[Layer]:
    """Le même motif en long : trois pistes, le créneau doré sur celle du milieu."""
    k = 3.0  # échelle de l'éclair
    return [
        (rounded_rect(0, 0, 250, 100, 22), TILE),
        *((rounded_rect(22, y, 206, 12, 6), TRACK) for y in (19, 44, 69)),
        (rounded_rect(104, 32, 64, 36, 10), GOLD),
        (bolt(136 - 3.5 * k, 50 - 4.75 * k, k), TILE),
    ]


def main() -> None:
    for name, (width, height), layers in (
        ("icon.png", (128, 128), icon()),
        ("logo.png", (250, 100), logo()),
    ):
        (ADDON / name).write_bytes(png(width, height, render(width, height, layers)))
        print(f"{name} : {width} x {height}")


if __name__ == "__main__":
    main()
