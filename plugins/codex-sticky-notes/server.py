"""Codex tools for sticky notes."""

import sqlite3
import sys
from contextlib import contextmanager
from typing import Annotated, Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from data import APP_HOME, TaskInputError, TaskNotFoundError, TaskStore, read_threads
from i18n import Translator, load_language, project_name, thread_title
from launch import open_notes

server = FastMCP("Codex 便签")
store = TaskStore()
read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
write_local = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def _translator():
    return Translator(load_language(APP_HOME / "settings.json"))


@contextmanager
def _todo_errors(storage_error="todo.write_error"):
    try:
        yield
    except (TaskInputError, TaskNotFoundError) as error:
        raise ToolError(_translator()(error.message_key)) from error
    except (OSError, sqlite3.Error) as error:
        raise ToolError(_translator()(storage_error)) from error


@server.tool(annotations=read_only)
def list_recent_threads(limit: Annotated[int, Field(ge=1, le=50)] = 10) -> dict[str, Any]:
    """查看本机最近的 Codex 会话、最近一轮状态及最后一条公开进展。"""
    tr = _translator()
    try:
        threads = read_threads(limit=limit)
    except (OSError, sqlite3.Error) as error:
        raise ToolError(tr("mcp.threads_read_error")) from error
    return {
        "source": tr("mcp.threads_source"),
        "threads": [
            {
                "title": thread_title(thread, tr),
                "project": project_name(thread["project_key"], thread["project"], tr),
                "status": tr(f"status.{thread['status']}"),
                "status_code": thread["status"],
                "progress": thread["progress"],
                "link": "codex://threads/" + quote(thread["id"], safe=""),
            }
            for thread in threads
        ],
    }


@server.tool(annotations=read_only)
def list_todos() -> dict[str, Any]:
    """列出 Codex 便签里的本地待办及完成状态。"""
    with _todo_errors("todo.read_error"):
        return {"todos": store.list()}


@server.tool(annotations=write_local)
def add_todo(text: Annotated[str, Field(min_length=1, max_length=1000)]) -> dict[str, Any]:
    """把用户指定的事项添加到本机 Codex 便签。"""
    with _todo_errors():
        return store.add(text)


@server.tool(annotations=write_local)
def update_todo(todo_id: str, text: Annotated[str, Field(min_length=1, max_length=1000)] | None = None,
                done: bool | None = None) -> dict[str, Any]:
    """更新一项本地待办的内容或完成状态。用 list_todos 查找待办 ID。"""
    with _todo_errors():
        return store.update(todo_id, text=text, done=done)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
def delete_todo(todo_id: str) -> dict[str, bool]:
    """删除用户指定的一项本地待办。用 list_todos 查找待办 ID。"""
    with _todo_errors():
        store.delete(todo_id)
    return {"deleted": True}


@server.tool(annotations=write_local)
def open_sticky_notes() -> dict[str, str]:
    """打开本机 Codex 便签小窗。"""
    tr = _translator()
    if sys.platform not in {"win32", "darwin"}:
        raise ToolError(tr("mcp.open_unsupported"))
    try:
        open_notes()
    except OSError as error:
        raise ToolError(tr("mcp.open_failed")) from error
    return {"message": tr("mcp.open_requested")}


if __name__ == "__main__":
    server.run()
