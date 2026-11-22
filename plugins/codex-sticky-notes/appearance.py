"""Colors and rounded controls for sticky notes."""

import math
import sys
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont

from data import is_finished_and_read
from note_icons import corner_images, icon
from palette import ORANGE

FONT = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"


def ui_font(size, weight="normal"):
    return FONT, size + ORANGE.font_delta, weight


def label(parent, text, *, size=10, color=None, bg=None, weight="normal", **kwargs):
    palette = ORANGE
    return tk.Label(parent, text=text, font=ui_font(size, weight), fg=color or palette.ink,
                    bg=bg or palette.paper, anchor="w", justify="left", **kwargs)


def text_button(parent, text, command, *, bg=None, fg=None, hover_bg=None, **kwargs):
    palette = ORANGE
    bg, fg = bg or palette.paper, fg or palette.accent
    hover_bg = hover_bg or palette.hover
    control = tk.Button(parent, text=text, command=command, font=ui_font(10), bg=bg, fg=fg,
                        activebackground=hover_bg, activeforeground=fg, relief="flat", bd=0,
                        highlightthickness=1, highlightbackground=bg, highlightcolor=palette.accent,
                        cursor="hand2", **kwargs)
    control.bind("<Enter>", lambda _: control.configure(bg=hover_bg))
    control.bind("<Leave>", lambda _: control.configure(bg=bg))
    return control


def rounded_indicator(control, scale, *, on_hero=False, text_gap=0):
    palette = ORANGE
    size = round(17 * scale)
    outline = palette.ink if on_hero else palette.muted
    fill = palette.ink if on_hero else palette.action
    mark = palette.card
    control.configure(
        indicatoron=False, image=icon(control, "ring", size, outline, text_gap=text_gap),
        selectimage=icon(control, "circle", size, fill, checkmark=mark, text_gap=text_gap),
        compound="left", selectcolor=control["bg"], relief="flat", offrelief="flat",
        overrelief="flat", bd=0,
    )


def capsule_switch(parent, text, variable, command, scale):
    palette = ORANGE
    bg = parent["bg"]
    control = tk.Checkbutton(
        parent, text=text, variable=variable, command=command,
        font=ui_font(10), bg=bg, activebackground=bg,
        fg=palette.muted, activeforeground=palette.ink, selectcolor=bg,
        indicatoron=False, bd=0, relief="flat", offrelief="flat", overrelief="flat",
        highlightthickness=1, highlightbackground=bg, highlightcolor=palette.accent,
        compound="right", padx=round(5 * scale), cursor="hand2",
    )
    radius = round(10 * scale)
    width, height = round(38 * scale), 2 * radius
    thumb = icon(control, "circle", height, palette.card)

    def switch_image(track, enabled):
        photo = tk.PhotoImage(master=control, width=width, height=height)
        photo.put(track, to=(radius, 0, width - radius, height))
        positions = ((0, 0), (width - radius, 0), (0, radius), (width - radius, radius))
        for (x, y), corner in zip(positions, corner_images(control, radius, track, track)):
            photo.tk.call(photo, "copy", corner, "-to", x, y)
        photo.tk.call(photo, "copy", thumb, "-to", width - height if enabled else 0, 0)
        return photo

    control.switch_images = (switch_image(palette.scroll_hover, False),
                             switch_image(palette.accent, True))
    control.configure(image=control.switch_images[0], selectimage=control.switch_images[1])
    control.bind("<Return>", lambda _: control.invoke())
    return control


def status_dot(canvas, x, y, scale, color):
    image = icon(canvas, "dot", round(10 * scale), color)
    canvas.create_image(x - round(1.5 * scale), y, anchor="w", image=image)


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


