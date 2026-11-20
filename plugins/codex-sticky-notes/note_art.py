"""Load the decorative note artwork at the window's pixel size."""

import ctypes
import tkinter as tk
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path

from note_icons import png_image


NOTE_ASSETS = Path(__file__).with_name("assets")
PIXEL_FORMAT_ARGB = 0x26200A  # GDI+ PixelFormat32bppARGB (straight alpha).
SOURCE_COPY = 1
HIGH_QUALITY_BICUBIC = 7
PIXEL_OFFSET_HALF = 4
UNIT_PIXEL = 2


class _StartupInput(ctypes.Structure):
    _fields_ = [
        ("version", wintypes.UINT),
        ("debug_callback", ctypes.c_void_p),
        ("suppress_background_thread", wintypes.BOOL),
        ("suppress_external_codecs", wintypes.BOOL),
    ]


def _check(status):
    if status:
        raise OSError(f"GDI+ image operation returned status {status}")


def _encode_png(bgra, width, height):
    # The GDI+ buffer stores byte channels in BGRA order. Tk's PNG loader
    # keeps partial alpha, so the same pixels work over different backgrounds.
    rgba = bytearray(bgra)
    rgba[0::4] = bgra[2::4]
    rgba[2::4] = bgra[0::4]
    stride = width * 4
    rows = b"".join(b"\x00" + rgba[start:start + stride] for start in range(0, len(rgba), stride))
    return png_image(width, height, rows)


@lru_cache(maxsize=8)
def _resized_png(path, width):
    gdiplus = ctypes.WinDLL("gdiplus")
    startup = _StartupInput(version=1, suppress_external_codecs=True)
    token = ctypes.c_size_t()
    source, resized, graphics = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    _check(gdiplus.GdiplusStartup(ctypes.byref(token), ctypes.byref(startup), None))
    try:
        _check(gdiplus.GdipCreateBitmapFromFile(ctypes.c_wchar_p(str(path)), ctypes.byref(source)))
        source_width, source_height = wintypes.UINT(), wintypes.UINT()
        _check(gdiplus.GdipGetImageWidth(source, ctypes.byref(source_width)))
        _check(gdiplus.GdipGetImageHeight(source, ctypes.byref(source_height)))
        height = max(1, round(source_height.value * width / source_width.value))
        stride = width * 4
        pixels = ctypes.create_string_buffer(stride * height)
        _check(gdiplus.GdipCreateBitmapFromScan0(
            width, height, stride, PIXEL_FORMAT_ARGB, pixels, ctypes.byref(resized)))
        _check(gdiplus.GdipGetImageGraphicsContext(resized, ctypes.byref(graphics)))
        try:
            _check(gdiplus.GdipSetCompositingMode(graphics, SOURCE_COPY))
            _check(gdiplus.GdipSetInterpolationMode(graphics, HIGH_QUALITY_BICUBIC))
            _check(gdiplus.GdipSetPixelOffsetMode(graphics, PIXEL_OFFSET_HALF))
            _check(gdiplus.GdipDrawImageRectRectI(
                graphics, source, 0, 0, width, height, 0, 0, source_width.value,
                source_height.value, UNIT_PIXEL, None, None, None))
        finally:
            gdiplus.GdipDeleteGraphics(graphics)
        return _encode_png(pixels.raw, width, height)
    finally:
        if resized:
            gdiplus.GdipDisposeImage(resized)
        if source:
            gdiplus.GdipDisposeImage(source)
        gdiplus.GdiplusShutdown(token)


def load_note_art(widget, size):
    for name in ("orange-notes-pinned.png", "orange-notes.png"):
        try:
            png = _resized_png(NOTE_ASSETS / name, size)
            return tk.PhotoImage(master=widget, data=png, format="png")
        except (OSError, tk.TclError):
            continue
    return None
