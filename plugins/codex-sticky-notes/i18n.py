"""Language selection and translated interface strings."""

import ctypes
import json
import locale
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


LANGUAGE_CHOICES = ("system", "zh-CN", "en")
MESSAGES = {
    "app.title": ("Codex 便签", "Codex Sticky Notes"),
    "app.heading": ("Codex 便签", "Codex Notes"),
    "app.open": ("打开 Codex 便签", "Open Codex Notes"),
    "language.menu": ("语言 ▾", "Language ▾"),
    "language.system": ("跟随系统", "System Default"),
    "language.save_error": ("无法保存语言设置，请重试。", "Couldn't save the language setting. Try again."),
    "action.collapse": ("收起", "Collapse"),
    "action.pin": ("置顶", "Pin"),
    "action.close": ("关闭", "Close"),
    "action.refresh": ("刷新", "Refresh"),
    "todo.heading": ("待办", "Todos"),
    "todo.fix": ("固定待办", "Pin tasks"),
    "todo.add": ("添加", "Add"),
    "todo.placeholder": ("记一条待办", "Add a todo"),
    "todo.left": ("{count} 项未完成", "{count} left"),
    "todo.empty": ("还没有待办", "No todos yet"),
    "todo.edit": ("编辑", "Edit"),
    "todo.delete": ("删除", "Delete"),
    "todo.edit_title": ("编辑待办", "Edit todo"),
    "todo.edit_prompt": ("待办内容", "Todo text"),
    "todo.save": ("保存", "Save"),
    "todo.cancel": ("取消", "Cancel"),
    "todo.delete_title": ("删除待办", "Delete todo"),
    "todo.delete_prompt": ("删除这条待办？\n\n{text}", "Delete this todo?\n\n{text}"),
    "todo.read_error": ("暂时无法读取本地待办。", "Couldn't read local todos."),
    "todo.write_error": ("保存失败，请重试。", "Couldn't save the changes. Try again."),
    "error.todo_text_length": ("请输入 1 至 1000 个字符。", "Enter 1 to 1,000 characters."),
    "error.todo_done": ("完成状态必须为 true 或 false。", "Completion must be true or false."),
    "error.todo_empty_update": ("请提供待办内容或完成状态。", "Provide todo text or completion status."),
    "error.todo_not_found": ("找不到这条待办。", "This todo was not found."),
    "projects.heading": ("项目会话", "Project sessions"),
    "project.running": ("有活动 {count}", "Active {count}"),
    "project.unread": ("待查看 {count}", "To review {count}"),
    "project.read": ("已查看", "Read"),
    "project.unknown": ("待确认", "Pending"),
    "project.unassigned": ("未分组", "Unassigned"),
    "sessions.count.one": ("{count} 个会话", "{count} session"),
    "sessions.count.many": ("{count} 个会话", "{count} sessions"),
    "sessions.loading": ("正在读取本机会话…", "Reading local sessions…"),
    "sessions.read_error": ("会话读取失败，可点刷新重试。", "Couldn't read sessions. Click Refresh to retry."),
    "sessions.refresh_error": ("刷新失败，以下是上次读取结果。", "Refresh failed. Showing the last results."),
    "sessions.empty": ("没有找到本机会话", "No local sessions found"),
    "session.untitled": ("未命名会话", "Untitled session"),
    "session.open_error": ("打开会话失败", "Couldn't open session"),
    "session.open_hint": ("请确认本机已安装 Codex 桌面应用。", "Make sure the Codex desktop app is installed."),
    "status.running": ("有新活动", "Active"),
    "status.stale": ("状态待确认", "Pending"),
    "status.completed": ("本轮完成", "Completed"),
    "status.interrupted": ("本轮中断", "Interrupted"),
    "status.failed": ("本轮失败", "Failed"),
    "status.unknown": ("状态未知", "Unknown"),
    "status.unread_completed": ("完成待查看", "To review"),
    "mcp.threads_source": ("本机 Codex 会话记录。进展消息是会话内容。",
                           "Local Codex session records. Progress messages come from the sessions."),
    "mcp.threads_read_error": ("无法读取当前 Codex 版本的本地会话记录。",
                               "Couldn't read the local session records for this version of Codex."),
    "mcp.open_unsupported": ("便签小窗需要在 Windows 或 macOS 本机打开。",
                             "Open the sticky notes on a Windows or macOS computer."),
    "mcp.open_failed": ("无法启动便签窗口。请检查便签或 Python 安装。",
                        "Couldn't start Sticky Notes. Check the Sticky Notes or Python installation."),
    "mcp.open_requested": ("已发出打开便签窗口的请求。", "Requested to open Sticky Notes."),
}


def system_language():
    if sys.platform == "win32":
        name = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
    elif sys.platform == "darwin":
        try:
            output = subprocess.run(
                ("/usr/bin/defaults", "read", "-g", "AppleLanguages"),
                capture_output=True, text=True, check=True, timeout=2,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            output = ""
        first = re.search(r'^\s*"?([A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*)"?\s*,?\s*$', output, re.M)
        name = first[1] if first else ""
    else:
        name = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return "zh-CN" if re.match(r"^zh(?:[-_.@]|$)", name, re.I) else "en"


def load_language(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("language") in LANGUAGE_CHOICES:
            return data["language"]
    except (OSError, ValueError):
        pass
    return "system"


def save_language(path, choice):
    if choice not in LANGUAGE_CHOICES:
        raise ValueError(choice)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".json", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump({"language": choice}, file)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Translator:
    def __init__(self, choice="system"):
        self.language = choice if choice in ("zh-CN", "en") else system_language()

    def __call__(self, key, **values):
        return MESSAGES[key][int(self.language == "en")].format(**values)

    def count(self, key, count):
        suffix = "one" if count == 1 else "many"
        return self(f"{key}.{suffix}", count=count)


def translator_for(widget):
    return widget.winfo_toplevel().notes_tr


def thread_title(thread, tr, *, hide_project=False):
    if thread.get("untitled"):
        return tr("session.untitled")
    title = thread["title"]
    project = (thread.get("project") or "").strip()
    if hide_project and project:
        separator = r"(?:\s*[·•‧・:：|｜]\s*|\s+[-–—]\s+)"
        prefix = rf"^\s*{re.escape(project)}{separator}"
        match = re.match(prefix, title, flags=re.IGNORECASE)
        if match:
            name = title[match.end():].strip()
            if name:
                return name
    return title


def project_name(project_key, name, tr):
    return tr("project.unassigned") if project_key == "unassigned" else name
