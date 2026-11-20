"""Colors and rounded controls for the Windows notes."""

import math
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont

from data import STATUS_LABELS
from note_icons import icon
from palette import palette_for

FONT = "Microsoft YaHei UI"


def label(parent, text, *, size=10, color=None, bg=None, weight="normal", **kwargs):
    palette = palette_for(parent)
    return tk.Label(parent, text=text, font=(FONT, size, weight), fg=color or palette.ink,
                    bg=bg or palette.paper, anchor="w", justify="left", **kwargs)


def text_button(parent, text, command, *, bg=None, fg=None, **kwargs):
    palette = palette_for(parent)
    bg, fg = bg or palette.paper, fg or palette.accent
    control = tk.Button(parent, text=text, command=command, font=(FONT, 10), bg=bg, fg=fg,
                        activebackground=palette.hover, activeforeground=fg, relief="flat", bd=0,
                        highlightthickness=1, highlightbackground=bg, highlightcolor=palette.accent,
                        cursor="hand2", **kwargs)
    control.bind("<Enter>", lambda _: control.configure(bg=palette.hover))
    control.bind("<Leave>", lambda _: control.configure(bg=bg))
    return control


def rounded_indicator(control, scale, *, on_hero=False):
    palette = palette_for(control)
    size = round(22 * scale)
    outline = palette.ink if on_hero else "#966747"
    fill = palette.ink if on_hero else palette.action
    mark = palette.card if on_hero else palette.ink
    control.configure(
        indicatoron=False, image=icon(control, "ring", size, outline),
        selectimage=icon(control, "circle", size, fill, checkmark=mark),
        compound="left", selectcolor=control["bg"], relief="flat", offrelief="flat",
        overrelief="flat", bd=0,
    )


def status_dot(canvas, x, y, scale, color, *, smooth):
    if smooth:
        image = icon(canvas, "dot", round(10 * scale), color)
        canvas.create_image(x - round(1.5 * scale), y, anchor="w", image=image)
    else:
        radius = round(3 * scale)
        canvas.create_oval(x, y - radius, x + 2 * radius, y + radius, fill=color, outline="")


def wrap(widget, padding=4):
    widget.bind("<Configure>", lambda event: widget.configure(
        wraplength=max(70, event.width - padding)))


def rounded_rect(canvas, x1, y1, x2, y2, radius, *, precise=False, **options):
    if precise:
        corners = (
            (x2 - radius, y1 + radius, -90), (x2 - radius, y2 - radius, 0),
            (x1 + radius, y2 - radius, 90), (x1 + radius, y1 + radius, 180),
        )
        points = []
        for x, y, start in corners:
            for angle in range(start, start + 91, 10):
                radians = math.radians(angle)
                points.extend((x + radius * math.cos(radians), y + radius * math.sin(radians)))
        return canvas.create_polygon(points, **options)
    points = (x1, y1 + radius, x1, y1, x1 + radius, y1, x2 - radius, y1,
              x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2,
              x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius)
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **options)


def note_mark(canvas, x, y, scale, color):
    def point(a, b):
        return x + a * scale, y + b * scale

    canvas.create_line(*point(18, 12), *point(36, 12), *point(43, 19),
                       *point(43, 40), *point(18, 40), *point(18, 12),
                       fill=color, width=2.1 * scale, joinstyle="round")
    canvas.create_line(*point(36, 12), *point(36, 19), *point(43, 19),
                       fill=color, width=1.65 * scale, joinstyle="round")
    for end, baseline in ((36, 27), (32, 33)):
        canvas.create_line(*point(24, baseline), *point(end, baseline),
                           fill=color, width=1.65 * scale, capstyle="round")


