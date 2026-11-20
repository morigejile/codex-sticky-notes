"""Interactive Windows smoke test with temporary tasks and sample sessions."""

import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "codex-sticky-notes"))
from data import TaskStore
from window import StickyWindow


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


def check_window(store):
    now = int(time.time() * 1000)
    threads = [
        dict(id="one", title="整理会话进展和显示方式", updated=now - 30, progress="已验证测试版。",
             status="completed", unread_completed=True, unread=True,
             project_key="one", project="示例应用",
             project_path="D:/One"),
        dict(id="running", title="检查新版本", updated=now, progress="",
             status="running", unread_completed=False, unread=False,
             project_key="one", project="示例应用", project_path="D:/One"),
        dict(id="two", title="核对物流页面", updated=now - 20, progress="正在检查页面。",
             status="running", unread_completed=False, unread=False,
             project_key="two", project="示例项目的近期会话与进度整理" * 6,
             project_path="D:/Two"),
        dict(id="read", title="归纳资料", updated=now - 60, progress="",
             status="completed", unread_completed=False, unread=False,
             project_key="read", project="资料", project_path="D:/Read"),
    ]
    older_ids = [f"older-{index}" for index in range(12)]
    threads.extend(dict(threads[0], id=thread_id, title=f"较早的会话 {index + 1}",
                        updated=now - 100 - index, unread=False, unread_completed=False)
                   for index, thread_id in enumerate(older_ids))
    root = tk.Tk()
    root.attributes("-topmost", True)
    window = StickyWindow(root, store, lambda: threads)
    cursor = (-1, -1)
    pointer = patch.object(root, "winfo_pointerxy", side_effect=lambda: cursor)
    pointer.start()

    def point_at(widget):
        nonlocal cursor
        cursor = center(widget)
        widget.event_generate("<Enter>", x=widget.winfo_width() // 2,
                              y=widget.winfo_height() // 2)

    try:
        until(root, lambda: window.threads is not None and window.thread_list.winfo_ismapped())
        assert window.task_list.winfo_ismapped()
        assert window.task_list.winfo_rooty() < window.thread_list.winfo_rooty()
        window.entry.insert(0, "复核本周测试结果")
        window.add_task()
        assert len(store.list()) == 1
        task_surface = window.task_list.winfo_children()[0]
        task_row = next(child for child in task_surface.winfo_children()
                        if isinstance(child, tk.Frame))
        checkbox = next(child for child in task_row.winfo_children()
                        if isinstance(child, tk.Checkbutton))
        checkbox.invoke()
        assert store.list()[0]["done"]

        assert list(window.project_cards) == ["one", "two", "read"]
        one, two, read = window.project_cards.values()
        assert len({card.status for card in (one, two, read)}) == 3
        assert one.winfo_rootx() < two.winfo_rootx() < read.winfo_rootx()
        assert one.winfo_rooty() == two.winfo_rooty() == read.winfo_rooty()
        assert one.winfo_width() == one.winfo_height()
        original = root.geometry().split("+", 1)[0]
        root.geometry(f"{root.minsize()[0]}x{root.winfo_height()}")
        until(root, lambda: read.winfo_rooty() > one.winfo_rooty())
        assert read.winfo_rootx() == one.winfo_rootx()
        root.geometry(original)
        until(root, lambda: read.winfo_rooty() == one.winfo_rooty())
        point_at(window.entry)
        until(root, lambda: window.popup is None)
        point_at(one)
        until(root, lambda: window.popup is not None and window.popup.winfo_viewable())
        popup = window.popup
        assert popup.anchor is one
        assert list(popup.links) == ["running", "one", *older_ids]
        first, second = popup.links["running"], popup.links["one"]
        assert first.winfo_width() == first.winfo_height()
        assert second.winfo_width() == first.winfo_width()
        assert first.winfo_rooty() == second.winfo_rooty()
        assert first.winfo_rootx() < second.winfo_rootx()
        assert (popup.winfo_rootx() >= one.winfo_rootx() + one.winfo_width()
                or popup.winfo_rootx() + popup.winfo_width() <= one.winfo_rootx())
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
        one, two, read = window.project_cards.values()
        assert one.status == two.status != read.status

        point_at(two)
        until(root, lambda: window.popup is not None and window.popup.winfo_viewable())
        assert window.popup.anchor is two
        popup = window.popup
        link = popup.links["two"]
        assert link.winfo_rooty() + link.winfo_height() <= popup.winfo_rooty() + popup.winfo_height()
        with patch("window.os.startfile") as startfile:
            link.event_generate("<ButtonRelease-1>", x=12, y=12)
            startfile.assert_called_once_with("codex://threads/two")
        assert window.popup is None

        window.collapse_button.invoke()
        until(root, lambda: window.floating is not None and window.floating.winfo_viewable())
        assert root.state() == "withdrawn"
        face = window.floating.face
        face.event_generate("<Leave>")
        idle_alpha = float(window.floating.attributes("-alpha"))
        face.event_generate("<Enter>")
        assert 0 < idle_alpha < float(window.floating.attributes("-alpha")) < 1
        face.event_generate("<ButtonRelease-1>", x=20, y=20)
        until(root, lambda: root.state() == "normal" and window.floating is None)

        root.iconify()
        until(root, lambda: window.floating is not None and window.floating.winfo_viewable())
        window.restore()
        until(root, lambda: root.state() == "normal" and window.floating is None)
    finally:
        pointer.stop()
        window.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        check_window(TaskStore(Path(temp) / "notes.sqlite"))
    print("Windows sticky notes smoke test passed")
