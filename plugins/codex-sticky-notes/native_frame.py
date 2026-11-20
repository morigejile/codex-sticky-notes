"""Keep the Windows resize frame while moving caption actions into the demo."""

import ctypes
from ctypes import wintypes


WS_CAPTION = 0x00C00000
GWL_STYLE = -16
GA_ROOT = 2
SWP_KEEP_BOUNDS = 0x0001 | 0x0002
SWP_KEEP_ORDER_AND_FOCUS = 0x0004 | 0x0010
SWP_FRAMECHANGED = 0x0020
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2

user32 = ctypes.WinDLL("user32", use_last_error=True)
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
user32.ReleaseCapture.argtypes = ()
user32.ReleaseCapture.restype = wintypes.BOOL
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostMessageW.restype = wintypes.BOOL


def frame_handle(root):
    return user32.GetAncestor(root.winfo_id(), GA_ROOT)


def window_style(root):
    return user32.GetWindowLongW(frame_handle(root), GWL_STYLE)


def hide_caption(root):
    handle = frame_handle(root)
    style = user32.GetWindowLongW(handle, GWL_STYLE)
    if style & WS_CAPTION:
        user32.SetWindowLongW(handle, GWL_STYLE, style & ~WS_CAPTION)
        flags = SWP_KEEP_BOUNDS | SWP_KEEP_ORDER_AND_FOCUS | SWP_FRAMECHANGED
        user32.SetWindowPos(handle, None, 0, 0, 0, 0, flags)


def start_window_move(root, screen_x, screen_y):
    coords = (screen_x & 0xffff) | ((screen_y & 0xffff) << 16)
    user32.ReleaseCapture()
    user32.PostMessageW(frame_handle(root), WM_NCLBUTTONDOWN, HTCAPTION, coords)
