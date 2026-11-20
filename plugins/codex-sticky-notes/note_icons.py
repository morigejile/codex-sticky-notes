"""Small antialiased icons rendered at the window's actual density."""

import base64
import math
import struct
import tkinter as tk
import zlib


def circle(radius):
    return lambda x, y: math.hypot(x - 10, y - 10) - radius


def stroke(points, radius):
    segments = [(x, y, nx - x, ny - y)
                for (x, y), (nx, ny) in zip(points, points[1:])]

    def distance(x, y):
        closest = math.inf
        for sx, sy, dx, dy in segments:
            fraction = ((x - sx) * dx + (y - sy) * dy) / (dx * dx + dy * dy)
            fraction = min(1, max(0, fraction))
            closest = min(closest, math.hypot(x - sx - fraction * dx, y - sy - fraction * dy))
        return closest - radius

    return distance


def combined(*shapes):
    return lambda x, y: min(shape(x, y) for shape in shapes)


_CONTROL_CIRCLE = circle(7.5)
_TICK = stroke(((6.3, 10.2), (8.8, 12.7), (13.6, 7.7)), 0.94)
_SHAPES = {
    "dot": circle(6.7),
    "circle": _CONTROL_CIRCLE,
    "ring": lambda x, y: abs(_CONTROL_CIRCLE(x, y)) - 0.9,
    "close": combined(
        stroke(((6.3, 6.3), (13.7, 13.7)), 0.95),
        stroke(((13.7, 6.3), (6.3, 13.7)), 0.95),
    ),
    "folder": stroke(((2.7, 5.8), (3.9, 4.6), (7.2, 4.6), (9.4, 6.8),
                      (16.1, 6.8), (17.5, 8.2), (17.5, 15.8), (16.4, 17.0),
                      (3.8, 17.0), (2.7, 15.8), (2.7, 5.8)), 0.82),
    "note": combined(
        stroke(((5.6, 3.0), (11.9, 3.0), (15.7, 6.8), (15.7, 15.4),
                (14.5, 16.6), (5.6, 16.6), (4.4, 15.4), (4.4, 4.2), (5.6, 3.0)), 0.72),
        stroke(((11.9, 3.0), (11.9, 6.8), (15.7, 6.8)), 0.66),
        stroke(((7.3, 9.9), (12.5, 9.9)), 0.66),
        stroke(((7.3, 12.7), (10.7, 12.7)), 0.66),
    ),
}


def rgb(color):
    return tuple(bytes.fromhex(color.removeprefix("#")))


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def render_png(name, size, ink, checkmark=None):
    layers = [(_SHAPES[name], rgb(ink))]
    if checkmark:
        layers.append((_TICK, rgb(checkmark)))
    pixels = bytearray()
    step = 20 / size
    for row in range(size):
        pixels.append(0)  # PNG scanline uses the None filter.
        for column in range(size):
            x, y = (column + 0.5) * step, (row + 0.5) * step
            alpha = 0.0
            color = (0.0, 0.0, 0.0)
            for shape, layer_color in layers:
                coverage = min(1.0, max(0.0, 0.5 - shape(x, y) / step))
                color = tuple(new * coverage + old * (1 - coverage)
                              for new, old in zip(layer_color, color))
                alpha = coverage + alpha * (1 - coverage)
            pixels.extend(round(channel / alpha) if alpha else 0 for channel in color)
            pixels.append(round(alpha * 255))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
            + png_chunk(b"IDAT", zlib.compress(pixels)) + png_chunk(b"IEND", b""))


def icon(widget, name, size, ink, *, checkmark=None):
    owner = widget.winfo_toplevel()
    if not hasattr(owner, "notes_icons"):
        owner.notes_icons = {}
    cache = owner.notes_icons
    key = name, size, ink, checkmark
    if key not in cache:
        png = render_png(name, size, ink, checkmark)
        cache[key] = tk.PhotoImage(master=owner, data=base64.b64encode(png), format="png")
    return cache[key]