def paint_hills(canvas):
    canvas.delete("all")
    width, height = canvas.winfo_width(), canvas.winfo_height()
    if width < 52:
        return
    scale = min(width / 94, height / 44)
    offset_x = (width - 94 * scale) / 2
    offset_y = (height - 44 * scale) / 2

    def points(*coordinates):
        return [offset + coordinate * scale for offset, coordinate in zip(
            (offset_x, offset_y) * (len(coordinates) // 2), coordinates)]

    canvas.create_oval(*points(63, 2, 79, 18), fill="#e8c887", outline="")
    canvas.create_polygon(*points(3, 36, 16, 23, 32, 17, 46, 19, 59, 28, 75, 31,
                                 92, 40, 65, 42, 23, 42),
                          smooth=True, splinesteps=20, fill="#c9dcce", outline="")
    canvas.create_polygon(*points(9, 40, 31, 36, 47, 32, 62, 21, 75, 21, 87, 32,
                                 93, 40, 74, 44, 22, 44),
                          smooth=True, splinesteps=20, fill="#b8ceb2", outline="")
    canvas.create_line(*points(22, 13, 32, 13), fill="#f8f6ec", width=2 * scale, capstyle="round")


class RoundedSurface(tk.Frame):
    def __init__(self, parent, *, outside=None, fill=None, radius=14, border=None):
        palette = palette_for(parent)
        outside = outside or palette.paper
        super().__init__(parent, bg=outside)
        self.fill = fill or palette.card
        self.radius = radius
        self.border = border or palette.line
        self.precise_corners = palette.precise_corners
        self.canvas = tk.Canvas(self, bg=outside, highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.canvas.bind("<Configure>", lambda _: self.paint())

    def set_border(self, color):
        self.border = color
        self.paint()

    def paint(self):
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if min(width, height) > 2:
            rounded_rect(self.canvas, 1, 1, width - 2, height - 2,
                         min(self.radius, (width - 2) / 2, (height - 2) / 2),
                         precise=self.precise_corners, fill=self.fill, outline=self.border)


class PillButton(RoundedSurface):
    def __init__(self, parent, text, command, *, outside=None, primary=False):
        palette = palette_for(parent)
        self.normal = palette.action if primary else palette.card
        self.hover = palette.action_hover if primary else palette.hover
        border = self.normal if primary else palette.line
        super().__init__(parent, outside=outside, fill=self.normal, radius=20, border=border)
        ink = palette.action_ink if primary else palette.accent
        self.control = tk.Button(self, text=text, command=command, font=(FONT, 9, "bold"),
                                 bg=self.normal, fg=ink, activebackground=self.hover,
                                 activeforeground=ink, relief="flat", bd=0,
                                 highlightthickness=0, cursor="hand2")
        self.control.pack(padx=11, pady=4)
        for widget in (self.canvas, self.control):
            widget.bind("<Enter>", lambda _: self.highlight(True))
            widget.bind("<Leave>", lambda _: self.highlight(False))
        self.canvas.configure(cursor="hand2")
        self.canvas.bind("<ButtonRelease-1>", self.release_padding)
        self.control.bind("<FocusIn>", lambda _: self.set_border(palette.accent))
        self.control.bind("<FocusOut>", lambda _: self.set_border(border))
        self.control.bind("<Return>", lambda _: self.invoke())

    def highlight(self, active):
        self.fill = self.hover if active else self.normal
        self.control.configure(bg=self.fill)
        self.paint()

    def release_padding(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def invoke(self):
        return self.control.invoke()


def shorten(text, font, width):
    if font.measure(text) <= width:
        return text
    prefix = ""
    for char in text:
        if font.measure(prefix + char + "…") > width:
            break
        prefix += char
    return prefix.rstrip() + "…"


def two_line_text(text, font, width):
    text = " ".join(text.split())
    if font.measure(text) <= width:
        return text
    first = shorten(text, font, width)[:-1]
    if text[len(first):].startswith("-") and font.measure(first + "-") <= width:
        first += "-"
    # Prefer a space or hyphen near the right edge over breaking a Latin word.
    boundary = max(first.rfind(" "), first.rfind("-")) + 1
    if boundary >= len(first) * 0.65:
        first = first[:boundary]
    return first.rstrip() + "\n" + shorten(text[len(first):].lstrip(), font, width)


class ProjectCard(tk.Canvas):
    def __init__(self, parent, title, hint, status, caption, scale):
        self.palette = palette_for(parent)
        super().__init__(parent, bg=self.palette.paper, bd=0, highlightthickness=0, width=1, height=1,
                         cursor="hand2", takefocus=True)
        self.title = title
        self.hint = hint
        self.status = status
        self.caption = caption
        self.scale = scale
        self.selected = False
        self.focused = False
        self.title_font = tkfont.Font(self, family=FONT, size=10, weight="bold")
        self.small_font = tkfont.Font(self, family=FONT, size=8)
        self.bind("<Configure>", lambda _: self.paint())
        self.bind("<FocusIn>", lambda _: self.set_focus(True))
        self.bind("<FocusOut>", lambda _: self.set_focus(False))

    def set_focus(self, active):
        self.focused = active
        self.paint()

    def set_selected(self, active):
        self.selected = active
        self.paint()

    def paint(self):
        self.delete("all")
        side = self.winfo_width()
        if side <= 2:
            return
        palette = self.palette
        paper, hover, border, ink = palette.project_colors[self.status]
        pad = round(13 * self.scale)
        title_top = round(36 * self.scale)
        radius = round(palette.tile_radius * self.scale)
        rounded_rect(self, 1, 1, side - 2, side - 2, radius,
                     precise=palette.precise_corners,
                     fill=hover if self.selected else paper,
                     outline=ink if self.focused or self.selected else border)
        x, y, s = pad, round(14 * self.scale), self.scale
        if palette.precise_corners:
            folder = icon(self, "folder", round(25 * s), ink)
            self.create_image(x - round(2 * s), y - round(4 * s), anchor="nw", image=folder)
        else:
            self.create_line(x, y + 13 * s, x, y + 2 * s, x + 6 * s, y + 2 * s,
                             x + 9 * s, y + 5 * s, x + 20 * s, y + 5 * s, x + 20 * s, y + 15 * s,
                             x, y + 15 * s, x, y + 13 * s, fill=ink, width=1.4 * s,
                             joinstyle="round", capstyle="round")
        width = side - 2 * pad
        if self.hint:
            hint_width = width - round(27 * s)
            self.create_text(side - pad, y + round(9 * s),
                             text=shorten(self.hint, self.small_font, hint_width),
                             anchor="e", font=self.small_font, fill=palette.muted)
        name = two_line_text(self.title, self.title_font, width)
        self.create_text(pad, title_top, text=name, anchor="nw", font=self.title_font, fill=palette.ink)
        bottom = side - round(17 * s)
        status_dot(self, pad, bottom, s, ink, smooth=palette.precise_corners)
        self.create_text(pad + round(12 * s), bottom, text=self.caption, anchor="w",
                         font=self.small_font, fill=ink)


class SessionCard(tk.Canvas):
    def __init__(self, parent, thread, scale, title_font, detail_font, command):
        self.palette = palette = palette_for(parent)
        super().__init__(parent, bg=palette.card, bd=0, highlightthickness=0, width=1, height=1,
                         cursor="hand2", takefocus=True)
        self.title = thread["title"]
        self.progress = thread["progress"]
        self.when = datetime.fromtimestamp(thread["updated"] / 1000).strftime("%m-%d %H:%M")
        status = thread["status"]
        self.caption = "完成待查看" if thread["unread_completed"] else STATUS_LABELS[status]
        self.status_ink = palette.status_colors.get(status, palette.muted)
        self.fill, self.hover_fill, self.border = palette.field, palette.hover, palette.line
        if thread["unread_completed"]:
            self.fill, self.hover_fill, self.border, self.status_ink = palette.project_colors["unread"]
        elif status == "running":
            self.fill, self.hover_fill, self.border, self.status_ink = palette.project_colors["running"]
        self.scale = scale
        self.title_font = title_font
        self.detail_font = detail_font
        self.command = command
        self.hovered = False
        self.focused = False
        self.bind("<Configure>", lambda _: self.paint())
        self.bind("<Enter>", lambda _: self.set_hover(True))
        self.bind("<Leave>", lambda _: self.set_hover(False))
        self.bind("<FocusIn>", lambda _: self.set_focus(True))
        self.bind("<FocusOut>", lambda _: self.set_focus(False))
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<Return>", lambda _: self.invoke())
        self.bind("<space>", lambda _: self.invoke())

    def invoke(self):
        self.command()
        return "break"

    def release(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            return self.invoke()

    def set_hover(self, active):
        self.hovered = active
        self.paint()

    def set_focus(self, active):
        self.focused = active
        self.paint()

    def paint(self):
        self.delete("all")
        side = self.winfo_width()
        if side <= 2:
            return
        s = self.scale
        palette = self.palette
        pad = round(10 * s)
        width = side - 2 * pad
        rounded_rect(self, 1, 1, side - 2, side - 2, round((palette.tile_radius - 3) * s),
                     precise=palette.precise_corners,
                     fill=self.hover_fill if self.hovered else self.fill,
                     outline=palette.accent if self.hovered or self.focused else self.border)
        status_y = round(16 * s)
        status_dot(self, pad, status_y, s, self.status_ink, smooth=palette.precise_corners)
        self.create_text(pad + round(10 * s), status_y, anchor="w", font=self.detail_font,
                         text=self.caption, fill=self.status_ink)

        title_top = round(29 * s)
        name = two_line_text(self.title, self.title_font, width)
        self.create_text(pad, title_top, text=name, anchor="nw", font=self.title_font, fill=palette.ink)
        bottom = side - round(9 * s)
        self.create_text(pad, bottom, text=self.when, anchor="sw", font=self.detail_font,
                         fill=palette.muted)

        detail_line = self.detail_font.metrics("linespace")
        detail_top = title_top + (name.count("\n") + 1) * self.title_font.metrics("linespace")
        detail_top += round(3 * s)
        lines = (bottom - detail_line - round(3 * s) - detail_top) // detail_line
        if self.progress and lines > 0:
            excerpt = self.progress if len(self.progress) <= 112 else self.progress[:112] + "…"
            excerpt = " ".join(excerpt.split())
            preview = (two_line_text(excerpt, self.detail_font, width) if lines >= 2
                       else shorten(excerpt, self.detail_font, width))
            self.create_text(pad, detail_top, text=preview, anchor="nw",
                             font=self.detail_font, fill=palette.muted)
