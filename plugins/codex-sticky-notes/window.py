"""Single-page Codex sticky notes."""

import argparse
import ctypes
import sqlite3
import sys
import time
import tkinter as tk
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import PurePosixPath, PureWindowsPath
from tkinter import messagebox, simpledialog, ttk
from tkinter import font as tkfont

from appearance import (
    PillButton, ProjectCard, RoundedSurface, SessionCard, capsule_switch, label, note_mark, paint_hills,
    paint_smooth_rect, rounded_indicator, rounded_rect, text_button, two_line_text, ui_font, wrap,
)
from data import TaskStore, group_threads, project_path_module, read_project_threads
from launch import open_thread_link
from note_art import load_note_art
from note_icons import icon
from palette import ORANGE, ORANGE_MAIN, PROJECT_COLOR_DEMOS, SAGE, palette_for

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
if WINDOWS:
    from lifecycle import Event, Instance
    from native_frame import (
        RoundedWindow, hide_window_frame, round_scroll_bottom, set_resize_cursor, set_window_bounds,
    )
else:
    from mac_lifecycle import Event, Instance


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


def work_area(widget):
    if not WINDOWS:
        return 0, 24, widget.winfo_screenwidth(), widget.winfo_screenheight() - 48
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    monitor = user32.MonitorFromWindow(widget.winfo_id(), 2)  # Nearest monitor.
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return info.work.left, info.work.top, info.work.right, info.work.bottom
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def screen_box(widget):
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def within(widget, parent):
    while widget is not None:
        if widget is parent:
            return True
        widget = widget.master
    return False


def distinguishing_folder(path, others):
    path_module = project_path_module(path)
    path_type = PureWindowsPath if path_module.sep == "\\" else PurePosixPath
    parts = path_type(path).parts
    peers = [path_type(path_module.normcase(other)).parts
             for other in others if other != path]
    normalized = path_type(path_module.normcase(path)).parts
    for length in range(1, len(parts) + 1):
        if all(peer[-length:] != normalized[-length:] for peer in peers):
            return str(path_type(*parts[-length:]))
    return path


def popup_background(widget, fallback):
    if WINDOWS:
        transparent = "#ff00fe"
        widget.attributes("-transparentcolor", transparent)
        return transparent
    if MACOS:
        widget.attributes("-transparent", True)
        return "systemTransparent"
    return fallback


