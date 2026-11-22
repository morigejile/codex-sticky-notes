"""Single-page Codex sticky notes."""

import argparse
import ctypes
import sqlite3
import sys
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from tkinter import messagebox, simpledialog, ttk
from tkinter import font as tkfont

from appearance import (
    PillButton, ProjectCard, RoundedSurface, SessionCard, capsule_switch, label, note_mark,
    paint_smooth_rect, rounded_indicator, rounded_rect, text_button, two_line_text, ui_font, wrap,
)
from data import (
    APP_HOME, TaskInputError, TaskNotFoundError, TaskStore,
    group_threads, read_project_threads,
)
from i18n import (
    LANGUAGE_CHOICES, Translator, load_language, project_name, save_language, thread_title, translator_for,
)
from launch import open_thread_link
from note_art import load_note_art
from note_icons import icon
from palette import ORANGE

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
if WINDOWS:
    from lifecycle import Event, Instance
    from native_frame import (
        RESIZE_CURSORS, RoundedWindow, hide_window_frame, round_scroll_bottom, set_window_bounds,
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


def popup_background(widget, fallback):
    if WINDOWS:
        transparent = "#ff00fe"
        widget.attributes("-transparentcolor", transparent)
        return transparent
    if MACOS:
        widget.attributes("-transparent", True)
        return "systemTransparent"
    return fallback


def tile_dimensions(width, scale, *, gap, target, maximum, column_limit):
    gap = round(gap * scale)
    target = round(target * scale)
    columns = max(1, min(column_limit, (width + gap) // (target + gap)))
    side = max(1, min(round(maximum * scale), (width - gap * (columns - 1)) // columns))
    return columns, side, gap


class FloatingNote(tk.Toplevel):
    UNREAD_ALERT_MS = 60 * 60 * 1000

    def __init__(self, root, restore):
        super().__init__(root)
        self.notes_tr = translator_for(root)
        self.palette = ORANGE
        self.restore = restore
        self.press = None
        self.dragged = False
        self.alert_timer = None
        self.alert_expiry = None
        self.pin_highlight = False
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.67)
        self.title(self.notes_tr("app.open"))
        outside = (self.palette.floating if WINDOWS
                   else popup_background(self, self.palette.floating))
        self.configure(bg=outside)

        self.scale = self.winfo_fpixels("1i") / 96
        self.size = round(54 * self.scale)
        self.tooltip = None
        self.face = tk.Canvas(self, width=self.size, height=self.size, bg=outside,
                              highlightthickness=0, cursor="hand2", takefocus=True)
        self.face.pack()
        if WINDOWS:
            self.rounded_window = RoundedWindow(
                self, round(18 * self.scale), corner_colors=lambda: (self.face["bg"],) * 2)
        self.art = load_note_art(self.face, round(self.size * 0.85))
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
        if WINDOWS:
            canvas.configure(bg=fill)
            self.rounded_window.refresh()
        else:
            rounded_rect(canvas, 2, 2, size - 2, size - 2, size * 0.30, fill=fill,
                         outline=self.palette.hero_border if hovered else fill, width=1)
        if self.art is not None:
            canvas.create_image(size / 2, size / 2, image=self.art)
        else:
            mark = icon(canvas, "note", round(size * 0.68), self.palette.ink)
            canvas.create_image(size / 2, size / 2, image=mark)
        # The pin in the orange artwork sits near the upper-right of the image.
        x, y = size * 0.73, size * 0.26
        if self.art is not None:
            x = size / 2 + self.art.width() * 0.24
            y = size / 2 - self.art.height() * 0.32
        highlight = icon(canvas, "dot", round(13 * self.scale), "#62a4ff")
        canvas.create_image(round(x), round(y), image=highlight, tags=("unread-indicator",))
        self.highlight_pin(self.pin_highlight)
        if (hovered and self.press is None
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

    def start_unread_alert(self):
        if self.alert_expiry is not None:
            self.after_cancel(self.alert_expiry)
        self.alert_expiry = self.after(self.UNREAD_ALERT_MS, self.stop_unread_alert)
        if self.alert_timer is None:
            self.flash_pin()

    def stop_unread_alert(self):
        if self.alert_expiry is not None:
            self.after_cancel(self.alert_expiry)
            self.alert_expiry = None
        if self.alert_timer is not None:
            self.after_cancel(self.alert_timer)
            self.alert_timer = None
            self.highlight_pin(False)

    def destroy(self):
        self.stop_unread_alert()
        super().destroy()

    def show_tooltip(self):
        if self.tooltip is None:
            self.tooltip = tk.Toplevel(self)
            self.tooltip.withdraw()
            self.tooltip.overrideredirect(True)
            self.tooltip.attributes("-topmost", True)
            outside = popup_background(self.tooltip, self.palette.card)
            self.tooltip.configure(bg=outside)
            shell = RoundedSurface(self.tooltip, outside=outside,
                                   radius=round(15 * self.scale))
            shell.pack(fill="both", expand=True)
            label(shell, self.notes_tr("app.open"), size=10, weight="bold", bg=self.palette.card).pack(
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
    def __init__(self, parent, *, bg=None, padding=(20, 18), bottom_radius=0, virtual=False):
        bg = bg or ORANGE.paper
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Note.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y", pady=10)
        self.canvas.pack(side="left", fill="both", expand=True)
        if virtual:
            self.content = self.canvas.create_rectangle(0, 0, 0, 0, width=0, outline="")
        else:
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

    def reveal(self, top, height):
        bounds = self.tk.splitlist(self.canvas.cget("scrollregion"))
        if not bounds:
            return
        start, end = float(bounds[1]), float(bounds[3])
        viewport_height = self.canvas.winfo_height()
        current = self.canvas.canvasy(0)
        if height > viewport_height:
            desired = top
        else:
            desired = max(top + height - viewport_height, min(top, current))
        if desired != current and end > start:
            self.canvas.yview_moveto((desired - start) / (end - start))


class ProjectPopup(tk.Toplevel):
    GRID_WIDTH = 524

    def __init__(self, root, anchor, group, scale, open_thread):
        super().__init__(root)
        self.notes_tr = translator_for(root)
        palette = ORANGE
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        radius = round(17 * scale)
        border = palette.popup_border
        if WINDOWS:
            outside = border
            self.rounded_window = RoundedWindow(self, radius, corner_colors=lambda: (outside, outside))
            # Windows blends the outer contour. The inset surface paints the inside of the rim.
            radius -= 1
            border = palette.card
        else:
            outside = popup_background(self, palette.card)
        self.configure(bg=outside)
        self.anchor = anchor
        self.scale = scale
        self.anchor_box = None
        self.uses_outer_edge = False
        self.content_width = None
        self.sessions = group["threads"]
        self.session_titles = [thread_title(thread, self.notes_tr, hide_project=True)
                               for thread in self.sessions]
        self.open_thread = open_thread
        self.links = {}
        self.project_title = group["title"]
        self.project_path = group["subtitle"]
        heading_size = 15
        self.title_font = tkfont.Font(self, font=ui_font(heading_size, "bold"))
        self.path_font = tkfont.Font(self, font=ui_font(8))
        self.card_title_font = tkfont.Font(self, font=ui_font(10, "bold"))
        shell = RoundedSurface(self, outside=outside, radius=radius, border=border, antialias=True)
        shell.pack(fill="both", expand=True)
        self.page_inset = round(12 * scale)
        self.header_pady = self.page_inset, round(9 * scale)
        self.header = tk.Frame(shell, bg=palette.card)
        self.header.pack(fill="x", padx=self.page_inset + round(8 * scale), pady=self.header_pady)
        title_row = tk.Frame(self.header, bg=palette.card)
        title_row.pack(fill="x")
        self.count = label(title_row, self.notes_tr.count("sessions.count", len(self.sessions)), size=9,
                           color=palette.muted, bg=palette.card)
        self.count.pack(side="right", padx=(8, 0))
        self.title_label = label(title_row, "", weight="bold", size=heading_size, bg=palette.card)
        self.title_label.pack(side="left", fill="x", expand=True)
        self.path_label = None
        if self.project_path:
            self.path_label = label(self.header, "", size=8, color=palette.muted, bg=palette.card)
            self.path_label.pack(fill="x", pady=(2, 0))
        self.page = ScrollPage(shell, bg=palette.card, virtual=True)
        self.page.pack(fill="both", expand=True, padx=self.page_inset, pady=(0, self.page_inset))
        self.card_height = self.make_session_card(0).compact_height()
        self.place_next_to_anchor()
        self.page.canvas.configure(yscrollcommand=self.update_scrollbar)
        self.deiconify()
        self.lift()
        self.update_idletasks()
        self.render_visible_sessions()

    def make_session_card(self, index):
        thread = self.sessions[index]
        thread_id = thread["id"]
        canvas = self.page.canvas
        card = SessionCard(canvas, thread, self.session_titles[index],
                           self.scale, self.card_title_font, self.path_font,
                           lambda: self.open_thread(thread_id))
        card.window_item = canvas.create_window(0, 0, window=card, anchor="nw")
        card.bind("<FocusIn>", lambda _: self.reveal_session(index), add="+")
        card.bind("<<NextWindow>>", lambda _: self.focus_session(index + 1))
        card.bind("<<PrevWindow>>", lambda _: self.focus_session(index - 1))
        self.links[thread_id] = card
        return card

    def place_session_card(self, index, card):
        canvas = self.page.canvas
        row, column = divmod(index, self.columns)
        canvas.coords(card.window_item, column * (self.card_width + self.card_gap),
                      row * self.row_height)
        canvas.itemconfigure(card.window_item, width=self.card_width, height=self.card_height)

    def session_card(self, index):
        card = self.links.get(self.sessions[index]["id"])
        if card is None:
            card = self.make_session_card(index)
            self.place_session_card(index, card)
        return card

    def update_scrollbar(self, first, last):
        self.page.bar.set(first, last)
        self.render_visible_sessions()

    def render_visible_sessions(self):
        canvas = self.page.canvas
        top = max(0, int(canvas.canvasy(0)))
        first_row = top // self.row_height
        # Keep the following row ready for the next small scroll.
        end_row = (top + canvas.winfo_height() - 1) // self.row_height + 2
        for index in range(first_row * self.columns, min(len(self.sessions), end_row * self.columns)):
            self.session_card(index)

    def reveal_session(self, index):
        self.page.reveal((index // self.columns) * self.row_height, self.card_height)

    def focus_session(self, index):
        index %= len(self.sessions)
        card = self.session_card(index)
        self.reveal_session(index)
        card.update_idletasks()
        card.focus_force()
        return "break"

    def size_content(self, width):
        self.content_width = width
        header_width = width - 2 * (self.page_inset + round(8 * self.scale))
        title_width = max(1, header_width - self.count.winfo_reqwidth() - 8)
        self.title_label.configure(text=two_line_text(self.project_title, self.title_font, title_width))
        if self.path_label is not None:
            self.path_label.configure(text=two_line_text(
                self.project_path, self.path_font, max(1, header_width)))

        viewport_width = max(1, width - self.page.bar.winfo_reqwidth() - 2 * self.page_inset)
        self.columns, self.card_width, self.card_gap = tile_dimensions(
            viewport_width, self.scale, gap=8, target=150, maximum=self.GRID_WIDTH,
            column_limit=min(3, len(self.sessions)))
        self.row_height = self.card_height + self.card_gap
        rows = (len(self.sessions) + self.columns - 1) // self.columns
        self.list_height = rows * self.row_height - self.card_gap
        canvas = self.page.canvas
        bounds = (0, 0, viewport_width, self.list_height)
        canvas.coords(self.page.content, *bounds)
        canvas.configure(scrollregion=bounds)
        for index, thread in enumerate(self.sessions):
            card = self.links.get(thread["id"])
            if card is not None:
                self.place_session_card(index, card)
        self.update_idletasks()

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
        preferred = round((self.GRID_WIDTH if len(self.sessions) >= 3 else 350) * self.scale)
        min_width = min(preferred, round(245 * self.scale))
        outer_left = root_left - left - gap
        outer_right = right - root_right - gap
        self.uses_outer_edge = max(outer_left, outer_right) >= min_width
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
            self.size_content(width)
        padding = sum(self.header_pady) + self.page_inset
        height = min(max_height, self.header.winfo_reqheight() + self.list_height + padding)
        if side_space >= min_width:
            top_offset = round(36 * self.scale)
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
                 settings_path=None):
        self.root = root
        self.settings_path = APP_HOME / "settings.json" if settings_path is None else settings_path
        self.language_preference = load_language(self.settings_path)
        self.language_choice = tk.StringVar(root, value=self.language_preference)
        self.tr = root.notes_tr = Translator(self.language_preference)
        self.text_variables = {}
        self.reflow_masthead = None
        self.palette = ORANGE
        self.store = store or TaskStore()
        self.thread_reader = thread_reader
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.tasks = None
        self.threads = None
        self.unread_threads = None
        self.rendered_threads = None
        self.project_cards = {}
        self.project_groups = {}
        self.popup = None
        self.hover_timer = None
        self.pending_hover = None
        self.pointer_left_at = None
        self.keyboard_popup = False
        self.floating = None
        self.floating_position = None
        self.edge_drag = None
        self.edge_cursor = None
        self.header_drag = None
        self.collapsed = False
        self.task_feedback = tk.StringVar()
        self.task_feedback_key = None
        self.tasks_fixed = tk.BooleanVar(value=False)
        self.fixed_task_host = None
        self.fixed_task_rows = None
        self.thread_feedback_key = "sessions.loading"
        self.thread_feedback = tk.StringVar(value=self.tr(self.thread_feedback_key))
        self.pinned = tk.BooleanVar(value=False)
        self.update_title()
        self.scale = root.winfo_fpixels("1i") / 96
        left, top, right, bottom = work_area(root)
        width = min(round(460 * self.scale), right - left - 55)
        height = min(round(672 * self.scale), bottom - top - 70)
        x = left + max(20, (right - left - width - round(428 * self.scale)) // 2)
        y = top + (bottom - top - height) // 2
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(round(355 * self.scale), round(380 * self.scale))
        paper = self.palette.paper
        root.configure(bg=paper)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Unmap>", self.on_unmap)
        root.bind("<Escape>", self.escape_project)
        side_inset = 6
        if WINDOWS:
            side_inset = round(12 * self.scale)
            root.bind("<Map>", self.on_map, add="+")
            self.rounded_window = RoundedWindow(
                root, round(30 * self.scale), resize_margin=(side_inset, round(6 * self.scale)),
                corner_colors=lambda: (self.palette.hero, self.palette.paper))
            root.bind("<ButtonPress-1>", self.resize_from_edge, add="+")
            root.bind("<B1-Motion>", self.drag_window, add="+")
            root.bind("<ButtonRelease-1>", self.finish_window_drag, add="+")
            root.bind("<Enter>", self.update_resize_cursor, add="+")
            root.bind("<Motion>", self.update_resize_cursor, add="+")
            root.bind("<Leave>", self.update_resize_cursor, add="+")

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Note.Vertical.TScrollbar", background=self.palette.scroll, troughcolor=paper,
                        bordercolor=paper, lightcolor=paper, darkcolor=paper, arrowsize=0,
                        width=8, gripcount=0)
        style.map("Note.Vertical.TScrollbar", background=[("active", self.palette.scroll_hover)])

        self.make_header()
        padding = (round(13 * self.scale), 0)
        frame_inset = round(17 * self.scale)
        self.page = ScrollPage(root, padding=padding, bottom_radius=frame_inset)
        # Keep the curved bottom edge outside the scroll viewport.
        self.page.pack(fill="both", expand=True, padx=(0, side_inset), pady=(0, frame_inset))
        self.task_inset = frame_inset
        self.inline_task_host = tk.Frame(self.page.body, bg=paper)
        self.inline_task_host.pack(fill="x", pady=(self.task_inset, 0))
        self.root.bind("<Configure>", self.resize_fixed_task_rows, add="+")
        self.make_tasks(self.inline_task_host)
        self.make_threads(self.page.body)
        self.refresh_tasks()
        self.refresh_threads()
        root.after(15000, self.tick)

    def text(self, key):
        if key not in self.text_variables:
            self.text_variables[key] = tk.StringVar(self.root, value=self.tr(key))
        return self.text_variables[key]

    def update_title(self):
        self.root.title(self.tr("app.title"))

    def make_language_menu(self, parent):
        palette = self.palette
        button = tk.Menubutton(
            parent, textvariable=self.text("language.menu"), font=ui_font(10),
            bg=palette.hero, fg=palette.ink, activebackground=palette.hero_border,
            activeforeground=palette.ink, relief="flat", bd=0, padx=round(5 * self.scale),
            pady=0, takefocus=True, cursor="hand2", highlightthickness=1,
            highlightbackground=palette.hero, highlightcolor=palette.accent,
        )
        self.language_menu = menu = tk.Menu(button, tearoff=False)
        for choice, name in zip(LANGUAGE_CHOICES, (self.tr("language.system"), "简体中文", "English")):
            menu.add_radiobutton(label=name, value=choice, variable=self.language_choice,
                                 command=self.change_language)
        button.configure(menu=menu)
        return button

    def change_language(self):
        choice = self.language_choice.get()
        if choice != self.language_preference:
            try:
                save_language(self.settings_path, choice)
            except OSError:
                self.language_choice.set(self.language_preference)
                messagebox.showerror(self.tr("app.title"), self.tr("language.save_error"), parent=self.root)
                return
        self.language_preference = choice
        translator = Translator(choice)
        if translator.language == self.tr.language:
            return
        self.dismiss_project()
        self.tr = self.root.notes_tr = translator
        for key, variable in self.text_variables.items():
            variable.set(self.tr(key))
        self.language_menu.entryconfigure(0, label=self.tr("language.system"))
        self.update_title()
        self.render_tasks(self.tasks or [])
        self.set_task_feedback(self.task_feedback_key)
        feedback_key = self.thread_feedback_key
        if self.threads is not None:
            self.rendered_threads = None
            self.render_projects()
        if feedback_key:
            self.set_thread_feedback(feedback_key)
        if self.reflow_masthead is not None:
            self.root.update_idletasks()
            self.reflow_masthead()

    def make_header_controls(self, parent):
        palette = self.palette
        scale = self.scale
        row = tk.Frame(parent, bg=palette.hero, pady=round(4 * scale))
        row.rowconfigure(0, minsize=round(28 * scale))
        padding = round(5 * scale)
        self.pin_control = tk.Checkbutton(
            row, textvariable=self.text("action.pin"), variable=self.pinned, command=self.toggle_pin,
            font=ui_font(10), bg=palette.hero, fg=palette.ink, activebackground=palette.hero_border,
            activeforeground=palette.ink, cursor="hand2", padx=padding, pady=0,
            highlightthickness=1, highlightbackground=palette.hero, highlightcolor=palette.accent,
        )
        rounded_indicator(self.pin_control, scale, on_hero=True, text_gap=round(3 * scale))
        self.pin_control.grid(row=0, column=0, sticky="nsew")
        self.collapse_button = text_button(
            row, "", self.collapse, bg=palette.hero, fg=palette.ink, hover_bg=palette.hero_border,
            padx=padding, pady=0, textvariable=self.text("action.collapse"))
        self.collapse_button.grid(row=0, column=1, sticky="nsew")
        self.make_language_menu(row).grid(row=0, column=2, sticky="nsew")
        if WINDOWS:
            separator = tk.Frame(row, bg=palette.hero_border, width=1, height=round(14 * scale))
            separator.grid(row=0, column=3, padx=round(4 * scale))
            row.columnconfigure(4, minsize=round(24 * scale))
            close_button = text_button(
                row, "", self.close, bg=palette.hero, fg=palette.ink, hover_bg=palette.hero_border,
                image=icon(row, "close", round(16 * scale), palette.ink),
                textvariable=self.text("action.close"), padx=0, pady=0)
            close_button.bind("<Return>", lambda _: close_button.invoke())
            close_button.grid(row=0, column=4, sticky="nsew")
        return row

    def make_header(self):
        if WINDOWS:
            self.root.iconphoto(True, icon(self.root, "note", 32, self.palette.accent))
        palette = self.palette
        hero = tk.Frame(self.root, bg=palette.hero)
        hero.pack(fill="x")
        top = tk.Frame(hero, bg=palette.hero)
        top.pack(fill="x", padx=round(24 * self.scale), pady=round(5 * self.scale))
        top.columnconfigure(2, weight=1)
        title = label(top, "", size=17, weight="bold", bg=palette.hero,
                      textvariable=self.text("app.heading"))
        controls = self.make_header_controls(top)

        size = round(64 * self.scale)
        art = tk.Canvas(top, width=size + 12, height=size, bg=palette.hero, highlightthickness=0)
        paint_smooth_rect(art, 9, 4, size - 6, size - 8, size // 2, "#fa9628", "#fa9628")
        self.hero_image = load_note_art(art, size)
        if self.hero_image is None:
            note_mark(art, 0, 0, size / 58, palette.ink)
        else:
            art.create_image((size + 12) // 2, size // 2, image=self.hero_image)

        gap = round(10 * self.scale)
        heading_font = tkfont.Font(top, font=title["font"])
        control_font = tkfont.Font(top, font=ui_font(10))
        languages = [Translator(choice) for choice in LANGUAGE_CHOICES if choice != "system"]
        control_keys = ("action.pin", "action.collapse", "language.menu")
        text_widths = {
            tr.language: heading_font.measure(tr("app.heading"))
            + sum(control_font.measure(tr(key)) for key in control_keys)
            for tr in languages
        }
        widest_text = max(text_widths.values())
        stacked = False
        title.grid(row=0, column=0, sticky="w")
        controls.grid(row=0, column=1, sticky="w", padx=(gap, 0))
        art.grid(row=0, column=2, sticky="e")

        def arrange_masthead(event=None):
            nonlocal stacked
            width = event.width if event else top.winfo_width()
            # Use the same wrapping threshold for both translations.
            single_row_width = (title.winfo_reqwidth() + controls.winfo_reqwidth() + art.winfo_reqwidth()
                                + gap + widest_text - text_widths[self.tr.language])
            narrow = width < single_row_width
            if narrow == stacked:
                return
            stacked = narrow
            title.grid_configure(columnspan=2 if stacked else 1)
            controls.grid_configure(row=1 if stacked else 0, column=0 if stacked else 1,
                                    columnspan=3 if stacked else 1,
                                    padx=(0 if stacked else gap, 0))

        self.reflow_masthead = arrange_masthead
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

    def set_edge_cursor(self, widget=None, hit=0):
        if self.edge_cursor is not None:
            previous, original = self.edge_cursor
            if previous is not widget or not hit:
                if previous.winfo_exists():
                    previous.configure(cursor=original)
                self.edge_cursor = None
        if hit:
            current = widget["cursor"]
            if self.edge_cursor is None:
                self.edge_cursor = widget, current
            if current != RESIZE_CURSORS[hit]:
                widget.configure(cursor=RESIZE_CURSORS[hit])

    def update_resize_cursor(self, event):
        if self.edge_drag is None and self.header_drag is None:
            hit = self.rounded_window.resize_hit(event.x_root, event.y_root)
            pointed = self.root.winfo_containing(event.x_root, event.y_root) if hit else None
            if pointed is not None and pointed.winfo_toplevel() is self.root:
                self.set_edge_cursor(pointed, hit)
            else:
                self.set_edge_cursor()

    def resize_from_edge(self, event):
        hit = self.rounded_window.resize_hit(event.x_root, event.y_root)
        if hit and self.rounded_window.shape is not None:
            self.dismiss_project()
            _, (left, top, _, _) = self.rounded_window.shape
            self.edge_drag = (hit, event.x_root, event.y_root,
                              self.root.winfo_rootx() - left, self.root.winfo_rooty() - top,
                              self.root.winfo_width(), self.root.winfo_height())
            self.set_edge_cursor(event.widget, hit)
            event.widget.grab_set()
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

    def finish_window_drag(self, event=None):
        self.header_drag = None
        if self.edge_drag is None:
            return
        self.edge_drag = None
        widget, _ = self.edge_cursor
        if widget.winfo_exists() and widget.grab_current() is widget:
            widget.grab_release()
        if event is not None:
            self.update_resize_cursor(event)
        else:
            self.set_edge_cursor()

    def make_content_panel(self, parent, *, pady=0):
        palette = self.palette
        shell = RoundedSurface(parent, radius=round(17 * self.scale), antialias=True)
        shell.pack(fill="x", pady=pady)
        panel = tk.Frame(shell, bg=palette.card)
        panel.pack(fill="x", padx=round(14 * self.scale), pady=round(12 * self.scale))
        return panel

    def make_tasks(self, parent):
        palette = self.palette
        task_panel = self.make_content_panel(parent)
        self.task_panel = task_panel.master
        panel_bg = task_panel["bg"]
        heading = tk.Frame(task_panel, bg=panel_bg)
        heading.pack(fill="x", pady=(0, round(14 * self.scale)))
        label(heading, "", size=14, weight="bold",
              bg=panel_bg, textvariable=self.text("todo.heading")).pack(side="left")
        self.count = label(heading, "", color=palette.muted,
                           size=11, bg=panel_bg)
        tk.Frame(heading, bg=palette.line, width=1, height=16).pack(side="left", padx=9)
        self.count.pack(side="left")
        self.task_freeze_switch = capsule_switch(
            heading, "", self.tasks_fixed, self.toggle_tasks_fixed, self.scale)
        self.task_freeze_switch.configure(textvariable=self.text("todo.fix"))
        self.task_freeze_switch.pack(side="right")

        entry_row = tk.Frame(task_panel, bg=panel_bg)
        entry_row.pack(fill="x", pady=(0, 8))
        add_button = PillButton(entry_row, "", self.add_task, outside=panel_bg,
                                radius=round(10 * self.scale))
        add_button.control.configure(textvariable=self.text("todo.add"))
        add_button.control.pack_configure(padx=round(21 * self.scale),
                                          pady=round(8 * self.scale))
        add_button.pack(side="right", padx=(round(9 * self.scale), 0))
        entry_border = palette.hero_border
        entry_shell = RoundedSurface(entry_row, outside=panel_bg, fill=palette.field,
                                     radius=round(9 * self.scale),
                                     border=entry_border, antialias=True)
        entry_shell.pack(side="left", fill="both", expand=True)
        self.entry = tk.Entry(entry_shell, font=ui_font(11),
                              bg=palette.field, fg=palette.ink,
                              relief="flat", bd=0, highlightthickness=0,
                              insertbackground=palette.ink)
        self.entry.pack(fill="both", expand=True, padx=round(13 * self.scale),
                        pady=round(8 * self.scale))
        self.entry.bind("<Return>", lambda _: self.add_task())
        self.entry.bind("<FocusIn>", lambda _: entry_shell.set_border(palette.accent))
        self.entry.bind("<FocusOut>", lambda _: entry_shell.set_border(entry_border))
        self.entry_hint = label(entry_shell, "", size=11, color=palette.muted,
                                bg=palette.field, padx=0, textvariable=self.text("todo.placeholder"))
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
        thread_panel = self.make_content_panel(parent, pady=(round(15 * self.scale), 0))
        panel_bg = thread_panel["bg"]
        heading = tk.Frame(thread_panel, bg=panel_bg)
        heading.pack(fill="x", pady=(0, round(12 * self.scale)))
        label(heading, "", size=14, weight="bold",
              bg=panel_bg, textvariable=self.text("projects.heading")).pack(side="left")
        refresh = icon(heading, "refresh", round(18 * self.scale), palette.muted)
        text_button(heading, "", self.refresh_threads, bg=panel_bg, fg=palette.muted,
                    image=refresh, compound="left",
                    textvariable=self.text("action.refresh"), padx=4).pack(side="right")
        summary = label(thread_panel, "", textvariable=self.thread_feedback,
                        color=palette.muted, size=9, bg=panel_bg)
        summary.pack(fill="x", pady=(0, 10))
        wrap(summary)
        self.thread_list = tk.Frame(thread_panel, bg=panel_bg)
        self.thread_list.pack(fill="x")
        self.thread_list.bind("<Configure>", lambda event: self.layout_project_cards(event.width))
        self.empty_projects = label(self.thread_list, "", color=palette.muted,
                                    textvariable=self.text("sessions.empty"), bg=panel_bg, pady=8)
        self.thread_feedback.trace_add("write", lambda *_: summary.pack(
            fill="x", pady=(0, 10), before=self.thread_list) if self.thread_feedback.get()
            else summary.pack_forget())

    def close(self):
        self.dismiss_project()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def toggle_pin(self):
        self.root.attributes("-topmost", self.pinned.get())
        if WINDOWS:
            self.rounded_window.refresh()

    def on_unmap(self, event):
        if event.widget is self.root:
            self.finish_window_drag()
            if WINDOWS:
                self.set_edge_cursor()
            if not self.collapsed and self.root.state() == "iconic":
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
            self.set_task_feedback("todo.read_error")
            return
        if tasks == self.tasks:
            return
        self.tasks = tasks
        self.render_tasks(tasks)

    def render_tasks(self, tasks):
        for child in self.task_list.winfo_children():
            child.destroy()
        self.count.configure(text=self.tr("todo.left", count=sum(not task["done"] for task in tasks)))
        if not tasks:
            empty = RoundedSurface(self.task_list, outside=self.task_list["bg"], radius=13)
            empty.pack(fill="x", pady=(0, 5))
            label(empty, "", bg=self.palette.card, color=self.palette.muted,
                  textvariable=self.text("todo.empty")).pack(
                fill="x", padx=12, pady=8)
        for task in tasks:
            self.show_task(task)

    def show_task(self, task):
        palette = self.palette
        if self.task_list.winfo_children():
            tk.Frame(self.task_list, bg=palette.line, height=1).pack(fill="x")
        surface = tk.Frame(self.task_list, bg=palette.card)
        surface.pack(fill="x")
        row = tk.Frame(surface, bg=palette.card)
        row.pack(fill="x", pady=round(9 * self.scale))
        value = tk.BooleanVar(row, value=task["done"])
        checkbox = tk.Checkbutton(
            row, text=task["text"], variable=value,
            command=lambda: self.change_task(task, done=value.get()),
            font=ui_font(11,
                         "overstrike" if task["done"] else "normal"),
            bg=palette.card, fg=palette.muted if task["done"] else palette.ink,
            activebackground=palette.card, selectcolor=palette.field, anchor="w", justify="left",
            wraplength=235, cursor="hand2",
            highlightthickness=1, highlightbackground=palette.card, highlightcolor=palette.accent)
        text_gap = round(5 * self.scale)
        rounded_indicator(checkbox, self.scale, text_gap=text_gap)
        text_button(row, "", lambda: self.remove_task(task), bg=palette.card, fg=palette.muted,
                    textvariable=self.text("todo.delete"), padx=4).pack(side="right")
        tk.Frame(row, bg=palette.line, width=1, height=14).pack(side="right", padx=4)
        text_button(row, "", lambda: self.edit_task(task), bg=palette.card,
                    textvariable=self.text("todo.edit"),
                    fg=palette.muted, padx=4).pack(
                        side="right")
        checkbox.pack(side="left", fill="x", expand=True)
        wrap(checkbox, 27 + text_gap)

    def task_action(self, operation, *args, **kwargs):
        try:
            operation(*args, **kwargs)
        except (TaskInputError, TaskNotFoundError) as error:
            self.set_task_feedback(error.message_key)
            return False
        except (OSError, sqlite3.Error):
            self.set_task_feedback("todo.write_error")
            return False
        self.set_task_feedback(None)
        self.refresh_tasks()
        return True

    def set_task_feedback(self, key):
        self.task_feedback_key = key
        self.task_feedback.set(self.tr(key) if key else "")

    def add_task(self):
        if self.task_action(self.store.add, self.entry.get()):
            self.entry.delete(0, "end")
        self.entry.focus_set()

    def change_task(self, task, **changes):
        if not self.task_action(self.store.update, task["id"], **changes):
            self.tasks = None
            self.refresh_tasks()

    def edit_task(self, task):
        text = simpledialog.askstring(self.tr("todo.edit_title"), self.tr("todo.edit_prompt"),
                                      initialvalue=task["text"],
                                      parent=self.root)
        if text is not None:
            self.change_task(task, text=text)

    def remove_task(self, task):
        if messagebox.askyesno(self.tr("todo.delete_title"),
                               self.tr("todo.delete_prompt", text=task["text"][:120]),
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
            self.set_thread_feedback("sessions.read_error" if self.threads is None
                                     else "sessions.refresh_error")
            return
        self.update_unread_alert(threads)
        self.threads = threads
        if threads == self.rendered_threads:
            self.set_thread_feedback(None)
        elif self.popup is None:
            self.render_projects()

    def update_unread_alert(self, threads):
        # A missing read-state snapshot makes every session's unread state unknown.
        if threads and all(thread["unread_completed"] is None for thread in threads):
            return
        unread = {thread["id"] for thread in threads if thread["unread_completed"] is True}
        if (self.floating is not None and self.unread_threads is not None
                and unread - self.unread_threads):
            self.floating.start_unread_alert()
        self.unread_threads = unread

    def set_thread_feedback(self, key):
        self.thread_feedback_key = key
        self.thread_feedback.set(self.tr(key) if key else "")

    def render_projects(self):
        if self.threads == self.rendered_threads:
            return
        self.rendered_threads = self.threads
        groups = group_threads(self.threads, project_label=lambda key, name: project_name(key, name, self.tr))
        self.project_groups = {group["key"]: group for group in groups}
        if groups:
            self.empty_projects.grid_remove()
        else:
            self.empty_projects.grid(sticky="w")
        old_cards = self.project_cards
        cards = {}
        for group in groups:
            key = group["key"]
            status = group["status"]
            caption = self.tr(f"project.{status}", count=group.get(status))
            card = old_cards.get(key)
            if card is None:
                card = self.make_project_card(key, group["title"], status, caption)
            else:
                card.update_content(group["title"], status, caption)
            cards[key] = card
        self.project_cards = cards
        for key in old_cards.keys() - cards.keys():
            old_cards[key].destroy()
        if tuple(cards) != tuple(old_cards):
            # Tk traverses sibling widgets in stacking order.
            for card in cards.values():
                tk.Misc.tkraise(card)
            self.layout_project_cards(self.thread_list.winfo_width())
        self.set_thread_feedback(None)

    def make_project_card(self, key, title, status, caption):
        card = ProjectCard(self.thread_list, title, status, caption, self.scale)
        for sequence in ("<Return>", "<space>"):
            card.bind(sequence, lambda _: self.open_project_with_keyboard(card, self.project_groups[key]))
        card.bind("<Enter>", lambda _: self.schedule_project_hover(card, key))
        card.bind("<ButtonRelease-1>", lambda _: self.open_project_under_pointer(card, key))
        return card

    def layout_project_cards(self, width):
        cards = self.project_cards.values()
        if not cards or width < 2:
            return
        height = next(iter(cards)).compact_height()
        columns, card_width, gap = tile_dimensions(width, self.scale, gap=9,
                                                   target=120, maximum=220, column_limit=3)
        for index, card in enumerate(cards):
            row, column = divmod(index, columns)
            card.configure(width=card_width, height=height)
            card.grid(row=row, column=column, padx=(0, gap if column < columns - 1 else 0),
                      pady=(0, gap))

    def schedule_project_hover(self, card, key):
        if self.pending_hover is not None:
            self.root.after_cancel(self.pending_hover)

        def show():
            self.pending_hover = None
            self.open_project_under_pointer(card, key)

        crossing_popup_gap = (
            self.popup is not None and self.popup.uses_outer_edge
            and self.popup.bridges(*self.root.winfo_pointerxy())
        )
        self.pending_hover = self.root.after(290 if crossing_popup_gap else 95, show)

    def open_project_under_pointer(self, card, key):
        pointed = self.root.winfo_containing(*self.root.winfo_pointerxy())
        if self.project_cards.get(key) is card and within(pointed, card):
            self.open_project(card, self.project_groups[key])

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
            self.popup.focus_session(0)
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
            messagebox.showerror(self.tr("session.open_error"), self.tr("session.open_hint"),
                                 parent=self.root)
        else:
            self.root.after(1300, self.refresh_threads)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--background", action="store_true")
    options = parser.parse_args()
    instance = Instance("window")
    activation = None
    try:
        activation = Event("window-activate")
        if not instance.primary:
            if not options.background:
                activation.signal()
            return
        if WINDOWS:
            ctypes.windll.user32.SetProcessDPIAware()
        root = tk.Tk()
        if options.background:
            root.withdraw()
        window = StickyWindow(root)

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
