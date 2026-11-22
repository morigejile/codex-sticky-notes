"""Interactive Windows smoke test with temporary tasks and sample sessions."""

import sys
import tempfile
import time
import tkinter as tk
from ctypes import byref, c_int, wintypes
from tkinter import font as tkfont
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "codex-sticky-notes"))
from appearance import PillButton
from data import TaskStore, group_threads
from i18n import load_language, save_language
from native_frame import WS_CAPTION, gdi32, set_window_bounds, user32, window_style
from palette import ORANGE
from window import StickyWindow, screen_box, work_area


def until(root, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError("Windows 界面条件未满足。")


def center(widget):
    widget.update_idletasks()
    return (widget.winfo_rootx() + widget.winfo_width() // 2,
            widget.winfo_rooty() + widget.winfo_height() // 2)


def pause(root, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.015)


def check_scroll_corners(canvas, inset):
    user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE)
    user32.GetWindowRgn.restype = c_int
    gdi32.PtInRegion.argtypes = (wintypes.HANDLE, c_int, c_int)
    gdi32.PtInRegion.restype = wintypes.BOOL
    region = gdi32.CreateRectRgn(0, 0, 0, 0)
    try:
        assert user32.GetWindowRgn(canvas.winfo_id(), region) != 0
        width, height = canvas.winfo_width(), canvas.winfo_height()
        assert gdi32.PtInRegion(region, inset + 1, 1)
        assert gdi32.PtInRegion(region, width // 2, height - 2)
        assert not gdi32.PtInRegion(region, inset + 1, height - 2)
        assert not gdi32.PtInRegion(region, width - inset - 2, height - 2)
    finally:
        gdi32.DeleteObject(region)


def check_antialiased_corners(canvas, tag):
    corners = [item for item in canvas.find_withtag(tag) if canvas.type(item) == "image"]
    assert len(corners) == 4
    for item, (right, bottom) in zip(corners, [(False, False), (True, False),
                                               (False, True), (True, True)]):
        photo = canvas.itemcget(item, "image")
        size = int(canvas.tk.call("image", "width", photo))
        x, y = size - 1 if right else 0, size - 1 if bottom else 0
        assert canvas.tk.getboolean(canvas.tk.call(photo, "transparency", "get", x, y))


def check_window_overlay(widget, rounded_window):
    bounds = wintypes.RECT()
    assert user32.IsWindowVisible(rounded_window.overlay)
    assert user32.GetWindowRect(rounded_window.overlay, byref(bounds))
    assert (bounds.left, bounds.top, bounds.right, bounds.bottom) == screen_box(widget)


def widget_text(widget):
    variable = widget["textvariable"]
    return widget.getvar(variable) if variable else widget["text"]


def check_session_footer(card):
    status, = card.find_withtag("session-status")
    when, = card.find_withtag("session-time")
    assert card.itemcget(status, "text") == card.caption
    assert card.itemcget(when, "text") == card.when
    assert card.bbox(status)[2] <= card.bbox(when)[0]
    status_x, y = card.coords(status)
    time_x, time_y = card.coords(when)
    assert y == time_y
    return (status_x + card.winfo_width() - time_x + round(2 * card.scale)
            + card.detail_font.measure(card.caption) + card.detail_font.measure(card.when))


def check_large_project(window, thread):
    root = window.root
    threads = [dict(thread, id=f"large-{index}", title=f"示例会话 {index}", status="completed",
                    updated=thread["updated"] - index, unread_completed=index == 299,
                    unread=index == 299) for index in range(300)]
    group, = group_threads(threads)
    card = window.project_cards[thread["project_key"]]
    try:
        window.open_project_with_keyboard(card, group)
        popup = window.popup
        assert len(popup.links) < 40
        assert "large-299" not in popup.links
        first = popup.links["large-0"]
        until(root, lambda: root.focus_get() is first)
        first.event_generate("<Tab>")
        until(root, lambda: root.focus_get() is popup.links["large-1"])
        popup.links["large-1"].event_generate("<Shift-Tab>")
        until(root, lambda: root.focus_get() is first)
        first.event_generate("<Shift-Tab>")
        until(root, lambda: "large-299" in popup.links and root.focus_get() is popup.links["large-299"])
        last = popup.links["large-299"]
        assert check_session_footer(first) < first.winfo_width() == last.winfo_width()
        assert check_session_footer(last) == last.winfo_width()
        assert screen_box(last)[3] <= screen_box(popup.page.canvas)[3]
        last.event_generate("<Tab>")
        until(root, lambda: root.focus_get() is first)

        window.dismiss_project()
        window.open_project_with_keyboard(card, group)
        popup = window.popup
        popup.page.canvas.yview_moveto(1)
        until(root, lambda: "large-299" in popup.links and popup.links["large-299"].winfo_viewable())
        assert "large-150" not in popup.links
        assert len(popup.links) < 80
        last = popup.links["large-299"]
        with (patch("launch.os.startfile") as startfile,
              patch.object(window, "refresh_threads", wraps=window.refresh_threads) as refresh_threads):
            last.event_generate("<ButtonRelease-1>", x=12, y=12)
            startfile.assert_called_once_with("codex://threads/large-299")
            until(root, lambda: refresh_threads.called and window.pending is None)
        assert window.popup is None

        left, _, right, _ = screen_box(root)
        _, top, _, bottom = work_area(root)
        for side_width, columns in ((360, 2), (235, 1)):
            area = left, top, right + round(side_width * window.scale), bottom
            with patch("window.work_area", return_value=area):
                window.open_project_with_keyboard(card, group)
                popup = window.popup
                assert popup.columns == columns
                first = popup.links["large-0"]
                next_row = popup.links[f"large-{columns}"]
                canvas = popup.page.canvas
                x0, y0 = canvas.coords(first.window_item)
                x1, y1 = canvas.coords(next_row.window_item)
                assert x0 == x1 and y1 > y0
            window.dismiss_project()
    finally:
        window.dismiss_project()


def check_languages(store, threads, settings):
    root = tk.Tk()
    window = StickyWindow(root, store, lambda: threads, settings_path=settings)
    try:
        until(root, lambda: window.threads is not None and window.thread_list.winfo_ismapped())
        header = root.winfo_children()[0].winfo_children()[0]
        title = next(child for child in header.winfo_children() if isinstance(child, tk.Label))
        art = next(child for child in header.winfo_children() if isinstance(child, tk.Canvas))
        header_height = header.winfo_height()
        title_size = tkfont.Font(root, font=title["font"]).cget("size")
        window.entry.insert(0, "保留草稿")
        window.entry.icursor(2)
        window.language_menu.invoke(2)
        until(root, lambda: root.title() == "Codex Sticky Notes")
        assert header.winfo_height() == header_height
        assert tkfont.Font(root, font=title["font"]).cget("size") == title_size == 16
        assert screen_box(title)[2] <= screen_box(window.pin_control)[0]
        assert abs(center(title)[1] - center(window.pin_control)[1]) <= 1
        assert window.pin_control.master.master is header
        close_button = next(child for child in window.pin_control.master.winfo_children()
                            if isinstance(child, tk.Button) and widget_text(child) == "Close")
        assert screen_box(close_button)[2] <= screen_box(art)[0]
        x, y, _, _ = screen_box(root)
        narrow_width = root.minsize()[0]
        set_window_bounds(root, x, y, narrow_width, root.winfo_height())
        until(root, lambda: root.winfo_width() <= narrow_width + 24)
        assert screen_box(window.pin_control)[1] >= screen_box(title)[3]
        assert tkfont.Font(root, font=title["font"]).cget("size") == title_size
        assert load_language(settings) == "en"
        assert window.entry.get() == "保留草稿" and window.entry.index("insert") == 2
        assert widget_text(window.collapse_button) == "Collapse"
        assert widget_text(window.task_freeze_switch) == "Pin tasks"
        assert window.count["text"] == "0 left"
        assert window.project_cards["one"].title == "示例应用"
        group = next(group for group in group_threads(window.threads) if group["key"] == "one")
        assert window.project_cards["one"].caption == f"To review {group['unread']}"
        for control in (window.pin_control, window.collapse_button, window.language_menu.master,
                        close_button, window.task_freeze_switch, window.count):
            assert control.winfo_viewable() and control.winfo_width() >= control.winfo_reqwidth()
            assert screen_box(control)[2] <= screen_box(root)[2]
        window.open_project_with_keyboard(window.project_cards["one"], group)
        root.update_idletasks()
        assert window.popup.count["text"] == f"{len(group['threads'])} sessions"
        assert window.popup.links["running"].caption == "To review"
        assert window.popup.links["running"].title == "检查新版本"
        for card in window.popup.links.values():
            if card.winfo_viewable():
                assert card.bbox("session-status")[2] < card.winfo_width()
        window.language_menu.invoke(1)
        until(root, lambda: root.title() == "Codex 便签")
        assert screen_box(window.pin_control)[1] >= screen_box(title)[3]
        assert load_language(settings) == "zh-CN"
        assert window.entry.get() == "保留草稿"
        assert widget_text(window.task_freeze_switch) == "固定待办"
        assert window.project_cards["one"].caption == f"待查看 {group['unread']}"
        window.language_menu.invoke(2)
    finally:
        window.close()

    root = tk.Tk()
    window = StickyWindow(root, store, lambda: threads, settings_path=settings)
    try:
        until(root, lambda: window.threads is not None)
        assert root.title() == "Codex Sticky Notes"
        assert widget_text(window.collapse_button) == "Collapse"
    finally:
        window.close()


def check_window(store):
    now = int(time.time() * 1000)
    long_session_title = "整理会话进展和显示方式以及窗口布局的详细记录" * 2
    threads = [
        dict(id="one", title=f"示例应用 · {long_session_title}", updated=now - 30,
             status="completed", unread_completed=True, unread=True,
             project_key="one", project="示例应用",
             project_path="D:/One"),
        dict(id="running", title="检查新版本", updated=now,
             status="running", unread_completed=False, unread=False,
             project_key="one", project="示例应用", project_path="D:/One"),
        dict(id="two", title="核对物流页面", updated=now - 20,
             status="running", unread_completed=False, unread=False,
             project_key="two", project="示例项目的近期会话与进度整理" * 6,
             project_path="D:/Two"),
        dict(id="read", title="归纳资料", updated=now - 60,
             status="completed", unread_completed=False, unread=False,
             project_key="read", project="expression-trainer-pro", project_path="D:/Read"),
        dict(id="unknown", title="核对进度", updated=now - 75,
             status="stale", unread_completed=False, unread=None,
             project_key="unknown", project="expression-trainer-pro", project_path="D:/Unknown"),
    ]
    older_ids = [f"older-{index}" for index in range(24)]
    older_statuses = {"older-0": ("failed", False), "older-1": ("completed", None),
                      "older-2": ("interrupted", False)}
    older_titles = {"older-0": "其他项目 · 迁移到示例应用",
                    "older-1": "检查示例应用的设置", "older-2": "示例应用 ·",
                    "older-3": "项目悬停 demo (4)", "older-4": "制作 Mac 版便签小工具",
                    "older-5": "生成子标签页面设计图"}
    for index, thread_id in enumerate(older_ids):
        status, unread = older_statuses.get(thread_id, ("completed", False))
        threads.append(dict(threads[0], id=thread_id,
                            title=older_titles.get(thread_id, f"较早的会话 {index + 1}"),
                            updated=now - 100 - index, status=status, unread=unread,
                            unread_completed=False))
    root = tk.Tk()
    root.attributes("-topmost", True)
    settings = store.file.with_name("settings.json")
    save_language(settings, "zh-CN")
    window = StickyWindow(root, store, lambda: threads, settings_path=settings)
    cursor = (-1, -1)
    pointer = patch.object(root, "winfo_pointerxy", side_effect=lambda: cursor)
    pointer.start()

    def point_at(widget):
        nonlocal cursor
        cursor = center(widget)
        widget.event_generate("<Enter>", x=widget.winfo_width() // 2,
                              y=widget.winfo_height() // 2)

    def resize(width, height):
        x, y, _, _ = screen_box(root)
        set_window_bounds(root, x, y, width, height)

    try:
        until(root, lambda: window.threads is not None and window.thread_list.winfo_ismapped())
        palette = ORANGE
        assert root.title() == "Codex 便签"
        assert window.palette.paper == palette.paper
        assert root["bg"] == palette.paper
        assert not window_style(root) & WS_CAPTION
        assert window.rounded_window.shape is not None
        _, bounds = window.rounded_window.shape
        assert bounds[:2] == (0, 0)
        check_window_overlay(root, window.rounded_window)
        old_x, old_y, _, _ = screen_box(root)
        masthead = root.winfo_children()[0]
        masthead.event_generate("<ButtonPress-1>", x=200, y=40)
        masthead.event_generate("<B1-Motion>", x=227, y=51)
        masthead.event_generate("<ButtonRelease-1>", x=227, y=51)
        until(root, lambda: root.winfo_rootx() == old_x + 27)
        assert root.winfo_rooty() == old_y + 11
        check_window_overlay(root, window.rounded_window)
        set_window_bounds(root, old_x, old_y, root.winfo_width(), root.winfo_height())
        until(root, lambda: screen_box(root)[:2] == (old_x, old_y))
        assert window.hero_image.width() == round(64 * window.scale)
        top = masthead.winfo_children()[0]
        title = next((child for child in top.winfo_children() if isinstance(child, tk.Label)), None)
        assert title is not None
        art = next(child for child in top.winfo_children() if isinstance(child, tk.Canvas))
        close_button = next(child for child in window.pin_control.master.winfo_children()
                            if isinstance(child, tk.Button) and widget_text(child) == "关闭")
        assert close_button["bg"] == ORANGE.hero
        window.collapse_button.event_generate("<Enter>")
        assert window.collapse_button["bg"] == ORANGE.hero_border
        assert window.collapse_button["activebackground"] == ORANGE.hero_border
        window.collapse_button.event_generate("<Leave>")
        assert window.collapse_button["bg"] == ORANGE.hero
        assert title.winfo_rootx() < window.pin_control.winfo_rootx() < art.winfo_rootx()
        actions_left, _, actions_right, _ = screen_box(window.pin_control.master)
        assert round(12 * window.scale) <= actions_left - screen_box(title)[2] <= round(24 * window.scale)
        assert screen_box(art)[0] - actions_right >= round(12 * window.scale)
        assert abs(center(title)[1] - center(window.pin_control)[1]) <= 1
        assert not int(window.pin_control["indicatoron"])
        assert window.pin_control["image"] and window.pin_control["selectimage"]
        controls = (window.pin_control, window.collapse_button, window.language_menu.master, close_button)
        assert all(screen_box(left)[2] <= screen_box(right)[0] for left, right in zip(controls, controls[1:]))
        assert len({center(control)[1] for control in controls}) == 1
        assert window.thread_list["bg"] == ORANGE.card
        assert window.entry_hint.winfo_ismapped() and not window.entry.get()
        assert window.entry.master.winfo_height() >= round(35 * window.scale)
        entry_shell = window.entry.master
        add_button = next(child for child in entry_shell.master.winfo_children()
                          if isinstance(child, PillButton))
        assert tkfont.Font(root, font=add_button.control["font"]).cget("size") == 8
        for panel, caption in ((window.task_list.master, "待办"),
                               (window.thread_list.master, "项目会话")):
            left, _, right, _ = screen_box(root)
            panel_left, _, panel_right, _ = screen_box(panel.master)
            assert panel_left - left == right - panel_right == round(13 * window.scale)
            panel_title = next(child for row in panel.winfo_children() for child in row.winfo_children()
                               if isinstance(child, tk.Label) and widget_text(child) == caption)
            assert tkfont.Font(root, font=panel_title["font"]).cget("size") == 13
        for surface in (entry_shell, add_button, window.task_list.master.master,
                        window.thread_list.master.master):
            check_antialiased_corners(surface.canvas, "surface")
        assert tkfont.Font(root, font=window.entry["font"]).cget("size") == 10
        assert not window.thread_feedback.get()
        assert window.task_list.winfo_ismapped()
        assert window.task_list.winfo_rooty() < window.thread_list.winfo_rooty()
        window.entry.insert(0, "复核本周测试结果")
        window.add_task()
        assert len(store.list()) == 1
        task_surface = window.task_list.winfo_children()[0]
        root.update_idletasks()
        assert task_surface.winfo_height() >= round(41 * window.scale)
        task_row = next(child for child in task_surface.winfo_children()
                        if isinstance(child, tk.Frame))
        checkbox = next(child for child in task_row.winfo_children()
                        if isinstance(child, tk.Checkbutton))
        assert not int(checkbox["indicatoron"])
        assert checkbox["image"] and checkbox["selectimage"]
        indicator_width = int(root.tk.call("image", "width", checkbox["image"]))
        assert int(root.tk.call("image", "height", checkbox["image"])) == round(17 * window.scale)
        pin_image = window.pin_control["image"]
        pin_size = int(root.tk.call("image", "height", pin_image))
        assert pin_size == round(17 * window.scale)
        assert int(root.tk.call("image", "width", pin_image)) == pin_size + round(3 * window.scale)
        assert indicator_width == pin_size + round(5 * window.scale)
        checkbox.invoke()
        assert store.list()[0]["done"]

        assert list(window.project_cards) == ["one", "two", "read", "unknown"]
        one, two, read, unknown = window.project_cards.values()
        assert screen_box(title)[0] == screen_box(one)[0]
        assert read.title == unknown.title == "expression-trainer-pro"
        for card in (read, unknown):
            texts = [card.itemcget(item, "text") for item in card.find_all() if card.type(item) == "text"]
            assert texts == ["expression-\ntrainer-pro", card.caption]
        assert len({card.status for card in (one, two, read, unknown)}) == 4
        for card in window.project_cards.values():
            check_antialiased_corners(card, "surface")
            check_antialiased_corners(card, "status-badge")
            check_antialiased_corners(card, "folder-background")
            corners = [item for item in card.find_withtag("folder-background") if card.type(item) == "image"]
            left, top, _, _ = card.bbox(corners[0])
            _, _, right, bottom = card.bbox(corners[-1])
            assert right - left == bottom - top == round(32 * window.scale)
            icon, = card.find_withtag("project-folder")
            image = card.itemcget(icon, "image")
            assert int(root.tk.call("image", "width", image)) == round(22 * window.scale)
            expected = ("#AEE1BC", "#F7EEEA", "#FFD77D", "#D5D8EF")
            index = ("running", "read", "unread", "unknown").index(card.status)
            for tag in ("surface", "status-badge"):
                fills = [card.itemcget(item, "fill") for item in card.find_withtag(tag)
                         if card.type(item) == "rectangle"]
                assert fills[-1].upper() == expected[index]
                if tag == "status-badge":
                    assert fills[0] == ORANGE.project_colors[card.status][0]
        assert one.winfo_rootx() < two.winfo_rootx() < read.winfo_rootx()
        assert one.winfo_rooty() == two.winfo_rooty() == read.winfo_rooty()
        assert unknown.winfo_rooty() > one.winfo_rooty()
        assert unknown.winfo_rootx() == one.winfo_rootx()
        assert screen_box(read)[2] <= screen_box(window.thread_list)[2]
        assert one.winfo_height() < one.winfo_width()
        assert all(card.winfo_height() == one.winfo_height() for card in window.project_cards.values())
        for card, line_count in ((one, 1), (two, 2)):
            title_item, = card.find_withtag("project-title")
            assert card.itemcget(title_item, "text").count("\n") + 1 == line_count
            _, folder_top, folder_right, folder_bottom = card.bbox("folder-background")
            title_left, title_top, title_right, title_bottom = card.bbox(title_item)
            badge_left, badge_top, badge_right, badge_bottom = card.bbox("status-badge")
            assert folder_right < title_left <= badge_left
            assert title_left - folder_right >= round(5 * window.scale)
            assert title_top < folder_bottom and folder_top < title_bottom
            assert badge_top > title_bottom
            assert badge_bottom < card.winfo_height()
            assert max(title_right, badge_right) < card.winfo_width()
        assert one.title_font.cget("size") == 9 and one.small_font.cget("size") == 7
        width = root.winfo_width()
        middle = root.winfo_height() // 2
        edge = round(10 * window.scale)
        window.page.canvas.event_generate("<Leave>", rootx=root.winfo_rootx() + width - edge,
                                          rooty=root.winfo_rooty() + middle)
        assert root["cursor"] == "size_we"
        root.event_generate("<ButtonPress-1>", x=width - edge, y=middle)
        assert root.grab_current() is root
        root.event_generate("<B1-Motion>", x=width + 30, y=middle)
        assert root["cursor"] == "size_we"
        root.event_generate("<ButtonRelease-1>", x=width + 30, y=middle)
        assert root.grab_current() is None
        until(root, lambda: root.winfo_width() > width)
        root.event_generate("<Motion>", x=width // 2, y=middle)
        assert root["cursor"] != "size_we"
        resize(width, root.winfo_height())
        until(root, lambda: abs(root.winfo_width() - width) <= 3)
        original_width, original_height = root.winfo_width(), root.winfo_height()
        left, _, right, _ = work_area(root)
        assert original_width == min(round(460 * window.scale), right - left - 55)
        assert screen_box(window.page.bar)[2] <= screen_box(root)[2] - round(12 * window.scale)
        resize(root.minsize()[0], original_height)
        until(root, lambda: read.winfo_rooty() > one.winfo_rooty())
        assert two.winfo_rooty() == one.winfo_rooty()
        assert read.winfo_rootx() == one.winfo_rootx()
        assert title.winfo_ismapped() and close_button.winfo_ismapped() and art.winfo_ismapped()
        assert screen_box(controls[0])[1] >= screen_box(title)[3]
        assert screen_box(controls[-1])[2] <= screen_box(root)[2]
        resize(original_width, original_height)
        until(root, lambda: read.winfo_rooty() == one.winfo_rooty())
        canvas = window.page.canvas
        bottom_inset = round(13 * window.scale)
        resize(original_width, root.minsize()[1])
        until(root, lambda: canvas.yview()[1] < 1)
        assert screen_box(root)[3] - screen_box(canvas)[3] == bottom_inset
        canvas.yview_moveto((1 - canvas.yview()[1]) / 2)
        until(root, lambda: 0 < canvas.yview()[0] < canvas.yview()[1] < 1)
        check_scroll_corners(canvas, int(window.page.body["padx"]))
        canvas.yview_moveto(1)
        until(root, lambda: canvas.yview()[1] == 1)
        assert screen_box(root)[3] - screen_box(canvas)[3] == bottom_inset
        assert screen_box(unknown)[3] <= screen_box(canvas)[3]
        resize(original_width, original_height)
        canvas.yview_moveto(0)
        root.update()
        resize(root.minsize()[0], root.minsize()[1])
        until(root, lambda: canvas.yview()[1] < 1)
        window.entry.insert(0, "未保存的待办")
        window.task_freeze_switch.invoke()
        until(root, lambda: window.entry.winfo_viewable() and canvas.yview()[1] < 1)
        left, _, right, _ = screen_box(root)
        task_left, _, task_right, _ = screen_box(window.fixed_task_host)
        assert task_left - left == right - task_right == bottom_inset
        task_y = window.entry.winfo_rooty()
        project_y = one.winfo_rooty()
        one.event_generate("<MouseWheel>", delta=-120)
        until(root, lambda: one.winfo_rooty() < project_y)
        assert window.entry.winfo_rooty() == task_y
        assert window.entry.get() == "未保存的待办"

        overflow_tasks = [store.add(f"滚动测试待办 {index}") for index in range(8)]
        window.refresh_tasks()
        task_canvas = window.fixed_task_rows.canvas
        until(root, lambda: task_canvas.yview()[1] < 1)
        project_scroll = canvas.yview()
        window.task_list.event_generate("<MouseWheel>", delta=-120)
        until(root, lambda: task_canvas.yview()[0] > 0)
        assert canvas.yview() == project_scroll
        for task in overflow_tasks:
            store.delete(task["id"])
        window.refresh_tasks()

        window.task_freeze_switch.invoke()
        until(root, lambda: window.entry.winfo_viewable() and canvas.yview()[0] == 0)
        assert window.entry.get() == "未保存的待办"
        window.entry.delete(0, "end")
        task_y = window.entry.winfo_rooty()
        one.event_generate("<MouseWheel>", delta=-120)
        until(root, lambda: window.entry.winfo_rooty() < task_y)
        resize(original_width, original_height)
        canvas.yview_moveto(0)
        root.update()
        point_at(window.entry)
        until(root, lambda: window.popup is None)

        original_threads = threads
        threads = [dict(thread, title="刷新后的标题", updated=now + 1)
                   if thread["id"] == "read" else thread for thread in threads]
        window.refresh_threads()
        until(root, lambda: window.threads == threads)
        assert list(window.project_cards) == ["read", "one", "two", "unknown"]
        assert window.project_cards["read"] is read
        assert window.project_cards["one"] is one
        assert read.winfo_rootx() < one.winfo_rootx()
        assert read.tk_focusNext() is one
        point_at(read)
        until(root, lambda: window.popup is not None and window.popup.winfo_viewable())
        assert window.popup.links["read"].title == "刷新后的标题"
        assert window.popup.path_label["text"] == "D:/Read"
        solo = window.popup.links["read"]
        single_width = solo.winfo_width()
        assert check_session_footer(solo) == single_width < read.winfo_width()
        assert window.popup.winfo_width() <= single_width + round(35 * window.scale)
        point_at(window.entry)
        until(root, lambda: window.popup is None)
        threads = original_threads
        window.refresh_threads()
        until(root, lambda: window.threads == threads)

        point_at(one)
        until(root, lambda: window.popup is not None and window.popup.winfo_viewable())
        popup = window.popup
        assert popup.anchor is one
        assert popup.links["one"]["bg"] == palette.card
        assert list(popup.links) == ["running", "one", *older_ids][:len(popup.links)]
        first, second = popup.links["running"], popup.links["one"]
        third, fourth = popup.links["older-0"], popup.links["older-1"]
        assert first.title == "检查新版本"
        assert second.title == long_session_title
        for thread_id, title in older_titles.items():
            assert popup.links[thread_id].title == title
        demo = popup.links["older-3"]
        demo_title, = demo.find_withtag("session-title")
        assert demo.itemcget(demo_title, "text").replace("\n", " ") == older_titles["older-3"]
        mac = popup.links["older-4"]
        mac_title, = mac.find_withtag("session-title")
        assert mac.itemcget(mac_title, "text").startswith("制作 Mac 版")
        design = popup.links["older-5"]
        design_title, = design.find_withtag("session-title")
        lines = design.itemcget(design_title, "text").splitlines()
        assert "".join(lines) == older_titles["older-5"] and len(lines[-1]) >= 2
        check_window_overlay(popup, popup.rounded_window)
        overlay = popup.rounded_window.overlay
        expected = {"running": "#AEE1BC", "one": "#FFD77D", "older-0": "#F7EEEA",
                    "older-1": "#D5D8EF", "older-2": "#F7EEEA", "older-3": "#F7EEEA"}
        for thread_id, fill in expected.items():
            link = popup.links[thread_id]
            assert link.fill == fill
            link.set_hover(False)
            fills = [link.itemcget(item, "fill") for item in link.find_withtag("surface")
                     if link.type(item) == "rectangle"]
            assert fills[-1] == fill
        check_antialiased_corners(first, "surface")
        assert first.winfo_height() < first.winfo_width()
        for card, line_count in ((first, 1), (second, 2)):
            title, = card.find_withtag("session-title")
            icon_box = card.bbox("session-icon")
            assert card.itemcget(title, "text").count("\n") + 1 == line_count
            status_box = card.bbox("session-status")
            time_box = card.bbox("session-time")
            assert status_box[1] < icon_box[3] and icon_box[1] < status_box[3]
            assert status_box[1] == time_box[1]
            assert status_box[2] <= time_box[0]
            assert card.bbox(title)[3] < time_box[1]
            assert time_box[3] < card.winfo_height()
        assert second.winfo_width() == first.winfo_width()
        assert first.winfo_width() > single_width
        painted = [card for card in popup.links.values() if card.find_withtag("session-status")]
        assert first.winfo_width() == max(check_session_footer(card) for card in painted)
        assert popup.winfo_width() < root.winfo_width()
        assert first.winfo_height() == second.winfo_height() == third.winfo_height()
        assert first.winfo_rooty() == second.winfo_rooty() == third.winfo_rooty()
        assert first.winfo_rootx() < second.winfo_rootx() < third.winfo_rootx()
        assert screen_box(first)[3] < fourth.winfo_rooty()
        assert first.winfo_rootx() == fourth.winfo_rootx()
        assert first.bbox("session-time")[2] == second.bbox("session-time")[2]
        assert (popup.winfo_rootx() >= one.winfo_rootx() + one.winfo_width()
                or popup.winfo_rootx() + popup.winfo_width() <= one.winfo_rootx())
        left, _, right, _ = work_area(one)
        root_left, _, root_right, _ = screen_box(root)
        if max(root_left - left, right - root_right) >= round(253 * window.scale):
            popup_left, _, popup_right, _ = screen_box(popup)
            assert popup_right <= root_left or popup_left >= root_right
        if popup.winfo_rootx() >= one.winfo_rootx() + one.winfo_width():
            gap_x = (one.winfo_rootx() + one.winfo_width() + popup.winfo_rootx()) // 2
        else:
            gap_x = (popup.winfo_rootx() + popup.winfo_width() + one.winfo_rootx()) // 2
        gap_y = max(one.winfo_rooty(), popup.winfo_rooty()) + 5
        cursor = gap_x, gap_y
        pause(root, 0.35)
        assert window.popup is popup
        point_at(second)
        pause(root, 0.4)
        assert window.popup is popup
        second.event_generate("<MouseWheel>", delta=-120)
        until(root, lambda: popup.page.canvas.yview()[0] > 0)
        threads = [dict(thread, unread_completed=False, unread=False) for thread in threads]
        window.refresh_threads()
        until(root, lambda: window.threads == threads)
        assert window.popup is popup
        point_at(window.entry)
        until(root, lambda: window.popup is None)
        assert not user32.IsWindowVisible(overlay)
        one, two, read, _ = window.project_cards.values()
        assert one.status == two.status != read.status

        point_at(two)
        until(root, lambda: window.popup is not None and window.popup.winfo_viewable())
        assert window.popup.anchor is two
        popup = window.popup
        link = popup.links["two"]
        assert link.winfo_rooty() + link.winfo_height() <= popup.winfo_rooty() + popup.winfo_height()
        with patch("launch.os.startfile") as startfile:
            link.event_generate("<ButtonRelease-1>", x=12, y=12)
            startfile.assert_called_once_with("codex://threads/two")
        assert window.popup is None

        window.collapse_button.invoke()
        until(root, lambda: window.floating is not None and window.floating.winfo_viewable())
        assert root.state() == "withdrawn"
        assert not user32.IsWindowVisible(window.rounded_window.overlay)
        check_window_overlay(window.floating, window.floating.rounded_window)
        face = window.floating.face

        def indicator_state():
            return face.itemcget("unread-indicator", "state")

        assert indicator_state() == "hidden"

        # A new session becomes unread while the note is collapsed.
        threads = [
            dict(thread, unread=False, unread_completed=False) if thread["id"] == "one"
            else dict(thread, status="completed", unread=True, unread_completed=True)
            if thread["id"] == "running" else thread
            for thread in threads
        ]
        window.refresh_threads()
        until(root, lambda: indicator_state() == "normal")
        until(root, lambda: indicator_state() == "hidden")
        until(root, lambda: indicator_state() == "normal")
        assert window.floating.UNREAD_ALERT_MS == 3_600_000
        original_expiry = window.floating.alert_expiry
        assert original_expiry is not None
        threads = [dict(thread, unread=False, unread_completed=False)
                   if thread["id"] == "running" else thread for thread in threads]
        window.refresh_threads()
        until(root, lambda: window.pending is None)
        assert window.floating.alert_timer is not None
        assert window.floating.alert_expiry == original_expiry

        with patch.object(window.floating, "UNREAD_ALERT_MS", 250):
            threads = [dict(thread, unread=True, unread_completed=True)
                       if thread["id"] == "one" else thread for thread in threads]
            window.refresh_threads()
            until(root, lambda: window.pending is None)
            assert window.floating.alert_expiry not in (None, original_expiry)
            assert original_expiry not in root.tk.splitlist(root.tk.call("after", "info"))
        until(root, lambda: window.floating.alert_timer is None)
        assert indicator_state() == "hidden"

        face.event_generate("<Leave>")
        idle_alpha = float(window.floating.attributes("-alpha"))
        face.event_generate("<Enter>")
        assert 0 < idle_alpha < float(window.floating.attributes("-alpha")) < 1
        until(root, lambda: window.floating.tooltip.winfo_viewable())
        assert window.floating.rounded_window.shape is not None
        assert window.floating.art.width() == round(window.floating.size * 0.85)
        face.event_generate("<Leave>")
        until(root, lambda: not window.floating.tooltip.winfo_viewable())
        x0, y0, _, _ = screen_box(window.floating)
        face.event_generate("<ButtonPress-1>", x=20, y=20)
        face.event_generate("<B1-Motion>", x=-24, y=35)
        face.event_generate("<ButtonRelease-1>", x=20, y=20)
        until(root, lambda: window.floating is not None
              and window.floating.winfo_rootx() < x0 - 20)
        moved = screen_box(window.floating)[:2]
        assert moved[1] > y0
        check_window_overlay(window.floating, window.floating.rounded_window)
        face.event_generate("<ButtonPress-1>", x=20, y=20)
        face.event_generate("<ButtonRelease-1>", x=20, y=20)
        until(root, lambda: root.state() == "normal" and window.floating is None)

        root.iconify()
        until(root, lambda: window.floating is not None and window.floating.winfo_viewable())
        assert screen_box(window.floating)[:2] == moved
        until(root, lambda: window.pending is None)
        face = window.floating.face
        threads = [dict(thread, unread=True, unread_completed=True)
                   if thread["id"] == "running" else thread for thread in threads]
        window.refresh_threads()
        until(root, lambda: indicator_state() == "normal")
        alert_timers = (window.floating.alert_timer, window.floating.alert_expiry)
        assert all(alert_timers)
        window.restore()
        until(root, lambda: root.state() == "normal" and window.floating is None)
        assert not set(alert_timers).intersection(root.tk.splitlist(root.tk.call("after", "info")))
        until(root, lambda: window.pending is None)
        assert not window_style(root) & WS_CAPTION
        assert window.rounded_window.shape is not None
        check_window_overlay(root, window.rounded_window)
        check_large_project(window, threads[0])

        default_card_width = one.winfo_width()
        default_card_height = one.winfo_height()
        original_threads = threads
        threads = threads + [
            dict(threads[0], id=f"wide-{index}", project_key=f"wide-{index}",
                 project=f"加宽测试 {index}", updated=now - 1000 - index)
            for index in range(3)
        ]
        window.refresh_threads()
        until(root, lambda: len(window.project_cards) == 7)
        for width, columns in ((610, 4), (830, 5), (960, 6), (460, 3)):
            target = round(width * window.scale)
            resize(target, original_height)
            until(root, lambda: root.winfo_width() == target)
            cards = list(window.project_cards.values())
            assert all(card.winfo_rooty() == cards[0].winfo_rooty() for card in cards[:columns])
            assert cards[columns].winfo_rooty() > cards[0].winfo_rooty()
            assert all(card.winfo_width() == default_card_width for card in cards)
            assert all(card.winfo_height() == default_card_height for card in cards)
        threads = original_threads
    finally:
        pointer.stop()
        window.close()
    check_languages(store, threads, settings)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        check_window(TaskStore(Path(temp) / "notes.sqlite"))
    print("Windows sticky notes smoke test passed")
