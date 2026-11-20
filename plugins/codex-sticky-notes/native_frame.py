"""Window chrome helpers for the desktop notes."""

import ctypes
from ctypes import wintypes


WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
GWL_STYLE = -16
GA_ROOT = 2
SWP_KEEP_BOUNDS = 0x0001 | 0x0002
SWP_NOMOVE = 0x0002
SWP_KEEP_ORDER_AND_FOCUS = 0x0004 | 0x0010
SWP_FRAMECHANGED = 0x0020
DWMWA_NCRENDERING_POLICY = 2
DWMNCRP_DISABLED = 1
RGN_OR = 2

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
user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
user32.SetWindowRgn.restype = ctypes.c_int
user32.LoadCursorW.argtypes = (wintypes.HINSTANCE, ctypes.c_void_p)
user32.LoadCursorW.restype = wintypes.HANDLE
user32.SetCursor.argtypes = (wintypes.HANDLE,)
user32.SetCursor.restype = wintypes.HANDLE
gdi32.CreateRoundRectRgn.argtypes = (ctypes.c_int,) * 6
gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
gdi32.CreateRectRgn.restype = wintypes.HANDLE
gdi32.CombineRgn.argtypes = (wintypes.HANDLE,) * 3 + (ctypes.c_int,)
gdi32.CombineRgn.restype = ctypes.c_int
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


def set_resize_cursor(hit):
    cursor_id = {10: 32644, 11: 32644, 12: 32645, 13: 32642, 14: 32643,
                 15: 32645, 16: 32643, 17: 32642}.get(hit)
    if cursor_id:
        user32.SetCursor(user32.LoadCursorW(None, cursor_id))


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


class RoundedWindow:
    """Clip the real HWND to its rounded client area and keep edge resizing."""

    def __init__(self, root, radius, *, resize_margin=0):
        self.root = root
        self.radius = radius
        self.resize_margin = resize_margin
        self.shape = None
        self.pending = None
        self.child = None
        for event in ("<Map>", "<Configure>"):
            root.bind(event, self.schedule, add="+")

    def schedule(self, event):
        if event.widget is self.root and self.pending is None:
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
        if self.shape != (handle, bounds):
            diameter = min(2 * self.radius, client.right - client.left, client.bottom - client.top)
            region = gdi32.CreateRoundRectRgn(*bounds, diameter, diameter)
            if region:
                if user32.SetWindowRgn(handle, region, True):
                    self.shape = handle, bounds
                else:
                    gdi32.DeleteObject(region)

    def resize_hit(self, x, y):
        rect = wintypes.RECT()
        if self.child is None or not user32.GetWindowRect(self.child, ctypes.byref(rect)):
            return 0
        if not (rect.left <= x < rect.right and rect.top <= y < rect.bottom):
            return 0
        left, right = x - rect.left, rect.right - 1 - x
        top, bottom = y - rect.top, rect.bottom - 1 - y
        margin = self.resize_margin
        if top < margin:
            return 13 if left < self.radius else 14 if right < self.radius else 12
        if bottom < margin:
            return 16 if left < self.radius else 17 if right < self.radius else 15
        if left < margin:
            return 13 if top < self.radius else 16 if bottom < self.radius else 10
        if right < margin:
            return 14 if top < self.radius else 17 if bottom < self.radius else 11
        return 0
