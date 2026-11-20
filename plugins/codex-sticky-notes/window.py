"""Single-page Windows sticky notes."""

import argparse
import ctypes
import os
import sqlite3
import sys
import time
import tkinter as tk
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import PureWindowsPath
from tkinter import messagebox, simpledialog, ttk
from tkinter import font as tkfont
from urllib.parse import quote

from appearance import (
    ACCENT, CARD, FIELD, FONT, HERO, INK, LINE, MUTED, PAPER, PROJECT_COLORS,
    PillButton, ProjectCard, RoundedSurface, SessionCard, label, note_mark, paint_hills,
    rounded_rect, text_button, two_line_text, wrap,
)
from data import TaskStore, group_threads, read_project_threads
from lifecycle import Event, Instance

TRANSPARENT = "#ff00fe"


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


def work_area(widget):
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
    parts = PureWindowsPath(path).parts
    peers = [tuple(part.casefold() for part in PureWindowsPath(other).parts)
             for other in others if other != path]
    for length in range(1, len(parts) + 1):
        suffix = tuple(part.casefold() for part in parts[-length:])
        if all(peer[-length:] != suffix for peer in peers):
            return str(PureWindowsPath(*parts[-length:]))
    return path


def layout_tiles(cards, width, scale, *, gap, target, maximum, column_limit):
    if width < 2:
        return
    gap = round(gap * scale)
    target = round(target * scale)
    columns = max(1, min(column_limit, (width + gap) // (target + gap)))
    side = min(round(maximum * scale), (width - gap * (columns - 1)) // columns)
    for index, card in enumerate(cards):
        row, column = divmod(index, columns)
        card.configure(width=side, height=side)
        card.grid(row=row, column=column, padx=(0, gap if column < columns - 1 else 0),
                  pady=(0, gap))


class FloatingNote(tk.Toplevel):
    def __init__(self, root, restore):
        super().__init__(root)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.67)
        self.title("打开 Codex 便签")
        self.attributes("-transparentcolor", TRANSPARENT)

        self.size = round(54 * self.winfo_fpixels("1i") / 96)
        self.face = tk.Canvas(self, width=self.size, height=self.size, bg=TRANSPARENT,
                              highlightthickness=0, cursor="hand2", takefocus=True)
        self.face.pack()
        self.face.bind("<Enter>", lambda _: self.set_hover(True))
        self.face.bind("<Leave>", lambda _: self.set_hover(False))
        self.face.bind("<ButtonRelease-1>", lambda _: restore())
        self.face.bind("<Return>", lambda _: restore())
        self.face.bind("<space>", lambda _: restore())
        self.set_hover(False)

    def set_hover(self, hovered):
        self.attributes("-alpha", 0.97 if hovered else 0.67)
        canvas = self.face
        size = self.size
        canvas.delete("all")
        rounded_rect(canvas, 2, 2, size - 2, size - 2, size * 0.30,
                     fill=ACCENT if hovered else "#668571",
                     outline="#cbdac1", width=1)
        note_mark(canvas, 0, 0, size / 58, "#fffaf5")

    def show(self, x, y):
        self.geometry(f"{self.size}x{self.size}{x:+d}{y:+d}")
        self.set_hover(False)
        self.deiconify()
        self.lift()


class ScrollPage(tk.Frame):
    def __init__(self, parent, *, bg=PAPER, padding=(20, 18)):
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
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(
            self.content, width=event.width))
        self.winfo_toplevel().bind("<MouseWheel>", self.scroll, add="+")

    def scroll(self, event):
        if within(event.widget, self):
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

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
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", TRANSPARENT)
        self.configure(bg=TRANSPARENT)
        self.anchor = anchor
        self.scale = scale
        self.anchor_box = None
        self.content_width = None
        self.links = {}
        self.project_title = group["title"]
        self.project_path = group["subtitle"]
        self.title_font = tkfont.Font(self, family=FONT, size=12, weight="bold")
        self.path_font = tkfont.Font(self, family=FONT, size=8)
        card_title_font = tkfont.Font(self, family=FONT, size=10, weight="bold")
        shell = RoundedSurface(self, outside=TRANSPARENT, radius=17, border="#c5c9b5")
        shell.pack(fill="both", expand=True)
        self.header = tk.Frame(shell, bg=CARD)
        self.header.pack(fill="x", padx=13, pady=(11, 3))
        title_row = tk.Frame(self.header, bg=CARD)
        title_row.pack(fill="x")
        status_color = PROJECT_COLORS[group["status"]][3]
        self.count = label(title_row, f"{len(group['threads'])} 个会话", size=9,
                           color=status_color, bg=CARD)
        self.count.pack(side="right", padx=(8, 0))
        self.title_label = label(title_row, "", weight="bold", size=12, bg=CARD)
        self.title_label.pack(side="left", fill="x", expand=True)
        self.path_label = None
        if self.project_path:
            self.path_label = label(self.header, "", size=8, color=MUTED, bg=CARD)
            self.path_label.pack(fill="x", pady=(2, 0))
        tk.Frame(self.header, bg=LINE, height=1).pack(fill="x", pady=(7, 0))
        self.update_idletasks()
        self.page = ScrollPage(shell, bg=CARD, padding=(self.TILE_PADDING, 0))
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
        if box == self.anchor_box:
            return
        self.anchor_box = box
        left, top, right, bottom = work_area(self.anchor)
        x0, y0, x1, y1 = box
        gap = round(8 * self.scale)
        columns = min(3, len(self.links))
        preferred = round(min(428, 34 + 130 * columns + 8 * (columns - 1)) * self.scale)
        min_width = min(preferred, round(245 * self.scale))
        space_left, space_right = x0 - left - gap, right - x1 - gap
        root_left, _, root_right, _ = screen_box(self.anchor.winfo_toplevel())
        # Prefer the closest window edge so the popup covers fewer neighboring tiles.
        use_right = x0 + x1 >= root_left + root_right
        if (space_right if use_right else space_left) < min_width:
            use_right = space_right >= space_left
        side_space = space_right if use_right else space_left
        max_height = min(bottom - top, round(448 * self.scale))
        if side_space >= min_width:
            width = min(preferred, side_space)
            x = x1 + gap if use_right else x0 - width - gap
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
            layout_tiles(self.links.values(), tile_width, self.scale,
                         gap=8, target=98, maximum=134, column_limit=columns)
            self.update_idletasks()
        height = min(max_height, self.header.winfo_reqheight() + self.page.body.winfo_reqheight() + 25)
        if side_space >= min_width:
            y = min(max(top, y0), bottom - height)
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
    def __init__(self, root, store=None, thread_reader=read_project_threads, *, preview=False):
        self.root = root
        self.store = store or TaskStore()
        self.thread_reader = thread_reader
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.tasks = None
        self.threads = None
        self.rendered_threads = None
        self.project_cards = {}
        self.popup = None
        self.hover_timer = None
        self.pending_hover = None
        self.pointer_left_at = None
        self.keyboard_popup = False
        self.floating = None
        self.collapsed = False
        self.task_feedback = tk.StringVar()
        self.thread_feedback = tk.StringVar(value="正在读取本机会话…")
        self.pinned = tk.BooleanVar(value=False)
        root.title("Codex 便签 · 方块预览" if preview else "Codex 便签")
        self.scale = root.winfo_fpixels("1i") / 96
        left, top, right, bottom = work_area(root)
        width = min(round(510 * self.scale), right - left - 55)
        height = min(round(700 * self.scale), bottom - top - 70)
        x = left + max(20, (right - left - width - round(428 * self.scale)) // 2)
        y = top + (bottom - top - height) // 2
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(round(355 * self.scale), round(380 * self.scale))
        root.configure(bg=PAPER)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Unmap>", self.on_unmap)
        root.bind("<Escape>", self.escape_project)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Note.Vertical.TScrollbar", background="#c8c8ae", troughcolor=PAPER,
                        bordercolor=PAPER, lightcolor=PAPER, darkcolor=PAPER, arrowsize=0,
                        width=8, gripcount=0)
        style.map("Note.Vertical.TScrollbar", background=[("active", "#899b82")])

        self.make_header()
        self.page = ScrollPage(root)
        self.page.pack(fill="both", expand=True, padx=(0, 6))
        self.make_tasks(self.page.body)
        self.make_threads(self.page.body)
        self.refresh_tasks()
        self.refresh_threads()
        root.after(15000, self.tick)

    def make_header(self):
        hero = RoundedSurface(self.root, fill=HERO, radius=20, border="#cfdac6")
        hero.pack(fill="x", padx=(20, 20), pady=(14, 0))
        top = tk.Frame(hero, bg=HERO)
        top.pack(fill="x", padx=14, pady=12)
        size = round(46 * self.scale)
        logo = tk.Canvas(top, width=size, height=size, bg=HERO, highlightthickness=0)
        logo.pack(side="left", padx=(0, 10))
        rounded_rect(logo, 1, 1, size - 2, size - 2, size * 0.3,
                     fill=CARD, outline="#cbd7c2")
        note_mark(logo, 0, 1, size / 60, ACCENT)
        window_icon = tk.PhotoImage(master=self.root, width=24, height=24)
        for color, bounds in (
            (ACCENT, (2, 2, 22, 22)), (CARD, (7, 5, 17, 19)),
            (ACCENT, (9, 9, 15, 10)), (ACCENT, (9, 12, 14, 13)),
        ):
            window_icon.put(color, to=bounds)
        self.root.iconphoto(True, window_icon)
        label(top, "Codex 便签", size=17, weight="bold", bg=HERO).pack(side="left")
        self.collapse_button = PillButton(top, "收起", self.collapse, outside=HERO)
        self.collapse_button.pack(side="right", padx=(5, 0))
        pin = tk.Checkbutton(top, text="置顶", variable=self.pinned, command=self.toggle_pin,
                             font=(FONT, 9), bg=HERO, fg=INK, activebackground=HERO,
                             activeforeground=INK, selectcolor=CARD, cursor="hand2", padx=0,
                             highlightthickness=1, highlightbackground=HERO, highlightcolor=ACCENT)
        pin.pack(side="right")
        hills = tk.Canvas(top, width=1, height=round(44 * self.scale), bg=HERO,
                          highlightthickness=0)
        hills.pack(side="left", fill="both", expand=True, padx=7)
        hills.bind("<Configure>", lambda _: paint_hills(hills))

    def make_tasks(self, parent):
        task_panel = tk.Frame(parent, bg=PAPER)
        task_panel.pack(fill="x")
        heading = tk.Frame(task_panel, bg=PAPER)
        heading.pack(fill="x", pady=(0, 9))
        label(heading, "待办", size=14, weight="bold").pack(side="left")
        self.count = label(heading, "", color=MUTED, size=9)
        self.count.pack(side="right")

        entry_row = tk.Frame(task_panel, bg=PAPER)
        entry_row.pack(fill="x", pady=(0, 8))
        add_button = PillButton(entry_row, "添加待办", self.add_task, primary=True)
        add_button.pack(side="right", padx=(8, 0))
        entry_shell = RoundedSurface(entry_row, fill=FIELD, radius=14)
        entry_shell.pack(side="left", fill="both", expand=True)
        self.entry = tk.Entry(entry_shell, font=(FONT, 10), bg=FIELD, fg=INK,
                              relief="flat", bd=0, highlightthickness=0, insertbackground=INK)
        self.entry.pack(fill="both", expand=True, padx=12, pady=5)
        self.entry.bind("<Return>", lambda _: self.add_task())
        self.entry.bind("<FocusIn>", lambda _: entry_shell.set_border(ACCENT))
        self.entry.bind("<FocusOut>", lambda _: entry_shell.set_border(LINE))
        self.task_list = tk.Frame(task_panel, bg=PAPER)
        self.task_list.pack(fill="x")
        feedback = label(task_panel, "", textvariable=self.task_feedback, color=MUTED, size=9)
        self.task_feedback.trace_add("write", lambda *_: feedback.pack(fill="x")
                                     if self.task_feedback.get() else feedback.pack_forget())
        wrap(feedback)

    def make_threads(self, parent):
        thread_panel = tk.Frame(parent, bg=PAPER)
        thread_panel.pack(fill="x", pady=(13, 0))
        tk.Frame(thread_panel, height=1, bg=LINE).pack(fill="x", pady=(0, 12))
        heading = tk.Frame(thread_panel, bg=PAPER)
        heading.pack(fill="x", pady=(0, 5))
        label(heading, "项目会话", size=14, weight="bold").pack(side="left")
        PillButton(heading, "刷新", self.refresh_threads).pack(side="right")
        summary = label(thread_panel, "", textvariable=self.thread_feedback, color=MUTED, size=9)
        summary.pack(fill="x", pady=(0, 10))
        wrap(summary)
        self.thread_list = tk.Frame(thread_panel, bg=PAPER)
        self.thread_list.pack(fill="x")
        self.thread_list.bind("<Configure>", lambda event: self.layout_project_cards(event.width))

    def close(self):
        self.dismiss_project()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def toggle_pin(self):
        self.root.attributes("-topmost", self.pinned.get())

    def on_unmap(self, event):
        if event.widget is self.root and not self.collapsed and self.root.state() == "iconic":
            self.root.after_idle(self.collapse)

    def collapse(self):
        if self.collapsed:
            return
        self.dismiss_project()
        self.floating = FloatingNote(self.root, self.restore)
        self.collapsed = True
        self.root.withdraw()
        width = self.root.winfo_vrootwidth()
        height = self.root.winfo_vrootheight()
        size = self.floating.size
        self.floating.show(max(0, width - size - 23), min(140, max(0, height - size - 20)))

    def restore(self):
        if not self.collapsed:
            return
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
            self.task_feedback.set("暂时无法读取本地待办。")
            return
        if tasks == self.tasks:
            return
        self.tasks = tasks
        for child in self.task_list.winfo_children():
            child.destroy()
        self.count.configure(text=f"{sum(not task['done'] for task in tasks)} 项未完成")
        if not tasks:
            empty = RoundedSurface(self.task_list, radius=13)
            empty.pack(fill="x", pady=(0, 5))
            label(empty, "还没有待办", bg=CARD, color=MUTED).pack(
                fill="x", padx=12, pady=8)
        for task in tasks:
            self.show_task(task)

    def show_task(self, task):
        surface = RoundedSurface(self.task_list, radius=13)
        surface.pack(fill="x", pady=(0, 5))
        row = tk.Frame(surface, bg=CARD)
        row.pack(fill="x", padx=9, pady=4)
        value = tk.BooleanVar(row, value=task["done"])
        checkbox = tk.Checkbutton(
            row, text=task["text"], variable=value,
            command=lambda: self.change_task(task, done=value.get()),
            font=(FONT, 10, "overstrike" if task["done"] else "normal"),
            bg=CARD, fg=MUTED if task["done"] else INK, activebackground=CARD,
            selectcolor=FIELD, anchor="w", justify="left", wraplength=235, cursor="hand2",
            highlightthickness=1, highlightbackground=CARD, highlightcolor=ACCENT)
        checkbox.value = value
        text_button(row, "删除", lambda: self.remove_task(task), bg=CARD, fg=MUTED,
                    padx=4).pack(side="right")
        text_button(row, "编辑", lambda: self.edit_task(task), bg=CARD, padx=4).pack(side="right")
        checkbox.pack(side="left", fill="x", expand=True)
        wrap(checkbox, 27)

    def task_action(self, operation, *args, **kwargs):
        try:
            operation(*args, **kwargs)
        except (ValueError, KeyError) as error:
            self.task_feedback.set(error.args[0])
            return False
        except (OSError, sqlite3.Error):
            self.task_feedback.set("保存失败，请重试。")
            return False
        self.task_feedback.set("已保存到本机")
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
        self.threads = threads
        if threads == self.rendered_threads:
            self.show_thread_summary()
        elif self.popup is None:
            self.render_projects()

    def show_thread_summary(self):
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
            label(self.thread_list, "没有找到本机会话", color=MUTED, pady=8).grid(sticky="w")
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
        card = ProjectCard(self.thread_list, group["title"], hint, status, summaries[status],
                           self.scale)
        for sequence in ("<Return>", "<space>"):
            card.bind(sequence, lambda _: self.open_project_with_keyboard(card, group))
        card.bind("<Enter>", lambda _: self.schedule_project_hover(card, group))
        card.bind("<ButtonRelease-1>", lambda _: self.open_project_under_pointer(card, group))
        self.project_cards[group["key"]] = card

    def layout_project_cards(self, width):
        layout_tiles(self.project_cards.values(), width, self.scale,
                     gap=11, target=104, maximum=145, column_limit=6)

    def schedule_project_hover(self, card, group):
        if self.pending_hover is not None:
            self.root.after_cancel(self.pending_hover)

        def show():
            self.pending_hover = None
            self.open_project_under_pointer(card, group)

        self.pending_hover = self.root.after(95, show)

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
            os.startfile("codex://threads/" + quote(thread_id, safe=""))
        except OSError:
            messagebox.showerror("打开会话失败", "Windows 无法打开 Codex 会话链接。",
                                 parent=self.root)
        else:
            self.root.after(1300, self.refresh_threads)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--background", action="store_true")
    mode.add_argument("--preview", action="store_true")
    options = parser.parse_args()
    name = "hover-preview" if options.preview else "window"
    activation = Event(f"{name}-activate")
    instance = Instance(name)
    if not instance.primary:
        if not options.background:
            activation.signal()
        activation.close()
        return
    if sys.platform == "win32":
        ctypes.windll.user32.SetProcessDPIAware()
    try:
        root = tk.Tk()
        if options.background:
            root.withdraw()
        window = StickyWindow(root, preview=options.preview)

        def check_activation():
            if activation.wait():
                window.restore()
                root.deiconify()
                root.lift()
                root.focus_force()
            root.after(250, check_activation)

        if options.background:
            root.after_idle(window.collapse)
        root.after(250, check_activation)
        root.mainloop()
    finally:
        activation.close()
        instance.close()


if __name__ == "__main__":
    main()
