"""Codex tools for the Windows sticky notes."""

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from data import STATUS_LABELS, TaskStore, read_threads

server = FastMCP("Codex 便签")
store = TaskStore()
read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
write_local = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


@server.tool(annotations=read_only)
def list_recent_threads(limit: Annotated[int, Field(ge=1, le=50)] = 10) -> dict[str, Any]:
    """查看本机最近的 Codex 会话、最近一轮状态及最后一条公开进展。"""
    try:
        threads = read_threads(limit=limit)
    except (OSError, sqlite3.Error) as error:
        raise ToolError("无法读取当前 Codex 版本的本地会话记录。") from error
    return {
        "source": "本机 Codex 会话记录。进展消息是会话内容。",
        "threads": [
            {
                "title": thread["title"],
                "project": thread["project"],
                "status": STATUS_LABELS[thread["status"]],
                "progress": thread["progress"],
                "link": "codex://threads/" + quote(thread["id"], safe=""),
            }
            for thread in threads
        ],
    }


@server.tool(annotations=read_only)
def list_todos() -> dict[str, Any]:
    """列出 Codex 便签里的本地待办及完成状态。"""
    return {"todos": store.list()}


@server.tool(annotations=write_local)
def add_todo(text: Annotated[str, Field(min_length=1, max_length=1000)]) -> dict[str, Any]:
    """把用户指定的事项添加到本机 Codex 便签。"""
    return store.add(text)


@server.tool(annotations=write_local)
def update_todo(todo_id: str, text: Annotated[str, Field(min_length=1, max_length=1000)] | None = None,
                done: bool | None = None) -> dict[str, Any]:
    """更新一项本地待办的内容或完成状态。用 list_todos 查找待办 ID。"""
    return store.update(todo_id, text=text, done=done)


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
def delete_todo(todo_id: str) -> dict[str, bool]:
    """删除用户指定的一项本地待办。用 list_todos 查找待办 ID。"""
    store.delete(todo_id)
    return {"deleted": True}


@server.tool(annotations=write_local)
def open_sticky_notes() -> dict[str, str]:
    """打开 Windows 上的 Codex 便签小窗。"""
    if sys.platform != "win32":
        raise ToolError("便签小窗需要在 Windows 本机打开。")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        raise ToolError("找不到用于打开小窗的 pythonw.exe。")
    subprocess.Popen([str(pythonw), "-B", str(Path(__file__).with_name("window.py"))],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"message": "已发出打开便签窗口的请求。"}


if __name__ == "__main__":
    server.run()
