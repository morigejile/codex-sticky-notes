"""Local persistence for the sticky notes and read-only Codex history."""

import json
import ntpath
import os
import posixpath
import sqlite3
import sys
import time
from collections import Counter
from contextlib import closing
from pathlib import Path
from uuid import uuid4

CODEX_HOME = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
if sys.platform == "darwin":
    APP_HOME = Path.home() / "Library" / "Application Support" / "CodexStickyNotes"
else:
    APP_HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "CodexStickyNotes"
THREAD_STATUSES = frozenset({"running", "stale", "completed", "interrupted", "failed", "unknown"})


class TaskInputError(ValueError):
    def __init__(self, message_key):
        super().__init__(message_key)
        self.message_key = message_key


class TaskNotFoundError(KeyError):
    message_key = "error.todo_not_found"


class TaskStore:
    def __init__(self, file=None):
        self.file = Path(file) if file is not None else APP_HOME / "tasks.sqlite"

    def _connect(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.file, timeout=2)
        try:
            db.row_factory = sqlite3.Row
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
            )""")
        except BaseException:
            db.close()
            raise
        return db

    @staticmethod
    def _task(row):
        return {"id": row["id"], "text": row["text"], "done": bool(row["done"])}

    @staticmethod
    def _text(value):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 1000:
            raise TaskInputError("error.todo_text_length")
        return value.strip()

    def list(self):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT id, text, done FROM tasks ORDER BY done, created_at DESC")
            return [self._task(row) for row in rows]

    def add(self, text):
        text = self._text(text)
        task_id = str(uuid4())
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO tasks (id, text, created_at) VALUES (?, ?, ?)",
                       (task_id, text, time.time_ns()))
        return {"id": task_id, "text": text, "done": False}

    def update(self, task_id, *, text=None, done=None):
        if text is not None:
            text = self._text(text)
        if done is not None and not isinstance(done, bool):
            raise TaskInputError("error.todo_done")
        if text is None and done is None:
            raise TaskInputError("error.todo_empty_update")
        with closing(self._connect()) as db, db:
            row = db.execute(
                """UPDATE tasks SET text = coalesce(?, text), done = coalesce(?, done)
                   WHERE id = ? RETURNING id, text, done""",
                (text, done, task_id),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(task_id)
            return self._task(row)

    def delete(self, task_id):
        with closing(self._connect()) as db, db:
            if not db.execute("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount:
                raise TaskNotFoundError(task_id)


def _read_only(file):
    if not file.is_file():
        raise FileNotFoundError(f"找不到 Codex 本地数据库 {file.name}。")
    db = sqlite3.connect(file.absolute().as_uri() + "?mode=ro", uri=True, timeout=0.3)
    db.row_factory = sqlite3.Row
    return db


def read_threads(root=CODEX_HOME, limit=30):
    """Return recent user sessions using the local Desktop history index."""
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("会话数量必须是 1 至 50 的整数。")
    return _read_threads(Path(root), limit)


def read_project_threads(root=CODEX_HOME):
    """Include all eligible local sessions when calculating project status."""
    return _read_threads(Path(root), -1)  # SQLite's LIMIT -1 keeps all rows.


def _read_threads(root, limit):
    desktop = _desktop_state(root)
    with closing(_read_only(root / "state_5.sqlite")) as state:
        columns = {row["name"] for row in state.execute("PRAGMA table_info(threads)")}
        project_column = "project_id" if "project_id" in columns else "NULL AS project_id"
        rows = state.execute(
            f"""SELECT id, name, title, cwd, {project_column},
                       coalesce(updated_at_ms, updated_at * 1000, 0) AS updated
                FROM threads WHERE archived = 0 AND source IN ('vscode', 'cli', 'appServer')
                ORDER BY updated DESC, id LIMIT ?""",
            (limit,),
        ).fetchall()
        projects, project_aliases, workspaces = _projects(state, desktop)

    now = int(time.time() * 1000)
    unread = _unread_ids(desktop)
    with closing(_read_only(root / "thread_history_1.sqlite")) as history:
        history.execute("BEGIN")
        threads = []
        for row in rows:
            thread = _describe_thread(row, history, now)
            project_key, name, path = _thread_project(
                row, desktop, projects, project_aliases, workspaces)
            thread.update(project_key=project_key, project=name, project_path=path)
            thread["unread"] = None if unread is None else row["id"] in unread
            thread["unread_completed"] = (
                None if unread is None else thread["status"] == "completed" and thread["unread"]
            )
            threads.append(thread)
        return threads


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _desktop_state(root):
    try:
        return _mapping(json.loads((root / ".codex-global-state.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def _unread_ids(desktop):
    read_state = _mapping(desktop.get("electron-thread-read-state-v1"))
    if read_state.get("version") != 1:
        return None
    identities = read_state.get("unreadByIdentity")
    if not isinstance(identities, dict):
        return None
    if not identities:
        return set()
    if len(identities) == 1:
        by_host = next(iter(identities.values()))
        if isinstance(by_host, dict):
            local_lists = [ids for host, ids in by_host.items()
                           if host == "local" or host.startswith("local:")]
            if all(isinstance(ids, list) and all(isinstance(item, str) for item in ids)
                   for ids in local_lists):
                return {thread_id for ids in local_lists for thread_id in ids}
    return None


def _projects(db, desktop):
    projects = {}
    try:
        rows = db.execute(
            """SELECT p.id, p.name, r.path
               FROM projects p LEFT JOIN project_roots r ON r.project_id = p.id
               ORDER BY p.id, r.position"""
        ).fetchall()
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        rows = []

    for row in rows:
        if row["id"] not in projects:
            projects[row["id"]] = (row["name"], [])
        if row["path"]:
            projects[row["id"]][1].append(row["path"])

    aliases = {}
    for host_aliases in _mapping(desktop.get(
            "app-server-project-id-by-legacy-project-id-by-host")).values():
        for legacy_id, project_id in _mapping(host_aliases).items():
            if isinstance(project_id, str) and project_id in projects:
                aliases[legacy_id] = project_id
    for legacy_id, value in _mapping(desktop.get("local-projects")).items():
        project = _mapping(value)
        name, roots = project.get("name"), project.get("rootPaths")
        if legacy_id not in aliases and isinstance(name, str) and isinstance(roots, list):
            projects.setdefault(legacy_id, (name, [path for path in roots if isinstance(path, str)]))
    workspaces = sorted(
        ((normalized_project_path(root), key) for key, (_, roots) in projects.items()
         for root in roots if root),
        key=lambda match: -len(match[0]),
    )
    return projects, aliases, workspaces


def project_path_module(path):
    if path.startswith("/") and not path.startswith("//"):
        return posixpath
    if ntpath.splitdrive(path)[0] or "\\" in path:
        return ntpath
    return posixpath if sys.platform == "darwin" else ntpath


def normalized_project_path(path):
    path_module = project_path_module(path)
    return path_module.normcase(path_module.normpath(path))


def _thread_project(row, desktop, projects, aliases, workspaces):
    thread_id = row["id"]
    assignment = _mapping(_mapping(desktop.get("thread-project-assignments")).get(thread_id))
    if row["project_id"] in projects:
        project_id = row["project_id"]
    elif thread_id in (desktop.get("projectless-thread-ids") or []):
        return "unassigned", "未分组", ""
    else:
        project_id = assignment.get("projectId") if assignment.get("projectKind") == "local" else None
        if isinstance(project_id, str):
            project_id = aliases.get(project_id, project_id)
    directory = row["cwd"] or ""
    path_module = project_path_module(directory)
    cwd = normalized_project_path(directory) if directory else ""
    sep = path_module.sep
    if project_id not in projects and cwd:
        project_id = next((key for path, key in workspaces
                           if cwd == path or cwd.startswith(path.rstrip(sep) + sep)), None)
    if project_id in projects:
        name, roots = projects[project_id]
        return f"project:{project_id}", name, roots[0] if roots else ""
    if cwd:
        return f"cwd:{cwd}", path_module.basename(path_module.normpath(directory)) or directory, directory
    return "unassigned", "未分组", ""


def is_finished_and_read(thread):
    return (thread["status"] in {"completed", "failed", "interrupted"}
            and thread.get("unread") is False)


def group_threads(threads, *, project_label=None):
    groups = {}
    for thread in sorted(threads, key=lambda item: (-item["updated"], item["id"])):
        key = thread["project_key"]
        if key not in groups:
            name = thread["project"]
            if project_label is not None:
                name = project_label(key, name)
            groups[key] = {
                "key": key, "title": name, "subtitle": thread["project_path"],
                "threads": [],
            }
        groups[key]["threads"].append(thread)
    names = Counter(group["title"] for group in groups.values())
    for group in groups.values():
        members = group["threads"]
        states = [thread["unread_completed"] for thread in members]
        group["unread"] = sum(state is True for state in states)
        group["running"] = sum(thread["status"] == "running" for thread in members)
        if group["unread"]:
            group["status"] = "unread"
        elif group["running"]:
            group["status"] = "running"
        elif all(is_finished_and_read(thread) for thread in members):
            group["status"] = "read"
        else:
            group["status"] = "unknown"
        if names[group["title"]] == 1:
            group["subtitle"] = ""
    return list(groups.values())


def _describe_thread(row, history, now):
    turn = history.execute(
        """SELECT turn_id, status FROM thread_turns WHERE thread_id = ?
           ORDER BY rollout_ordinal DESC LIMIT 1""",
        (row["id"],),
    ).fetchone()
    status = turn["status"] if turn else "unknown"
    updated = row["updated"]
    progress = ""
    if turn:
        message = history.execute(
            """SELECT item_json, created_at_ms FROM thread_items
               WHERE thread_id = ? AND turn_id = ? AND item_type = 'agentMessage'
               ORDER BY rollout_ordinal DESC LIMIT 1""",
            (row["id"], turn["turn_id"]),
        ).fetchone()
        if message:
            try:
                progress = " ".join(json.loads(message["item_json"])["text"].split())
                progress = progress[:360] + ("…" if len(progress) > 360 else "")
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
            updated = max(updated, message["created_at_ms"] or 0)

    if status == "inProgress":
        status = "running" if now - updated <= 5 * 60 * 1000 else "stale"
    title = row["name"] or row["title"]
    return {
        "id": row["id"],
        "title": title or "未命名会话",
        "untitled": not title,
        "updated": updated,
        "status": status if status in THREAD_STATUSES else "unknown",
        "progress": progress,
    }