def layout_tiles(cards, width, scale, *, gap, target, maximum, column_limit, height=None):
    if width < 2:
        return
    gap = round(gap * scale)
    target = round(target * scale)
    columns = max(1, min(column_limit, (width + gap) // (target + gap)))
    side = min(round(maximum * scale), (width - gap * (columns - 1)) // columns)
    for index, card in enumerate(cards):
        row, column = divmod(index, columns)
        card.configure(width=side, height=side if height is None else height)
        card.grid(row=row, column=column, padx=(0, gap if column < columns - 1 else 0),
                  pady=(0, gap))


class FloatingNote(tk.Toplevel):
    def __init__(self, root, restore):
        super().__init__(root)
        self.notes_palette = self.palette = palette_for(root)
        self.restore = restore
        self.press = None
        self.dragged = False
        self.alert_timer = None
        self.pin_highlight = False
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.67)
        self.title("打开 Codex 便签")
        self.native_corners = WINDOWS and self.palette.precise_corners
        outside = (self.palette.floating if self.native_corners
                   else popup_background(self, self.palette.floating))
        self.configure(bg=outside)

        self.scale = self.winfo_fpixels("1i") / 96
        self.size = round(54 * self.scale)
        self.tooltip = None
        self.face = tk.Canvas(self, width=self.size, height=self.size, bg=outside,
                              highlightthickness=0, cursor="hand2", takefocus=True)
        self.face.pack()
        if self.native_corners:
            self.rounded_window = RoundedWindow(
                self, round(18 * self.scale), corner_colors=lambda: (self.face["bg"],) * 2)
        self.art = load_note_art(self.face, round(self.size * 0.85)) if self.palette.precise_corners else None
        self.face.bind("<Enter>", lambda _: self.set_hover(True))
        self.face.bind("<Leave>", lambda _: self.set_hover(False))
        self.face.bind("<ButtonPress-1>", self.begin_drag)
        self.face.bind("<B1-Motion>", self.drag)
        self.face.bind("<ButtonRelease-1>", self.end_drag)
        self.face.bind("<Return>", lambda _: restore())
        self.face.bind("<space>", lambda _: restore())
        self.set_hover(False)

    def set_hover(self, hovered):
        self.attributes("-alpha", 0.97 if hovered else 0.67)
        canvas = self.face
        size = self.size
        canvas.delete("all")
        fill = self.palette.action if hovered else self.palette.floating
        if self.native_corners:
            canvas.configure(bg=fill)
            self.rounded_window.refresh()
        else:
            rounded_rect(canvas, 2, 2, size - 2, size - 2, size * 0.30, fill=fill,
                         outline=self.palette.hero_border if hovered else fill, width=1)
        if self.art is not None:
            canvas.create_image(size / 2, size / 2, image=self.art)
        elif self.palette.precise_corners:
            mark = icon(canvas, "note", round(size * 0.68), self.palette.ink)
            canvas.create_image(size / 2, size / 2, image=mark)
        else:
            note_mark(canvas, 0, 0, size / 58, "#fffaf5")
        # The pin in the orange artwork sits near the upper-right of the image.
        x, y = size * 0.73, size * 0.26
        if self.art is not None:
            x = size / 2 + self.art.width() * 0.24
            y = size / 2 - self.art.height() * 0.32
        highlight = icon(canvas, "dot", round(13 * self.scale), "#62a4ff")
        canvas.create_image(round(x), round(y), image=highlight, tags=("unread-indicator",))
        self.highlight_pin(self.pin_highlight)
        if (self.palette.precise_corners and hovered and self.press is None
                and self.winfo_viewable()):
            self.show_tooltip()
        elif self.tooltip is not None:
            self.tooltip.withdraw()

    def highlight_pin(self, visible):
        self.pin_highlight = visible
        self.face.itemconfigure("unread-indicator", state="normal" if visible else "hidden")

    def flash_pin(self):
        self.highlight_pin(not self.pin_highlight)
        self.alert_timer = self.after(500, self.flash_pin)

    def set_unread_alert(self, enabled):
        if enabled and self.alert_timer is None:
            self.flash_pin()
        elif not enabled and self.alert_timer is not None:
            self.after_cancel(self.alert_timer)
            self.alert_timer = None
            self.highlight_pin(False)

    def destroy(self):
        self.set_unread_alert(False)
        super().destroy()

    def show_tooltip(self):
        if self.tooltip is None:
            self.tooltip = tk.Toplevel(self)
            self.tooltip.withdraw()
            self.tooltip.notes_palette = self.palette
            self.tooltip.overrideredirect(True)
            self.tooltip.attributes("-topmost", True)
            outside = popup_background(self.tooltip, self.palette.card)
            self.tooltip.configure(bg=outside)
            shell = RoundedSurface(self.tooltip, outside=outside,
                                   radius=round(15 * self.scale))
            shell.pack(fill="both", expand=True)
            label(shell, "打开便签", size=10, weight="bold", bg=self.palette.card).pack(
                padx=round(12 * self.scale), pady=round(6 * self.scale))
            self.tooltip.update_idletasks()
        width, height = self.tooltip.winfo_reqwidth(), self.tooltip.winfo_reqheight()
        left, top, right, bottom = work_area(self)
        x0, y0, x1, y1 = screen_box(self)
        gap = round(8 * self.scale)
        x = x0 - gap - width if x0 - gap - width >= left else x1 + gap
        x = min(max(left, x), right - width)
        y = min(max(top, (y0 + y1 - height) // 2), bottom - height)
        self.tooltip.geometry(f"{width}x{height}+{x}+{y}")
        self.tooltip.deiconify()
        self.tooltip.lift()

    def show(self, x, y):
        self.geometry(f"{self.size}x{self.size}+{x}+{y}")
        self.set_hover(False)
        self.deiconify()
        self.lift()
        self.keep_on_screen()

    def begin_drag(self, event):
        self.press = event.x_root, event.y_root, self.winfo_rootx(), self.winfo_rooty()
        self.dragged = False
        if self.tooltip is not None:
            self.tooltip.withdraw()

    def drag(self, event):
        if self.press is None:
            return
        start_x, start_y, x, y = self.press
        dx, dy = event.x_root - start_x, event.y_root - start_y
        if self.dragged or max(abs(dx), abs(dy)) >= round(4 * self.scale):
            self.dragged = True
            self.geometry(f"+{x + dx}+{y + dy}")

    def end_drag(self, event):
        if self.press is None:
            return
        self.press = None
        if self.dragged:
            self.keep_on_screen()
            self.set_hover(within(self.winfo_containing(event.x_root, event.y_root), self))
        else:
            self.restore()

    def keep_on_screen(self):
        self.update_idletasks()
        left, top, right, bottom = work_area(self)
        x = min(max(left, self.winfo_rootx()), right - self.size)
        y = min(max(top, self.winfo_rooty()), bottom - self.size)
        self.geometry(f"+{x}+{y}")


class ScrollPage(tk.Frame):
    def __init__(self, parent, *, bg=None, padding=(20, 18), bottom_radius=0):
        bg = bg or palette_for(parent).paper
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Note.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y", pady=10)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg, padx=padding[0], pady=padding[1])
        self.content = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        def size_viewport(event):
            self.canvas.itemconfigure(self.content, width=event.width)
            if WINDOWS and bottom_radius:
                round_scroll_bottom(self.canvas, event.width, event.height, padding[0], bottom_radius)

        self.canvas.bind("<Configure>", size_viewport)
        self.wheel_owner = self.winfo_toplevel()
        self.wheel_step = 1 if MACOS and tk.TkVersion < 9 else 120
        self.scroll_bindings = {
            "<MouseWheel>": self.wheel_owner.bind("<MouseWheel>", self.scroll, add="+"),
        }
        if MACOS and tk.TkVersion >= 9:
            self.scroll_bindings["<TouchpadScroll>"] = self.wheel_owner.bind(
                "<TouchpadScroll>", self.scroll_touchpad, add="+")

    def destroy(self):
        for sequence, binding in self.scroll_bindings.items():
            self.wheel_owner.unbind(sequence, binding)
        super().destroy()

    def scroll(self, event):
        if within(event.widget, self):
            steps = int(event.delta / self.wheel_step)
            self.canvas.yview_scroll(-steps, "units")

    def scroll_touchpad(self, event):
        if within(event.widget, self):
            bounds = self.canvas.bbox(self.content)
            if bounds and bounds[3] > bounds[1]:
                _, vertical = self.tk.splitlist(self.tk.call("tk::PreciseScrollDeltas", event.delta))
                fraction = self.canvas.yview()[0] - int(vertical) / (bounds[3] - bounds[1])
                self.canvas.yview_moveto(fraction)

    def reveal(self, widget):
        bounds = self.canvas.bbox(self.content)
        if not bounds:
            return
        top = widget.winfo_y()
        height = self.canvas.winfo_height()
        current = self.canvas.canvasy(0)
        if widget.winfo_height() > height:
            desired = top
        else:
            desired = max(top + widget.winfo_height() - height, min(top, current))
        if desired != current and bounds[3] > bounds[1]:
            self.canvas.yview_moveto((desired - bounds[1]) / (bounds[3] - bounds[1]))


class ProjectPopup(tk.Toplevel):
    PAGE_INSET = 10
    TILE_PADDING = 3

    def __init__(self, root, anchor, group, scale, open_thread):
        super().__init__(root)
        self.notes_palette = palette = palette_for(root)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        outside = popup_background(self, palette.card)
        self.configure(bg=outside)
        self.anchor = anchor
        self.scale = scale
        self.anchor_box = None
        self.uses_outer_edge = False
        self.content_width = None
        self.links = {}
        self.project_title = group["title"]
        self.project_path = group["subtitle"]
        heading_size = 15 if palette.precise_corners else 12
        self.title_font = tkfont.Font(self, font=ui_font(self, heading_size, "bold"))
        self.path_font = tkfont.Font(self, font=ui_font(self, 8))
        card_title_font = tkfont.Font(self, font=ui_font(self, 10, "bold"))
        shell = RoundedSurface(self, outside=outside, radius=round(17 * scale),
                               border=palette.popup_border)
        shell.pack(fill="both", expand=True)
        self.header = tk.Frame(shell, bg=palette.card)
        self.header.pack(fill="x", padx=round(14 * scale),
                         pady=(round(12 * scale), round(11 * scale))
                         if palette.precise_corners else (11, 3))
        title_row = tk.Frame(self.header, bg=palette.card)
        title_row.pack(fill="x")
        status_color = (palette.muted if palette.precise_corners
                        else palette.project_colors[group["status"]][3])
        self.count = label(title_row, f"{len(group['threads'])} 个会话", size=9,
                           color=status_color, bg=palette.card)
        self.count.pack(side="right", padx=(8, 0))
        self.title_label = label(title_row, "", weight="bold", size=heading_size, bg=palette.card)
        self.title_label.pack(side="left", fill="x", expand=True)
        self.path_label = None
        if self.project_path:
            self.path_label = label(self.header, "", size=8, color=palette.muted, bg=palette.card)
            self.path_label.pack(fill="x", pady=(2, 0))
        if not palette.precise_corners:
            tk.Frame(self.header, bg=palette.line, height=1).pack(fill="x", pady=(7, 0))
        self.update_idletasks()
        self.page = ScrollPage(shell, bg=palette.card, padding=(self.TILE_PADDING, 0))
        self.page.pack(fill="both", expand=True, padx=self.PAGE_INSET, pady=(0, 10))
        for thread in group["threads"]:
            thread_id = thread["id"]
            card = SessionCard(self.page.body, thread, scale, card_title_font, self.path_font,
                               lambda thread_id=thread_id: open_thread(thread_id))
            card.bind("<FocusIn>", lambda event: self.page.reveal(event.widget), add="+")
            self.links[thread_id] = card
        self.place_next_to_anchor()
        self.deiconify()
        self.lift()

    def place_next_to_anchor(self):
        box = screen_box(self.anchor)
        root_left, _, root_right, _ = screen_box(self.master)
        geometry = box, root_left, root_right
        if geometry == self.anchor_box:
            return
        self.anchor_box = geometry
        left, top, right, bottom = work_area(self.anchor)
        x0, y0, x1, y1 = box
        gap = round(8 * self.scale)
        columns = min(3, len(self.links))
        compact = self.notes_palette.precise_corners
        tile_size, width_limit = (110, 376) if compact else (130, 428)
        preferred = round(min(width_limit, 34 + tile_size * columns + 8 * (columns - 1))
                          * self.scale)
        min_width = min(preferred, round(245 * self.scale))
        outer_left = root_left - left - gap
        outer_right = right - root_right - gap
        self.uses_outer_edge = (
            self.notes_palette.precise_corners and max(outer_left, outer_right) >= min_width
        )
        if self.uses_outer_edge:
            near_left, near_right = root_left, root_right
            space_left, space_right = outer_left, outer_right
        else:
            near_left, near_right = x0, x1
            space_left, space_right = x0 - left - gap, right - x1 - gap
        # Prefer the closest window edge so the popup covers fewer neighboring tiles.
        use_right = x0 + x1 >= root_left + root_right
        if (space_right if use_right else space_left) < min_width:
            use_right = space_right >= space_left
        side_space = space_right if use_right else space_left
        max_height = min(bottom - top, round(448 * self.scale))
        if side_space >= min_width:
            width = min(preferred, side_space)
            x = near_right + gap if use_right else near_left - width - gap
        else:
            width = min(preferred, right - left)
            x = min(max(left, x0), right - width)
            down, up = bottom - y1 - gap, y0 - top - gap
            max_height = max(1, min(max_height, max(down, up)))

        if width != self.content_width:
            # Set the header and tile sizes before measuring the popup.
            self.content_width = width
            title_width = max(70, width - self.count.winfo_reqwidth() - 42)
            self.title_label.configure(text=two_line_text(
                self.project_title, self.title_font, title_width))
            if self.path_label is not None:
                self.path_label.configure(text=two_line_text(
                    self.project_path, self.path_font, max(70, width - 32)))
            tile_width = width - self.page.bar.winfo_reqwidth()
            tile_width -= 2 * (self.PAGE_INSET + self.TILE_PADDING)
            cards = self.links.values()
            tile_height = next(iter(cards)).compact_height() if compact and cards else None
            layout_tiles(cards, tile_width, self.scale, height=tile_height,
                         gap=8, target=98, maximum=tile_size + 4, column_limit=columns)
            self.update_idletasks()
        padding = round(34 * self.scale) if compact else 25
        height = min(max_height, self.header.winfo_reqheight() + self.page.body.winfo_reqheight()
                     + padding)
        if side_space >= min_width:
            top_offset = round(36 * self.scale) if compact else 0
            y = min(max(top, y0 - top_offset), bottom - height)
        else:
            y = y1 + gap if down >= up else y0 - height - gap
        self.geometry(f"{width}x{height}+{x}+{y}")

    def bridges(self, x, y):
        x0, y0, x1, y1 = screen_box(self.anchor)
        px0, py0, px1, py1 = screen_box(self)
        if max(y0, py0) <= y < min(y1, py1):
            return x1 <= x < px0 or px1 <= x < x0
        if max(x0, px0) <= x < min(x1, px1):
            return y1 <= y < py0 or py1 <= y < y0
        return False


class StickyWindow:
    def __init__(self, root, store=None, thread_reader=read_project_threads, *,
                 preview=False, orange_demo=True, project_color_demo=None):
        self.root = root
        orange_theme = (orange_demo and not preview) or project_color_demo is not None
        title_suffix, self.project_backgrounds = (
            PROJECT_COLOR_DEMOS[project_color_demo] if project_color_demo is not None
            else ("方块预览" if preview else "", {})
        )
        self.orange_theme = orange_theme
        if orange_theme:
            root.notes_palette = ORANGE_MAIN if project_color_demo is None else ORANGE
        else:
            root.notes_palette = SAGE
        self.palette = root.notes_palette
        self.store = store or TaskStore()
        self.thread_reader = thread_reader
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.tasks = None
        self.threads = None
        self.unread_threads = None
        self.alert_threads = set()
        self.rendered_threads = None
        self.project_cards = {}
        self.popup = None
        self.hover_timer = None
        self.pending_hover = None
        self.pointer_left_at = None
        self.keyboard_popup = False
        self.floating = None
        self.floating_position = None
        self.edge_drag = None
        self.header_drag = None
        self.collapsed = False
        self.task_feedback = tk.StringVar()
        self.tasks_fixed = tk.BooleanVar(value=False)
        self.fixed_task_host = None
        self.fixed_task_rows = None
        self.thread_feedback = tk.StringVar(value="正在读取本机会话…")
        self.show_project_counts = True
        self.pinned = tk.BooleanVar(value=False)
        root.title(f"Codex 便签 · {title_suffix}" if title_suffix else "Codex 便签")
        self.scale = root.winfo_fpixels("1i") / 96
        left, top, right, bottom = work_area(root)
        width = min(round(510 * self.scale), right - left - 55)
        height = min(round((672 if orange_theme else 700) * self.scale), bottom - top - 70)
        x = left + max(20, (right - left - width - round(428 * self.scale)) // 2)
        y = top + (bottom - top - height) // 2
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(round(355 * self.scale), round(380 * self.scale))
        paper = self.palette.paper
        root.configure(bg=paper)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Unmap>", self.on_unmap)
        root.bind("<Escape>", self.escape_project)
        if WINDOWS and orange_theme:
            root.bind("<Map>", self.on_map, add="+")
            self.rounded_window = RoundedWindow(
                root, round(30 * self.scale), resize_margin=round(6 * self.scale),
                corner_colors=lambda: (self.palette.hero, self.palette.paper))
            root.bind("<ButtonPress-1>", self.resize_from_edge, add="+")
            root.bind("<B1-Motion>", self.drag_window, add="+")
            root.bind("<ButtonRelease-1>", self.finish_window_drag, add="+")
            root.bind("<Motion>", lambda event: set_resize_cursor(
                self.rounded_window.resize_hit(event.x_root, event.y_root)), add="+")

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Note.Vertical.TScrollbar", background=self.palette.scroll, troughcolor=paper,
                        bordercolor=paper, lightcolor=paper, darkcolor=paper, arrowsize=0,
                        width=8, gripcount=0)
        style.map("Note.Vertical.TScrollbar", background=[("active", self.palette.scroll_hover)])

        self.make_header()
        padding = (round(13 * self.scale), 0) if orange_theme else (20, 18)
        frame_inset = round(17 * self.scale) if orange_theme else 0
        self.page = ScrollPage(root, padding=padding, bottom_radius=frame_inset)
        # Keep the curved bottom edge outside the scroll viewport.
        self.page.pack(fill="both", expand=True, padx=(0, 6), pady=(0, frame_inset))
        if orange_theme:
            self.task_inset = frame_inset
            self.inline_task_host = tk.Frame(self.page.body, bg=paper)
            self.inline_task_host.pack(fill="x", pady=(self.task_inset, 0))
            self.root.bind("<Configure>", self.resize_fixed_task_rows, add="+")
            self.make_tasks(self.inline_task_host)
        else:
            self.make_tasks(self.page.body)
        self.make_threads(self.page.body)
        self.refresh_tasks()
        self.refresh_threads()
        root.after(15000, self.tick)

    def make_header(self):
        palette = self.palette
        if self.orange_theme:
            if WINDOWS:
                self.root.iconphoto(True, icon(self.root, "note", 32, palette.accent))
            self.make_orange_masthead()
            return

        hero = RoundedSurface(self.root, fill=palette.hero, radius=20, border=palette.hero_border)
        hero.pack(fill="x", padx=(20, 20), pady=(14, 0))
        window_icon = tk.PhotoImage(master=self.root, width=24, height=24)
        for color, bounds in (
            (palette.action, (2, 2, 22, 22)), (palette.card, (7, 5, 17, 19)),
            (palette.accent, (9, 9, 15, 10)), (palette.accent, (9, 12, 13, 13)),
        ):
            window_icon.put(color, to=bounds)
        if WINDOWS:
            self.root.iconphoto(True, window_icon)
        top = tk.Frame(hero, bg=palette.hero)
        top.pack(fill="x", padx=14, pady=12)
        size = round(46 * self.scale)
        logo = tk.Canvas(top, width=size, height=size, bg=palette.hero, highlightthickness=0)
        logo.pack(side="left", padx=(0, 10))
        rounded_rect(logo, 1, 1, size - 2, size - 2, size * 0.3,
                     fill=palette.card, outline=palette.hero_border)
        note_mark(logo, 0, 1, size / 60, palette.accent)
        label(top, "Codex 便签", size=17, weight="bold", bg=palette.hero).pack(side="left")
        self.make_header_controls(top, side="right")
        hills = tk.Canvas(top, width=1, height=round(44 * self.scale), bg=palette.hero,
                          highlightthickness=0)
        hills.pack(side="left", fill="both", expand=True, padx=7)
        hills.bind("<Configure>", lambda _: paint_hills(hills))

    def make_header_controls(self, parent, *, side):
        palette = self.palette
        if side == "left":
            self.collapse_button = text_button(
                parent, "收起", self.collapse, bg=palette.hero, fg=palette.ink, padx=3)
            self.collapse_button.configure(font=ui_font(parent, 11))
        else:
            self.collapse_button = PillButton(parent, "收起", self.collapse, outside=palette.hero)
            self.collapse_button.pack(side=side, padx=(5, 0))
        self.pin_control = tk.Checkbutton(
            parent, text="置顶", variable=self.pinned, command=self.toggle_pin,
            font=ui_font(parent, 11 if side == "left" else 9),
            bg=palette.hero, fg=palette.ink, activebackground=palette.hero,
            activeforeground=palette.ink, selectcolor=palette.card, cursor="hand2", padx=0,
            highlightthickness=1, highlightbackground=palette.hero, highlightcolor=palette.accent,
        )
        if self.orange_theme:
            rounded_indicator(self.pin_control, self.scale, on_hero=True)
        self.pin_control.pack(side=side)
        if side == "left":
            tk.Frame(parent, bg=palette.hero_border, width=1, height=16).pack(
                side="left", padx=8)
            self.collapse_button.pack(side="left")

    def make_orange_masthead(self):
        palette = self.palette
        hero = tk.Frame(self.root, bg=palette.hero)
        hero.pack(fill="x")
        top = tk.Frame(hero, bg=palette.hero)
        top.pack(fill="x", padx=round(24 * self.scale), pady=round(5 * self.scale))
        top.columnconfigure(2, weight=1)
        title = label(top, "Codex 便签", size=24, weight="bold", bg=palette.hero)
        controls = tk.Frame(top, bg=palette.hero)
        self.make_header_controls(controls, side="left")
        if WINDOWS:
            tk.Frame(controls, bg=palette.hero_border, width=1, height=16).pack(
                side="left", padx=8)
            close_image = icon(controls, "close", round(16 * self.scale), palette.ink)
            close_button = text_button(
                controls, "关闭", self.close, bg=palette.hero, fg=palette.ink,
                hover_bg=palette.hero_border, image=close_image,
                padx=round(6 * self.scale), pady=round(6 * self.scale))
            close_button.bind("<Return>", lambda _: close_button.invoke())
            close_button.pack(side="left")

        size = round(64 * self.scale)
        art = tk.Canvas(top, width=size + 12, height=size, bg=palette.hero, highlightthickness=0)
        paint_smooth_rect(art, 9, 4, size - 6, size - 8, size // 2, "#fa9628", "#fa9628")
        self.hero_image = load_note_art(art, size)
        if self.hero_image is None:
            note_mark(art, 0, 0, size / 58, palette.ink)
        else:
            art.create_image((size + 12) // 2, size // 2, image=self.hero_image)

        gap = round(21 * self.scale)
        stacked = False
        title.grid(row=0, column=0, sticky="w")
        controls.grid(row=0, column=1, sticky="w", padx=(gap, 0))
        art.grid(row=0, column=2, sticky="e")

        def arrange_masthead(event):
            nonlocal stacked
            single_row_width = sum(widget.winfo_reqwidth() for widget in (title, controls, art))
            narrow = event.width < single_row_width + gap
            if narrow == stacked:
                return
            stacked = narrow
            title.grid_configure(columnspan=2 if stacked else 1)
            controls.grid_configure(row=1 if stacked else 0, column=0 if stacked else 1,
                                    columnspan=2 if stacked else 1,
                                    padx=(0 if stacked else gap, 0))
            art.grid_configure(rowspan=2 if stacked else 1)

        top.bind("<Configure>", arrange_masthead)
        if WINDOWS:
            for area in (hero, top, title, controls, art):
                area.configure(cursor="fleur")
                area.bind("<ButtonPress-1>", self.drag_header)

    def on_map(self, event):
        if event.widget is self.root:
            hide_window_frame(self.root)

    def drag_header(self, event):
        if not self.resize_from_edge(event):
            self.dismiss_project()
            self.header_drag = (event.x_root, event.y_root, self.root.winfo_rootx(),
                                self.root.winfo_rooty())
        return "break"

    def resize_from_edge(self, event):
        hit = self.rounded_window.resize_hit(event.x_root, event.y_root)
        if hit and self.rounded_window.shape is not None:
            self.dismiss_project()
            _, (left, top, _, _) = self.rounded_window.shape
            self.edge_drag = (hit, event.x_root, event.y_root,
                              self.root.winfo_rootx() - left, self.root.winfo_rooty() - top,
                              self.root.winfo_width(), self.root.winfo_height())
            return "break"

    def drag_window(self, event):
        if self.header_drag is not None:
            start_x, start_y, x, y = self.header_drag
            set_window_bounds(self.root, x + event.x_root - start_x, y + event.y_root - start_y,
                              self.root.winfo_width(), self.root.winfo_height())
            return "break"
        if self.edge_drag is None:
            return
        hit, start_x, start_y, x, y, width, height = self.edge_drag
        dx, dy = event.x_root - start_x, event.y_root - start_y
        min_width, min_height = self.root.minsize()
        if hit in (10, 13, 16):
            new_width = max(min_width, width - dx)
            x += width - new_width
            width = new_width
        elif hit in (11, 14, 17):
            width = max(min_width, width + dx)
        if hit in (12, 13, 14):
            new_height = max(min_height, height - dy)
            y += height - new_height
            height = new_height
        elif hit in (15, 16, 17):
            height = max(min_height, height + dy)
        set_window_bounds(self.root, x, y, width, height)
        return "break"

    def finish_window_drag(self, _):
        self.header_drag = None
        self.edge_drag = None

    def make_content_panel(self, parent, *, pady=0):
        palette = self.palette
        if self.orange_theme:
            shell = RoundedSurface(parent, radius=round(17 * self.scale), antialias=True)
            shell.pack(fill="x", pady=pady)
            panel = tk.Frame(shell, bg=palette.card)
            panel.pack(fill="x", padx=round(14 * self.scale), pady=round(12 * self.scale))
        else:
            panel = tk.Frame(parent, bg=palette.paper)
            panel.pack(fill="x", pady=pady)
        return panel

    def make_tasks(self, parent):
        palette = self.palette
        task_panel = self.make_content_panel(parent)
        self.task_panel = task_panel.master if self.orange_theme else task_panel
        panel_bg = task_panel["bg"]
        heading = tk.Frame(task_panel, bg=panel_bg)
        heading.pack(fill="x", pady=(0, round(14 * self.scale) if self.orange_theme else 9))
        label(heading, "待办", size=16 if self.orange_theme else 14, weight="bold",
              bg=panel_bg).pack(side="left")
        self.count = label(heading, "", color=palette.muted,
                           size=11 if self.orange_theme else 9, bg=panel_bg)
        if self.orange_theme:
            tk.Frame(heading, bg=palette.line, width=1, height=16).pack(side="left", padx=9)
            self.count.pack(side="left")
            self.task_freeze_switch = capsule_switch(
                heading, "固定待办", self.tasks_fixed, self.toggle_tasks_fixed, self.scale)
            self.task_freeze_switch.pack(side="right")
        else:
            self.count.pack(side="right")

        entry_row = tk.Frame(task_panel, bg=panel_bg)
        entry_row.pack(fill="x", pady=(0, 8))
        caption = "添加" if self.orange_theme else "添加待办"
        add_button = PillButton(entry_row, caption, self.add_task, primary=True, outside=panel_bg,
                                radius=round(10 * self.scale) if self.orange_theme else 20,
                                antialias=self.orange_theme)
        if self.orange_theme:
            add_button.control.configure(font=ui_font(entry_row, 11, "bold"))
            add_button.control.pack_configure(padx=round(21 * self.scale),
                                              pady=round(8 * self.scale))
        add_button.pack(side="right", padx=(round(9 * self.scale), 0))
        entry_border = palette.hero_border if self.orange_theme else palette.line
        entry_shell = RoundedSurface(entry_row, outside=panel_bg, fill=palette.field,
                                     radius=round(9 * self.scale) if self.orange_theme else 14,
                                     border=entry_border, antialias=self.orange_theme)
        entry_shell.pack(side="left", fill="both", expand=True)
        entry_size = 11 if self.orange_theme else 10
        self.entry = tk.Entry(entry_shell, font=ui_font(entry_shell, entry_size),
                              bg=palette.field, fg=palette.ink,
                              relief="flat", bd=0, highlightthickness=0,
                              insertbackground=palette.ink)
        self.entry.pack(fill="both", expand=True, padx=round(13 * self.scale),
                        pady=round(8 * self.scale) if self.orange_theme else 5)
        self.entry.bind("<Return>", lambda _: self.add_task())
        self.entry.bind("<FocusIn>", lambda _: entry_shell.set_border(palette.accent))
        self.entry.bind("<FocusOut>", lambda _: entry_shell.set_border(entry_border))
        if self.orange_theme:
            self.entry_hint = label(entry_shell, "记一条待办", size=11, color=palette.muted,
                                    bg=palette.field, padx=0)
            self.entry_hint.bind("<Button-1>", lambda _: self.entry.focus_set())
            self.entry.bind("<FocusIn>", lambda _: self.entry_hint.place_forget(), add="+")
            self.entry.bind("<FocusOut>", lambda _: self.show_entry_hint(), add="+")
            self.show_entry_hint()
        if self.tasks_fixed.get():
            rows = self.fixed_task_rows = ScrollPage(task_panel, bg=panel_bg, padding=(0, 0))
            rows.canvas.configure(height=1)
            rows.pack(fill="x")
            self.task_list = rows.body
            rows.body.bind("<Configure>", self.resize_fixed_task_rows, add="+")
        else:
            self.task_list = tk.Frame(task_panel, bg=panel_bg)
            self.task_list.pack(fill="x")
        feedback = label(task_panel, "", textvariable=self.task_feedback,
                         color=palette.muted, size=9, bg=panel_bg)

        def show_feedback(*_):
            if self.task_feedback.get():
                feedback.pack(fill="x")
            else:
                feedback.pack_forget()

        self.task_feedback_trace = self.task_feedback.trace_add("write", show_feedback)
        show_feedback()
        wrap(feedback)

    def toggle_tasks_fixed(self):
        draft, cursor = self.entry.get(), self.entry.index("insert")
        focused = self.root.focus_get()
        entry_focused = focused is self.entry
        switch_focused = focused is self.task_freeze_switch
        self.dismiss_project(redraw=True)
        self.task_feedback.trace_remove("write", self.task_feedback_trace)
        self.fixed_task_rows = None
        self.task_panel.destroy()
        if self.tasks_fixed.get():
            self.inline_task_host.pack_forget()
            self.fixed_task_host = tk.Frame(self.root, bg=self.palette.paper)
            left = round(13 * self.scale)
            right = left + 6 + self.page.bar.winfo_reqwidth()
            self.fixed_task_host.pack(before=self.page, fill="x", padx=(left, right),
                                      pady=(self.task_inset, 0))
            self.make_tasks(self.fixed_task_host)
        else:
            self.fixed_task_host.destroy()
            self.fixed_task_host = None
            self.inline_task_host.pack(before=self.page.body.pack_slaves()[0], fill="x",
                                       pady=(self.task_inset, 0))
            self.make_tasks(self.inline_task_host)
        self.render_tasks(self.tasks or [])
        self.entry.insert(0, draft)
        self.entry.icursor(cursor)
        if draft:
            self.entry_hint.place_forget()
        if entry_focused:
            self.entry.focus_set()
        elif switch_focused:
            self.task_freeze_switch.focus_set()
        self.root.update_idletasks()
        self.resize_fixed_task_rows()
        self.page.canvas.yview_moveto(0)

    def resize_fixed_task_rows(self, event=None):
        rows = self.fixed_task_rows
        if rows is None or (event is not None and event.widget not in (self.root, rows.body)):
            return
        top = rows.winfo_rooty() - self.root.winfo_rooty()
        # Leave room for projects even when the task list is larger than the window.
        limit = max(round(36 * self.scale),
                    self.root.winfo_height() * 2 // 3 - top - round(12 * self.scale))
        height = min(rows.body.winfo_reqheight(), limit)
        if int(rows.canvas["height"]) != height:
            rows.canvas.configure(height=height)

    def show_entry_hint(self):
        if not self.entry.get():
            self.entry_hint.place(x=round(13 * self.scale), rely=0.5, anchor="w")

    def make_threads(self, parent):
        palette = self.palette
        self.show_project_counts = not self.orange_theme
        thread_panel = self.make_content_panel(parent, pady=(round(15 * self.scale), 0))
        panel_bg = thread_panel["bg"]
        if not self.orange_theme:
            tk.Frame(thread_panel, height=1, bg=palette.line).pack(fill="x", pady=(0, 12))
        heading = tk.Frame(thread_panel, bg=panel_bg)
        heading.pack(fill="x", pady=(0, round(12 * self.scale) if self.orange_theme else 5))
        label(heading, "项目会话", size=16 if self.orange_theme else 14, weight="bold",
              bg=panel_bg).pack(side="left")
        if self.orange_theme:
            refresh = icon(heading, "refresh", round(18 * self.scale), palette.muted)
            text_button(heading, " 刷新", self.refresh_threads, bg=panel_bg, fg=palette.muted,
                        image=refresh, compound="left").pack(side="right")
        else:
            PillButton(heading, "刷新", self.refresh_threads).pack(side="right")
        summary = label(thread_panel, "", textvariable=self.thread_feedback,
                        color=palette.muted, size=9, bg=panel_bg)
        summary.pack(fill="x", pady=(0, 10))
        wrap(summary)
        self.thread_list = tk.Frame(thread_panel, bg=panel_bg)
        self.thread_list.pack(fill="x")
        self.thread_list.bind("<Configure>", lambda event: self.layout_project_cards(event.width))
        if self.orange_theme:
            self.thread_feedback.trace_add("write", lambda *_: summary.pack(
                fill="x", pady=(0, 10), before=self.thread_list) if self.thread_feedback.get()
                else summary.pack_forget())

    def close(self):
        self.dismiss_project()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def toggle_pin(self):
        self.root.attributes("-topmost", self.pinned.get())
        if WINDOWS and self.orange_theme:
            self.rounded_window.refresh()

    def on_unmap(self, event):
        if event.widget is self.root and not self.collapsed and self.root.state() == "iconic":
            self.root.after_idle(self.collapse)

    def collapse(self):
        if self.collapsed:
            return
        self.dismiss_project()
        left, top, right, bottom = work_area(self.root)
        self.floating = FloatingNote(self.root, self.restore)
        self.collapsed = True
        self.root.withdraw()
        size = self.floating.size
        position = self.floating_position or (
            max(left, right - size - 23), min(top + 140, max(top, bottom - size - 20))
        )
        self.floating.show(*position)

    def restore(self):
        if not self.collapsed:
            return
        self.floating_position = self.floating.winfo_rootx(), self.floating.winfo_rooty()
        self.floating.destroy()
        self.floating = None
        self.alert_threads.clear()
        self.collapsed = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.render_projects()
        self.refresh_threads()

    def refresh_tasks(self):
        try:
            tasks = self.store.list()
        except (OSError, sqlite3.Error):
            self.task_feedback.set("暂时无法读取本地待办。")
            return
        if tasks == self.tasks:
            return
        self.tasks = tasks
        self.render_tasks(tasks)

    def render_tasks(self, tasks):
        for child in self.task_list.winfo_children():
            child.destroy()
        self.count.configure(text=f"{sum(not task['done'] for task in tasks)} 项未完成")
        if not tasks:
            empty = RoundedSurface(self.task_list, outside=self.task_list["bg"], radius=13)
            empty.pack(fill="x", pady=(0, 5))
            label(empty, "还没有待办", bg=self.palette.card, color=self.palette.muted).pack(
                fill="x", padx=12, pady=8)
        for task in tasks:
            self.show_task(task)

    def show_task(self, task):
        palette = self.palette
        if self.orange_theme:
            if self.task_list.winfo_children():
                tk.Frame(self.task_list, bg=palette.line, height=1).pack(fill="x")
            surface = tk.Frame(self.task_list, bg=palette.card)
            surface.pack(fill="x")
        else:
            surface = RoundedSurface(self.task_list, radius=13)
            surface.pack(fill="x", pady=(0, 5))
        row = tk.Frame(surface, bg=palette.card)
        row.pack(fill="x", padx=0 if self.orange_theme else 9,
                 pady=round(9 * self.scale) if self.orange_theme else 4)
        value = tk.BooleanVar(row, value=task["done"])
        checkbox = tk.Checkbutton(
            row, text=task["text"], variable=value,
            command=lambda: self.change_task(task, done=value.get()),
            font=ui_font(row, 11 if self.orange_theme else 10,
                         "overstrike" if task["done"] else "normal"),
            bg=palette.card, fg=palette.muted if task["done"] else palette.ink,
            activebackground=palette.card, selectcolor=palette.field, anchor="w", justify="left",
            wraplength=235, cursor="hand2",
            highlightthickness=1, highlightbackground=palette.card, highlightcolor=palette.accent)
        checkbox.value = value
        text_gap = round(5 * self.scale) if self.orange_theme else 0
        if self.orange_theme:
            rounded_indicator(checkbox, self.scale, text_gap=text_gap)
        text_button(row, "删除", lambda: self.remove_task(task), bg=palette.card, fg=palette.muted,
                    padx=4).pack(side="right")
        if self.orange_theme:
            tk.Frame(row, bg=palette.line, width=1, height=14).pack(side="right", padx=4)
        text_button(row, "编辑", lambda: self.edit_task(task), bg=palette.card,
                    fg=palette.muted if self.orange_theme else palette.accent, padx=4).pack(
                        side="right")
        checkbox.pack(side="left", fill="x", expand=True)
        wrap(checkbox, 27 + text_gap)

    def task_action(self, operation, *args, **kwargs):
        try:
            operation(*args, **kwargs)
        except (ValueError, KeyError) as error:
            self.task_feedback.set(error.args[0])
            return False
        except (OSError, sqlite3.Error):
            self.task_feedback.set("保存失败，请重试。")
            return False
        self.task_feedback.set("" if self.orange_theme else "已保存到本机")
        self.refresh_tasks()
        return True

    def add_task(self):
        if self.task_action(self.store.add, self.entry.get()):
            self.entry.delete(0, "end")
        self.entry.focus_set()

    def change_task(self, task, **changes):
        if not self.task_action(self.store.update, task["id"], **changes):
            self.tasks = None
            self.refresh_tasks()

    def edit_task(self, task):
        text = simpledialog.askstring("编辑待办", "待办内容", initialvalue=task["text"],
                                      parent=self.root)
        if text is not None:
            self.change_task(task, text=text)

    def remove_task(self, task):
        if messagebox.askyesno("删除待办", f"删除这条待办？\n\n{task['text'][:120]}",
                               parent=self.root):
            self.task_action(self.store.delete, task["id"])

    def tick(self):
        self.refresh_tasks()
        self.refresh_threads()
        self.root.after(15000, self.tick)

    def refresh_threads(self):
        if self.pending is None:
            self.pending = self.pool.submit(self.thread_reader)
            self.root.after(60, self.finish_refresh)

    def finish_refresh(self):
        if not self.pending.done():
            self.root.after(60, self.finish_refresh)
            return
        future, self.pending = self.pending, None
        try:
            threads = future.result()
        except (OSError, sqlite3.Error):
            self.thread_feedback.set("会话读取失败，可点刷新重试。"
                                     if self.threads is None else "刷新失败，以下是上次读取结果。")
            return
        self.update_unread_alert(threads)
        self.threads = threads
        if threads == self.rendered_threads:
            self.show_thread_summary()
        elif self.popup is None:
            self.render_projects()

    def update_unread_alert(self, threads):
        # A missing read-state snapshot makes every session's unread state unknown.
        if threads and all(thread["unread_completed"] is None for thread in threads):
            return
        unread = {thread["id"] for thread in threads if thread["unread_completed"] is True}
        if self.floating is not None and self.unread_threads is not None:
            self.alert_threads.intersection_update(unread)
            self.alert_threads.update(unread - self.unread_threads)
            self.floating.set_unread_alert(bool(self.alert_threads))
        self.unread_threads = unread

    def show_thread_summary(self):
        if not self.show_project_counts:
            self.thread_feedback.set("")
            return
        count = f"{len(self.project_cards)} 个项目 · {len(self.rendered_threads)} 个会话"
        self.thread_feedback.set(f"{count} · 悬停项目查看" if self.rendered_threads else count)

    def render_projects(self):
        if self.threads == self.rendered_threads:
            return
        self.rendered_threads = self.threads
        for child in self.thread_list.winfo_children():
            child.destroy()
        self.project_cards.clear()
        if not self.threads:
            label(self.thread_list, "没有找到本机会话", color=self.palette.muted,
                  bg=self.thread_list["bg"], pady=8).grid(sticky="w")
        groups = group_threads(self.threads)
        paths = defaultdict(list)
        for group in groups:
            if group["subtitle"]:
                paths[group["title"]].append(group["subtitle"])
        for group in groups:
            hint = (distinguishing_folder(group["subtitle"], paths[group["title"]])
                    if group["subtitle"] else "")
            self.make_project_card(group, hint)
        self.layout_project_cards(self.thread_list.winfo_width())
        self.show_thread_summary()

    def make_project_card(self, group, hint):
        summaries = {
            "unread": f"待查看 {group['unread']}",
            "running": f"有活动 {group['running']}",
            "read": "已查看",
            "unknown": "待确认",
        }
        status = group["status"]
        card_options = {}
        if status in self.project_backgrounds:
            card_options["fills"] = self.project_backgrounds[status]
        card = ProjectCard(self.thread_list, group["title"], hint, status, summaries[status],
                           self.scale, **card_options)
        for sequence in ("<Return>", "<space>"):
            card.bind(sequence, lambda _: self.open_project_with_keyboard(card, group))
        card.bind("<Enter>", lambda _: self.schedule_project_hover(card, group))
        card.bind("<ButtonRelease-1>", lambda _: self.open_project_under_pointer(card, group))
        self.project_cards[group["key"]] = card

    def layout_project_cards(self, width):
        cards = self.project_cards.values()
        if not cards:
            return
        height = next(iter(cards)).compact_height() if self.orange_theme else None
        layout_tiles(cards, width, self.scale, height=height,
                     gap=9 if self.orange_theme else 11,
                     target=98 if self.orange_theme else 104, maximum=145, column_limit=6)

    def schedule_project_hover(self, card, group):
        if self.pending_hover is not None:
            self.root.after_cancel(self.pending_hover)

        def show():
            self.pending_hover = None
            self.open_project_under_pointer(card, group)

        crossing_popup_gap = (
            self.popup is not None and self.popup.uses_outer_edge
            and self.popup.bridges(*self.root.winfo_pointerxy())
        )
        self.pending_hover = self.root.after(290 if crossing_popup_gap else 95, show)

    def open_project_under_pointer(self, card, group):
        pointed = self.root.winfo_containing(*self.root.winfo_pointerxy())
        if within(pointed, card):
            self.open_project(card, group)

    def open_project(self, card, group):
        if self.collapsed or (self.popup is not None and self.popup.anchor is card):
            return
        self.dismiss_project()
        self.popup = ProjectPopup(self.root, card, group, self.scale, self.open_thread)
        card.set_selected(True)
        self.popup.bind("<Escape>", self.escape_project)
        self.hover_timer = self.root.after(35, self.track_project)

    def open_project_with_keyboard(self, card, group):
        self.open_project(card, group)
        if self.popup is not None:
            self.keyboard_popup = True
            first_link = next(iter(self.popup.links.values()))
            first_link.focus_force()
        return "break"

    def track_project(self):
        self.hover_timer = None
        popup = self.popup
        card = popup.anchor
        _, y0, _, y1 = screen_box(card)
        _, visible_top, _, visible_bottom = screen_box(self.page.canvas)
        if not self.root.winfo_viewable() or y1 <= visible_top or y0 >= visible_bottom:
            self.dismiss_project(redraw=True)
            return
        x, y = self.root.winfo_pointerxy()
        pointed = self.root.winfo_containing(x, y)
        has_focus = self.keyboard_popup and within(self.root.focus_get(), popup)
        if within(pointed, card) or within(pointed, popup) or popup.bridges(x, y) or has_focus:
            self.pointer_left_at = None
        elif self.pointer_left_at is None:
            self.pointer_left_at = time.monotonic()
        elif time.monotonic() - self.pointer_left_at >= 0.18:
            self.dismiss_project(redraw=True)
            return
        popup.place_next_to_anchor()
        self.hover_timer = self.root.after(35, self.track_project)

    def dismiss_project(self, *, redraw=False):
        if self.pending_hover is not None:
            self.root.after_cancel(self.pending_hover)
            self.pending_hover = None
        if self.hover_timer is not None:
            self.root.after_cancel(self.hover_timer)
            self.hover_timer = None
        if self.popup is not None:
            self.popup.anchor.set_selected(False)
            self.popup.destroy()
            self.popup = None
        self.pointer_left_at = None
        self.keyboard_popup = False
        if redraw:
            self.render_projects()

    def escape_project(self, _):
        if self.popup is not None:
            self.root.focus_set()
            self.dismiss_project(redraw=True)
            return "break"

    def open_thread(self, thread_id):
        self.dismiss_project(redraw=True)
        try:
            open_thread_link(thread_id)
        except OSError:
            messagebox.showerror("打开会话失败", "请确认本机已安装 Codex 桌面应用。",
                                 parent=self.root)
        else:
            self.root.after(1300, self.refresh_threads)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--background", action="store_true")
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--orange-demo", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--project-color-demo", choices=PROJECT_COLOR_DEMOS)
    options = parser.parse_args()
    if options.project_color_demo:
        name = f"project-color-demo-{options.project_color_demo}"
    else:
        name = "hover-preview" if options.preview else "window"
    instance = Instance(name)
    activation = None
    try:
        activation = Event(f"{name}-activate")
        if not instance.primary:
            if not options.background:
                activation.signal()
            return
        if WINDOWS:
            ctypes.windll.user32.SetProcessDPIAware()
        root = tk.Tk()
        if options.background:
            root.withdraw()
        window = StickyWindow(root, preview=options.preview,
                              project_color_demo=options.project_color_demo)

        def show_window():
            window.restore()
            root.deiconify()
            root.lift()
            root.focus_force()

        def check_activation():
            if activation.wait():
                show_window()
            root.after(250, check_activation)

        if MACOS:
            root.createcommand("::tk::mac::ReopenApplication", show_window)
            root.createcommand("::tk::mac::Quit", window.close)
        if options.background:
            root.after_idle(window.collapse)
        root.after(250, check_activation)
        root.mainloop()
    finally:
        if activation is not None:
            activation.close()
        instance.close()


if __name__ == "__main__":
    main()