def paint_smooth_rect(canvas, x, y, width, height, radius, fill, border, *, tag="surface"):
    radius = min(round(radius), width // 2, height // 2)
    if radius < 1:
        return
    right, bottom = x + width, y + height

    def band(left, top, right, bottom, color):
        if left < right and top < bottom:
            canvas.create_rectangle(left, top, right, bottom, fill=color, outline="", tags=(tag,))

    # Keep panel height out of the image cache. Only the four arcs need alpha.
    band(x + radius, y, right - radius, bottom, border)
    band(x, y + radius, right, bottom - radius, border)
    band(x + radius, y + 1, right - radius, bottom - 1, fill)
    band(x + 1, y + radius, right - 1, bottom - radius, fill)
    positions = ((x, y), (right - radius, y), (x, bottom - radius),
                 (right - radius, bottom - radius))
    for (left, top), photo in zip(positions, corner_images(canvas, radius, fill, border)):
        canvas.create_image(left, top, image=photo, anchor="nw", tags=(tag,))


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


class RoundedSurface(tk.Frame):
    def __init__(self, parent, *, outside=None, fill=None, radius=14, border=None,
                 antialias=False):
        palette = ORANGE
        outside = outside or palette.paper
        super().__init__(parent, bg=outside)
        self.fill = fill or palette.card
        self.radius = radius
        self.border = border or palette.line
        self.antialias = antialias
        self.canvas = tk.Canvas(self, bg=outside, highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.canvas.bind("<Configure>", lambda _: self.paint())

    def set_border(self, color):
        self.border = color
        self.paint()

    def paint(self):
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self.antialias and min(width, height) > 3:
            paint_smooth_rect(self.canvas, 1, 1, width - 2, height - 2,
                              self.radius, self.fill, self.border)
        elif min(width, height) > 2:
            rounded_rect(self.canvas, 1, 1, width - 2, height - 2,
                         min(self.radius, (width - 2) / 2, (height - 2) / 2),
                         precise=True, fill=self.fill, outline=self.border)


class PillButton(RoundedSurface):
    def __init__(self, parent, text, command, *, outside, radius):
        palette = ORANGE
        self.normal = palette.action
        self.hover = palette.action_hover
        border = palette.action
        super().__init__(parent, outside=outside, fill=self.normal, radius=radius, border=border,
                         antialias=True)
        ink = palette.ink
        self.control = tk.Button(self, text=text, command=command, font=ui_font(9, "bold"),
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


def shorten(text, font, width, *, suffix="…"):
    if font.measure(text) <= width:
        return text
    prefix = ""
    for char in text:
        if font.measure(prefix + char + suffix) > width:
            break
        prefix += char
    return prefix.rstrip() + suffix


def two_line_text(text, font, width, *, prefer_word_break=False, full_first_line=False):
    text = " ".join(text.split())
    if font.measure(text) <= width:
        return text
    suffix = "" if full_first_line else "…"
    first = shorten(text, font, width, suffix=suffix).removesuffix(suffix)
    if text[len(first):].startswith("-") and font.measure(first + "-") <= width:
        first += "-"
    # Prefer a space or hyphen near the right edge over breaking a Latin word.
    boundary = max(first.rfind(" "), first.rfind("-")) + 1
    split = text[max(0, len(first) - 1):len(first) + 1]
    prefer_boundary = not full_first_line or (split.isascii() and split == split.strip())
    if boundary and prefer_boundary and (
        boundary >= len(first) * 0.65
        or (prefer_word_break and font.measure(text[boundary:].lstrip()) <= width)
    ):
        first = first[:boundary]
    rest = text[len(first):].lstrip()
    # Keep a single trailing ideograph with its neighbors when the second line has room.
    if (full_first_line and len(rest) == 1 and len(first) > 2
            and all("\u3400" <= char <= "\u9fff" for char in first[-2:] + rest)):
        first, rest = first[:-2], first[-2:] + rest
    return first.rstrip() + "\n" + shorten(rest, font, width)


class ProjectCard(tk.Canvas):
    FOLDER_BACKGROUNDS = {
        "unread": "#F9C66F",
        "running": "#8FCCAA",
        "read": "#EBC8C9",
        "unknown": "#BDC1E2",
    }

    def __init__(self, parent, title, status, caption, scale):
        self.palette = ORANGE
        super().__init__(parent, bg=parent["bg"], bd=0, highlightthickness=0, width=1, height=1,
                         cursor="hand2", takefocus=True)
        self.title = title
        self.status = status
        self.caption = caption
        self.scale = scale
        self.selected = False
        self.focused = False
        self.title_font = tkfont.Font(self, font=ui_font(10, "bold"))
        self.small_font = tkfont.Font(self, font=ui_font(8))
        self.padding = round(7 * scale)
        self.folder_size = round(32 * scale)
        self.badge_height = self.small_font.metrics("linespace") + round(4 * scale)
        self.title_badge_gap = max(1, round(3 * scale))
        self.bind("<Configure>", lambda _: self.paint())
        self.bind("<FocusIn>", lambda _: self.set_focus(True))
        self.bind("<FocusOut>", lambda _: self.set_focus(False))

    def set_focus(self, active):
        self.focused = active
        self.paint()

    def set_selected(self, active):
        self.selected = active
        self.paint()

    def update_content(self, title, status, caption):
        content = title, status, caption
        if content != (self.title, self.status, self.caption):
            self.title, self.status, self.caption = content
            self.paint()

    def compact_height(self):
        text_height = (2 * self.title_font.metrics("linespace")
                       + self.title_badge_gap + self.badge_height)
        return max(self.folder_size, text_height) + 2 * self.padding

    def paint(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if min(width, height) <= 2:
            return
        palette = self.palette
        border, ink = palette.project_colors[self.status]
        paper, hover = palette.status_backgrounds[self.status]
        surface = hover if self.selected else paper
        s = self.scale
        radius = round(palette.tile_radius * s)
        outline = ink if self.focused or self.selected else border
        paint_smooth_rect(self, 1, 1, width - 2, height - 2, radius, surface, outline)

        folder_left, folder_size = round(5 * s), self.folder_size
        folder_top = (height - folder_size) // 2
        folder_bg = self.FOLDER_BACKGROUNDS[self.status]
        paint_smooth_rect(self, folder_left, folder_top, folder_size, folder_size,
                          round(8 * s), folder_bg, folder_bg, tag="folder-background")
        folder = icon(self, "folder", round(22 * s), palette.ink)
        self.create_image(folder_left + folder_size // 2, folder_top + folder_size // 2,
                          image=folder, tags=("project-folder",))

        text_left = folder_left + folder_size + round(7 * s)
        text_width = width - text_left - round(2 * s)
        name = two_line_text(self.title, self.title_font, text_width, prefer_word_break=True)
        title_height = (name.count("\n") + 1) * self.title_font.metrics("linespace")
        text_height = title_height + self.title_badge_gap + self.badge_height
        title_top = (height - text_height) // 2
        self.create_text(text_left, title_top, text=name, anchor="nw", font=self.title_font,
                         fill=palette.ink, tags=("project-title",))
        badge_center = title_top + text_height - self.badge_height / 2
        self.paint_status_badge(text_left, badge_center, text_width, surface, border, ink)

    def paint_status_badge(self, left, center, width, fill, border, ink):
        s = self.scale
        text_offset = round(18 * s)
        padding = text_offset + round(7 * s)
        caption = shorten(self.caption, self.small_font, width - padding)
        right = left + padding + self.small_font.measure(caption)
        radius = self.badge_height / 2
        paint_smooth_rect(self, left, round(center - radius), right - left,
                          self.badge_height, radius, fill, border, tag="status-badge")
        status_dot(self, left + round(6 * s), center, s, ink)
        self.create_text(left + text_offset, center, text=caption, anchor="w",
                         font=self.small_font, fill=ink)


class SessionCard(tk.Canvas):
    @staticmethod
    def metadata(thread, tr):
        status = "unread_completed" if thread["unread_completed"] else thread["status"]
        caption = tr(f"status.{status}")
        when = datetime.fromtimestamp(thread["updated"] / 1000).strftime("%m-%d %H:%M")
        return caption, when

    def __init__(self, parent, thread, title, metadata, scale, title_font, detail_font, command):
        self.palette = palette = ORANGE
        super().__init__(parent, bg=palette.card, bd=0, highlightthickness=0, width=1, height=1,
                         cursor="hand2", takefocus=True)
        self.title = title
        self.caption, self.when = metadata
        status = thread["status"]
        self.status_ink = palette.status_colors.get(status, palette.muted)
        self.border = palette.line
        if thread["unread_completed"]:
            state = "unread"
        elif status == "running":
            state = "running"
        elif is_finished_and_read(thread):
            state = "read"
        else:
            state = "unknown"
        if state in {"unread", "running"} or status in {"stale", "unknown"}:
            self.border, self.status_ink = palette.project_colors[state]
        self.fill, self.hover_fill = palette.status_backgrounds[state]
        self.scale = scale
        self.title_font = title_font
        self.detail_font = detail_font
        self.padding = round(7 * scale)
        self.metadata_gap = round(4 * scale)
        self.chat_size = round(9 * scale)
        self.icon_left = round(5 * scale)
        self.status_x = self.icon_left + self.chat_size + round(scale)
        self.time_inset = round(4 * scale)
        self.status_time_gap = round(2 * scale)
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

    def compact_height(self):
        return (2 * self.padding + 2 * self.title_font.metrics("linespace")
                + self.metadata_gap + self.detail_font.metrics("linespace"))

    def metadata_width(self, caption, when):
        return (self.status_x + self.detail_font.measure(caption) + self.status_time_gap
                + self.detail_font.measure(when) + self.time_inset)

    def paint(self):
        self.delete("all")
        card_width, height = self.winfo_width(), self.winfo_height()
        if min(card_width, height) <= 2:
            return
        s = self.scale
        palette = self.palette
        pad = self.padding
        radius = round((palette.tile_radius - 3) * s)
        surface = self.hover_fill if self.hovered else self.fill
        outline = palette.accent if self.hovered or self.focused else self.border
        paint_smooth_rect(self, 1, 1, card_width - 2, height - 2, radius, surface, outline)
        text_pad = round(6 * s)
        name = two_line_text(self.title, self.title_font, card_width - 2 * text_pad,
                             full_first_line=True)
        self.create_text(text_pad, pad, text=name, anchor="nw", font=self.title_font,
                         fill=palette.ink, tags=("session-title",))

        metadata_y = height - pad - self.detail_font.metrics("linespace") // 2
        chat = icon(self, "chat", self.chat_size, self.status_ink)
        self.create_image(self.icon_left, metadata_y, anchor="w", image=chat, tags=("session-icon",))
        status_width = card_width - self.metadata_width("", self.when)
        self.create_text(self.status_x, metadata_y, anchor="w", font=self.detail_font,
                         text=shorten(self.caption, self.detail_font, status_width),
                         fill=self.status_ink, tags=("session-status",))
        self.create_text(card_width - self.time_inset, metadata_y, text=self.when, anchor="e", font=self.detail_font,
                         fill=palette.muted, tags=("session-time",))
