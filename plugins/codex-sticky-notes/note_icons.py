"""Small antialiased icons rendered at the window's actual density."""

import base64
import math
import struct
import tkinter as tk
import zlib


def circle(radius):
    return lambda x, y: math.hypot(x - 10, y - 10) - radius


def stroke(points, radius):
    segments = []
    for (x, y), (nx, ny) in zip(points, points[1:]):
        dx, dy = nx - x, ny - y
        length_squared = dx * dx + dy * dy
        if length_squared:
            segments.append((x, y, dx, dy, length_squared))

    def distance(x, y):
        closest = math.inf
        for sx, sy, dx, dy, length_squared in segments:
            fraction = ((x - sx) * dx + (y - sy) * dy) / length_squared
            fraction = min(1, max(0, fraction))
            closest = min(closest, math.hypot(x - sx - fraction * dx, y - sy - fraction * dy))
        return closest - radius

    return distance


def combined(*shapes):
    return lambda x, y: min(shape(x, y) for shape in shapes)


def rounded_outline(vertices, radius):
    points = []
    for index, (x, y) in enumerate(vertices):
        px, py = vertices[index - 1]
        nx, ny = vertices[(index + 1) % len(vertices)]
        inbound = min(0.5, radius / math.hypot(px - x, py - y))
        outbound = min(0.5, radius / math.hypot(nx - x, ny - y))
        start_x, start_y = x + (px - x) * inbound, y + (py - y) * inbound
        end_x, end_y = x + (nx - x) * outbound, y + (ny - y) * outbound
        for step in range(6):
            t = step / 5
            u = 1 - t
            points.append((u * u * start_x + 2 * u * t * x + t * t * end_x,
                           u * u * start_y + 2 * u * t * y + t * t * end_y))
    return points + [points[0]]


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
    "refresh": combined(
        stroke(((3.2, 9.3), (3.9, 6.6), (6.2, 4.2), (9.5, 3.1), (13.0, 3.8),
                (15.7, 6.2), (16.6, 7.6)), 0.72),
        stroke(((16.7, 3.7), (16.7, 7.9), (12.5, 7.9)), 0.72),
        stroke(((16.8, 10.7), (16.1, 13.4), (13.8, 15.8), (10.5, 16.9), (7.0, 16.2),
                (4.3, 13.8), (3.4, 12.4)), 0.72),
        stroke(((3.3, 16.3), (3.3, 12.1), (7.5, 12.1)), 0.72),
    ),
    "folder": stroke(rounded_outline(((2.7, 4.6), (7.25, 4.6), (9.8, 6.9),
                                      (17.5, 6.9), (17.5, 17.0), (2.7, 17.0)), 2.4), 0.78),
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


def png_image(width, height, pixels):
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
            + png_chunk(b"IDAT", zlib.compress(pixels)) + png_chunk(b"IEND", b""))


def render_png(name, size, ink, checkmark=None, *, text_gap=0):
    layers = [(_SHAPES[name], rgb(ink))]
    if checkmark:
        layers.append((_TICK, rgb(checkmark)))
    pixels = bytearray()
    step = 20 / size
    spacing = bytes(text_gap * 4)
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
        pixels.extend(spacing)
    return png_image(size + text_gap, size, pixels)


def icon(widget, name, size, ink, *, checkmark=None, text_gap=0):
    owner = widget.winfo_toplevel()
    if not hasattr(owner, "notes_icons"):
        owner.notes_icons = {}
    cache = owner.notes_icons
    key = name, size, ink, checkmark, text_gap
    if key not in cache:
        png = render_png(name, size, ink, checkmark, text_gap=text_gap)
        cache[key] = tk.PhotoImage(master=owner, data=base64.b64encode(png), format="png")
    return cache[key]


def rounded_surface_image(widget, width, height, radius, fill, border):
    radius = min(radius, width // 2, height // 2)
    fill_rgb, border_rgb = rgb(fill), rgb(border)
    fill_pixel, border_pixel = bytes((*fill_rgb, 255)), bytes((*border_rgb, 255))
    rows = []
    for row in range(radius):
        corner = []
        for column in range(radius):
            distance = math.hypot(radius - column - 0.5, radius - row - 0.5) - radius
            alpha = min(1.0, max(0.0, 0.5 - distance))
            inside = min(1.0, max(0.0, -0.5 - distance))
            color = (round(edge + (face - edge) * inside)
                     for edge, face in zip(border_rgb, fill_rgb))
            corner.append(bytes((*color, round(alpha * 255))))
        center = (border_pixel if row == 0 else fill_pixel) * (width - 2 * radius)
        rows.append(b"\0" + b"".join(corner) + center + b"".join(reversed(corner)))
    middle = b"\0" + border_pixel + fill_pixel * (width - 2) + border_pixel
    pixels = b"".join(rows) + middle * (height - 2 * radius) + b"".join(reversed(rows))
    return tk.PhotoImage(master=widget, data=base64.b64encode(png_image(width, height, pixels)),
                         format="png")
