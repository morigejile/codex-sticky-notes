"""Window chrome helpers for the desktop notes."""

import ctypes
from ctypes import wintypes
from functools import lru_cache


WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GWL_STYLE = -16
GWL_EXSTYLE = -20
GA_ROOT = 2
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_KEEP_BOUNDS = SWP_NOSIZE | SWP_NOMOVE
SWP_NOACTIVATE = 0x0010
SWP_KEEP_ORDER_AND_FOCUS = 0x0004 | SWP_NOACTIVATE
SWP_FRAMECHANGED = 0x0020
SWP_NOOWNERZORDER = 0x0200
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
DWMWA_NCRENDERING_POLICY = 2
DWMNCRP_DISABLED = 1
RGN_OR = 2
ULW_ALPHA = 2
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
DIB_RGB_COLORS = 0
RESIZE_CURSORS = {
    10: "size_we", 11: "size_we", 12: "size_ns", 13: "size_nw_se",
    14: "size_ne_sw", 15: "size_ns", 16: "size_ne_sw", 17: "size_nw_se",
}


class _BitmapInfo(ctypes.Structure):
    # BITMAPINFOHEADER followed by one RGBQUAD. 32-bit BI_RGB needs no palette.
    _fields_ = (
        ("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
        ("planes", wintypes.WORD), ("bits_per_pixel", wintypes.WORD),
        ("compression", wintypes.DWORD), ("image_size", wintypes.DWORD),
        ("x_pixels_per_meter", wintypes.LONG), ("y_pixels_per_meter", wintypes.LONG),
        ("colors_used", wintypes.DWORD), ("colors_important", wintypes.DWORD),
        ("color", wintypes.DWORD),
    )


class _BlendFunction(ctypes.Structure):
    _fields_ = (
        ("operation", wintypes.BYTE), ("flags", wintypes.BYTE),
        ("opacity", wintypes.BYTE), ("alpha_format", wintypes.BYTE),
    )

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowPos.argtypes = (
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
)
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.GetWindowRect.restype = wintypes.BOOL
user32.CreateWindowExW.argtypes = (
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
)
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.DestroyWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.ShowWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = (
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
    ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
    wintypes.DWORD, ctypes.POINTER(_BlendFunction), wintypes.DWORD,
)
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
user32.SetWindowRgn.restype = ctypes.c_int
gdi32.CreateRoundRectRgn.argtypes = (ctypes.c_int,) * 6
gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
gdi32.CreateRectRgn.restype = wintypes.HANDLE
gdi32.SetRectRgn.argtypes = (wintypes.HANDLE,) + (ctypes.c_int,) * 4
gdi32.SetRectRgn.restype = wintypes.BOOL
gdi32.CombineRgn.argtypes = (wintypes.HANDLE,) * 3 + (ctypes.c_int,)
gdi32.CombineRgn.restype = ctypes.c_int
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = (
    wintypes.HDC, ctypes.POINTER(_BitmapInfo), wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE, wintypes.DWORD,
)
gdi32.CreateDIBSection.restype = wintypes.HANDLE
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
gdi32.DeleteObject.restype = wintypes.BOOL

dwmapi.DwmSetWindowAttribute.argtypes = (
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
)
dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


def frame_handle(root):
    return user32.GetAncestor(root.winfo_id(), GA_ROOT)


def window_style(root):
    return user32.GetWindowLongW(frame_handle(root), GWL_STYLE)


def hide_window_frame(root):
    handle = frame_handle(root)
    policy = wintypes.DWORD(DWMNCRP_DISABLED)
    dwmapi.DwmSetWindowAttribute(handle, DWMWA_NCRENDERING_POLICY,
                                ctypes.byref(policy), ctypes.sizeof(policy))
    style = user32.GetWindowLongW(handle, GWL_STYLE)
    chrome = WS_CAPTION | WS_THICKFRAME
    if style & chrome:
        width, height = root.winfo_width(), root.winfo_height()
        user32.SetWindowLongW(handle, GWL_STYLE, style & ~chrome)
        flags = SWP_KEEP_ORDER_AND_FOCUS | SWP_FRAMECHANGED
        flags |= SWP_NOMOVE if min(width, height) > 1 else SWP_KEEP_BOUNDS
        user32.SetWindowPos(handle, None, 0, 0, width, height, flags)


def set_window_bounds(root, x, y, width, height):
    user32.SetWindowPos(frame_handle(root), None, x, y, width, height,
                        SWP_KEEP_ORDER_AND_FOCUS)


def round_scroll_bottom(canvas, width, height, inset, radius):
    radius = min(radius, (width - 2 * inset) // 2, height // 2)
    if radius <= 0:
        return
    diameter = 2 * radius
    clip = gdi32.CreateRoundRectRgn(inset, 0, width - inset, height, diameter, diameter)
    if not clip:
        return
    # Keep the top and the side gutters square above the rounded bottom.
    top = gdi32.CreateRectRgn(0, 0, width, height - radius)
    if top:
        combined = gdi32.CombineRgn(clip, clip, top, RGN_OR)
        gdi32.DeleteObject(top)
        if combined and user32.SetWindowRgn(canvas.winfo_id(), clip, True):
            return  # Windows owns the installed region.
    gdi32.DeleteObject(clip)


@lru_cache(maxsize=8)
def _corner_coverage(radius):
    """Coverage for the top-left quadrant, sampled on an 8×8 grid per edge pixel."""
    samples = tuple((index + 0.5) / 8 for index in range(8))
    radius_squared = radius * radius
    rows = []
    for y in range(radius, 0, -1):
        row = bytearray()
        for x in range(radius, 0, -1):
            if x * x + y * y <= radius_squared:
                row.append(255)
            elif (x - 1) ** 2 + (y - 1) ** 2 >= radius_squared:
                row.append(0)
            else:
                covered = sum((x - dx) ** 2 + (y - dy) ** 2 <= radius_squared
                              for dx in samples for dy in samples)
                row.append(round(255 * covered / 64))
        rows.append(bytes(row))
    return tuple(rows)


def _solid_region(bounds, coverage):
    left, top, right, bottom = bounds
    radius = len(coverage)
    region = gdi32.CreateRectRgn(left, top + radius, right, bottom - radius)
    if not region:
        return None
    strip = gdi32.CreateRectRgn(0, 0, 0, 0)
    if not strip:
        gdi32.DeleteObject(region)
        return None
    try:
        for y, row in enumerate(coverage):
            inset = row.find(b"\xff")
            if inset < 0:
                inset = radius
            if left + inset >= right - inset:
                continue
            for strip_top in (top + y, bottom - y - 1):
                if not (gdi32.SetRectRgn(strip, left + inset, strip_top, right - inset, strip_top + 1)
                        and gdi32.CombineRgn(region, region, strip, RGN_OR)):
                    gdi32.DeleteObject(region)
                    return None
        return region
    finally:
        gdi32.DeleteObject(strip)


def _install_region(handle, region):
    if region:
        if user32.SetWindowRgn(handle, region, True):
            return True  # Windows now owns the region.
        gdi32.DeleteObject(region)
    return False


def _paint_corner_overlay(handle, origin, size, coverage, colors, opacity):
    width, height = size
    # Every fully covered pixel is already painted by Tk. The overlay only
    # supplies fractional pixels, so the floating window's alpha applies once.
    pixels = bytearray(width * height * 4)
    for y, row in enumerate(coverage):
        for x, alpha in enumerate(row):
            if 0 < alpha < 255:
                for pixel_y, (red, green, blue) in zip((y, height - y - 1), colors):
                    bgra = bytes(((blue * alpha + 127) // 255,
                                  (green * alpha + 127) // 255,
                                  (red * alpha + 127) // 255, alpha))
                    for pixel_x in (x, width - x - 1):
                        offset = (pixel_y * width + pixel_x) * 4
                        pixels[offset:offset + 4] = bgra

    dc = gdi32.CreateCompatibleDC(None)
    if not dc:
        return False
    # Negative height makes the bitmap rows run from top to bottom.
    info = _BitmapInfo(_BitmapInfo.color.offset, width, -height, 1, 32)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(info), DIB_RGB_COLORS,
                                    ctypes.byref(bits), None, 0)
    previous = gdi32.SelectObject(dc, bitmap) if bitmap else None
    try:
        if not previous:
            return False
        ctypes.memmove(bits, (ctypes.c_ubyte * len(pixels)).from_buffer(pixels), len(pixels))
        return user32.UpdateLayeredWindow(
            handle, None, ctypes.byref(wintypes.POINT(*origin)),
            ctypes.byref(wintypes.SIZE(width, height)), dc, ctypes.byref(wintypes.POINT()), 0,
            ctypes.byref(_BlendFunction(AC_SRC_OVER, 0, opacity, AC_SRC_ALPHA)), ULW_ALPHA)
    finally:
        if previous:
            gdi32.SelectObject(dc, previous)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc)


class RoundedWindow:
    """Clip the Tk window and blend the four corner edges over the desktop."""

    def __init__(self, root, radius, *, resize_margin=(0, 0), corner_colors=None):
        self.root = root
        self.radius = radius
        self.resize_margin = resize_margin
        self.corner_colors = corner_colors
        self.shape = None
        self.pending = None
        self.child = None
        self.overlay = None
        self._overlay_owner = None
        self._overlay_origin = None
        self._overlay_content = None
        self._antialiased = False
        for event in ("<Map>", "<Configure>"):
            root.bind(event, self.schedule, add="+")
        if corner_colors is not None:
            root.bind("<Unmap>", self._on_unmap, add="+")
            root.bind("<Destroy>", self._on_destroy, add="+")

    def schedule(self, event):
        if event.widget is self.root:
            self.refresh()

    def refresh(self):
        if self.pending is None:
            self.pending = self.root.after_idle(self.apply)

    def apply(self):
        self.pending = None
        if not self.root.winfo_ismapped():
            return
        self.child = self.root.winfo_id()
        handle = frame_handle(self.root)
        client, frame = wintypes.RECT(), wintypes.RECT()
        if not (user32.GetWindowRect(self.child, ctypes.byref(client))
                and user32.GetWindowRect(handle, ctypes.byref(frame))):
            return
        bounds = (client.left - frame.left, client.top - frame.top,
                  client.right - frame.left, client.bottom - frame.top)
        width, height = client.right - client.left, client.bottom - client.top
        radius = min(self.radius, width // 2, height // 2)
        coverage = _corner_coverage(radius) if self.corner_colors is not None and radius > 0 else ()
        antialiased = bool(coverage) and self._update_overlay(handle, client, coverage)
        if self.shape != (handle, bounds) or self._antialiased != antialiased:
            antialiased = antialiased and _install_region(handle, _solid_region(bounds, coverage))
            if not antialiased:
                diameter = min(2 * self.radius, width, height)
                if not _install_region(handle, gdi32.CreateRoundRectRgn(*bounds, diameter, diameter)):
                    self._hide_overlay()
                    return
            self.shape = handle, bounds
            self._antialiased = antialiased
        if antialiased:
            self._show_overlay(handle)
        else:
            self._hide_overlay()

    def _update_overlay(self, owner, client, coverage):
        if owner != self._overlay_owner:
            self._destroy_overlay()
            style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            self.overlay = user32.CreateWindowExW(style, "Static", None, WS_POPUP,
                                                   0, 0, 0, 0, owner, None, None, None)
            if not self.overlay:
                return False
            self._overlay_owner = owner

        origin = (client.left, client.top)
        size = (client.right - client.left, client.bottom - client.top)
        colors = tuple(self.corner_colors())
        opacity = int(float(self.root.attributes("-alpha")) * 255 + 0.5)
        content = size, len(coverage), colors, opacity
        if self._overlay_content != content:
            rgb = [tuple(value >> 8 for value in self.root.winfo_rgb(color)) for color in colors]
            updated = _paint_corner_overlay(self.overlay, origin, size, coverage, rgb, opacity)
        elif self._overlay_origin != origin:
            updated = user32.SetWindowPos(self.overlay, None, *origin, 0, 0,
                                          SWP_KEEP_ORDER_AND_FOCUS | SWP_NOSIZE)
        else:
            return True
        if not updated:
            self._destroy_overlay()
            return False
        self._overlay_content = content
        self._overlay_origin = origin
        return True

    def _show_overlay(self, owner):
        topmost = user32.GetWindowLongW(owner, GWL_EXSTYLE) & WS_EX_TOPMOST
        # Tk changes the owner's topmost flag with SWP_NOOWNERZORDER.
        if topmost != user32.GetWindowLongW(self.overlay, GWL_EXSTYLE) & WS_EX_TOPMOST:
            order = HWND_TOPMOST if topmost else HWND_NOTOPMOST
            user32.SetWindowPos(self.overlay, order, 0, 0, 0, 0,
                                SWP_KEEP_BOUNDS | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
        if not user32.IsWindowVisible(self.overlay):
            user32.ShowWindow(self.overlay, SW_SHOWNOACTIVATE)

    def _hide_overlay(self):
        if self.overlay:
            user32.ShowWindow(self.overlay, SW_HIDE)

    def _destroy_overlay(self):
        if self.overlay:
            user32.DestroyWindow(self.overlay)
        self.overlay = self._overlay_owner = self._overlay_origin = self._overlay_content = None

    def _on_unmap(self, event):
        if event.widget is self.root:
            self._hide_overlay()

    def _on_destroy(self, event):
        if event.widget is self.root:
            if self.pending is not None:
                self.root.after_cancel(self.pending)
                self.pending = None
            self._destroy_overlay()

    def resize_hit(self, x, y):
        rect = wintypes.RECT()
        if self.child is None or not user32.GetWindowRect(self.child, ctypes.byref(rect)):
            return 0
        if not (rect.left <= x < rect.right and rect.top <= y < rect.bottom):
            return 0
        left, right = x - rect.left, rect.right - 1 - x
        top, bottom = y - rect.top, rect.bottom - 1 - y
        horizontal, vertical = self.resize_margin
        if top < vertical:
            return 13 if left < self.radius else 14 if right < self.radius else 12
        if bottom < vertical:
            return 16 if left < self.radius else 17 if right < self.radius else 15
        if left < horizontal:
            return 13 if top < self.radius else 16 if bottom < self.radius else 10
        if right < horizontal:
            return 14 if top < self.radius else 17 if bottom < self.radius else 11
        return 0
