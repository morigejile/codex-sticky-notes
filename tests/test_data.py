import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "codex-sticky-notes"))
from data import TaskStore, group_threads, read_project_threads, read_threads


class StickyNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_tasks_persist_and_can_be_reopened_and_deleted(self):
        file = self.root / "tasks.sqlite"
        store = TaskStore(file)
        with self.assertRaises(ValueError):
            store.add("  ")
        task = store.add("  检查构建  ")
        self.assertEqual("检查构建", TaskStore(file).list()[0]["text"])
        store.update(task["id"], done=True)
        store.update(task["id"], text="检查安装包", done=False)
        self.assertEqual(
            {"id": task["id"], "text": "检查安装包", "done": False},
            TaskStore(file).list()[0],
        )
        store.delete(task["id"])
        self.assertEqual([], store.list())
        with self.assertRaises(KeyError):
            store.update(task["id"], done=True)

    def test_latest_turn_status_and_progress_exclude_hidden_threads_and_reasoning(self):
        now = int(time.time() * 1000)
        with closing(sqlite3.connect(self.root / "state_5.sqlite")) as db, db:
            db.execute("""CREATE TABLE threads (
                id, name, title, cwd, updated_at, updated_at_ms, source, archived
            )""")
            db.executemany("INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                ("open", "手动命名", "原始标题", "D:/项目", now // 1000, now, "vscode", 0),
                ("stale", None, "旧会话", "", (now - 900000) // 1000, now - 900000, "cli", 0),
                ("archived", None, "归档", "", now // 1000, now, "vscode", 1),
                ("agent", None, "子代理", "", now // 1000, now, '{"subagent":{}}', 0),
            ])
        with closing(sqlite3.connect(self.root / "thread_history_1.sqlite")) as db, db:
            db.execute("CREATE TABLE thread_turns (thread_id, turn_id, rollout_ordinal, status)")
            db.executemany("INSERT INTO thread_turns VALUES (?, ?, ?, ?)", [
                ("open", "a", 1, "completed"), ("open", "b", 2, "inProgress"),
                ("stale", "c", 1, "inProgress"),
            ])
            db.execute("""CREATE TABLE thread_items (
                thread_id, turn_id, item_type, rollout_ordinal, item_json, created_at_ms
            )""")
            db.executemany("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?)", [
                ("open", "a", "agentMessage", 1, json.dumps({"text": "旧结果"}), now - 1000),
                ("open", "b", "agentMessage", 2, json.dumps({"text": "正在检查安装包"}), now),
                ("open", "b", "reasoning", 3, json.dumps({"text": "隐藏内容"}), now),
            ])
        threads = read_threads(self.root)
        self.assertEqual(["open", "stale"], [thread["id"] for thread in threads])
        self.assertEqual(("手动命名", "running", "正在检查安装包"), (
            threads[0]["title"], threads[0]["status"], threads[0]["progress"]
        ))
        self.assertEqual("stale", threads[1]["status"])

    def test_missing_history_does_not_create_codex_files(self):
        with self.assertRaises(FileNotFoundError):
            read_threads(self.root)
        self.assertEqual([], list(self.root.iterdir()))

    def test_projects_resolve_by_assignment_or_most_specific_root(self):
        now = int(time.time())
        rows = [
            ("assigned", None, "已分配", "D:/临时工作区", now, now * 1000, "vscode", 0, None),
            ("nested", None, "子目录", r"d:\工作\应用\src", now, now * 1000 - 1, "vscode", 0, None),
            ("primary", None, "数据库归属", "D:/其他", now, now * 1000 - 2, "vscode", 0, "workspace"),
            ("loose", None, "独立会话", "D:/工作/应用", now, now * 1000 - 3, "vscode", 0, None),
        ]
        with closing(sqlite3.connect(self.root / "state_5.sqlite")) as db, db:
            db.execute("CREATE TABLE threads (id, name, title, cwd, updated_at, updated_at_ms, "
                       "source, archived, project_id)")
            db.executemany("INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            db.execute("CREATE TABLE projects (id, name)")
            db.executemany("INSERT INTO projects VALUES (?, ?)", [
                ("workspace", "工作"), ("app", "应用"),
            ])
            db.execute("CREATE TABLE project_roots (project_id, path, position)")
            db.executemany("INSERT INTO project_roots VALUES (?, ?, 0)", [
                ("workspace", "D:/工作"), ("app", "D:/工作/应用"),
            ])
        with closing(sqlite3.connect(self.root / "thread_history_1.sqlite")) as db, db:
            db.execute("CREATE TABLE thread_turns (thread_id, turn_id, rollout_ordinal, status)")
            db.executemany("INSERT INTO thread_turns VALUES (?, 'turn', 1, ?)", [
                ("assigned", "completed"), ("nested", "inProgress"),
                ("primary", "completed"), ("loose", "completed"),
            ])
            db.execute("CREATE TABLE thread_items (thread_id, turn_id, item_type, rollout_ordinal, "
                       "item_json, created_at_ms)")
        state = {
            "local-projects": {"old-app": {"name": "应用", "rootPaths": ["D:/工作/应用"]}},
            "app-server-project-id-by-legacy-project-id-by-host": {"desktop": {"old-app": "app"}},
            "thread-project-assignments": {
                "assigned": {"projectKind": "local", "projectId": "old-app"},
            },
            "projectless-thread-ids": ["loose"],
            "electron-thread-read-state-v1": {
                "version": 1,
                "unreadByIdentity": {"profile": {"local:desktop": ["assigned", "nested"],
                                                 "ssh:other": ["primary"]}},
            },
        }
        global_state = self.root / ".codex-global-state.json"
        global_state.write_text(json.dumps(state), encoding="utf-8")
        groups = group_threads(read_threads(self.root))
        self.assertEqual(["应用", "工作", "未分组"], [group["title"] for group in groups])
        self.assertEqual(["assigned", "nested"], [t["id"] for t in groups[0]["threads"]])
        self.assertEqual([1, 0, 0], [group["unread"] for group in groups])
        state["electron-thread-read-state-v1"]["unreadByIdentity"]["profile"]["local:desktop"].remove(
            "assigned")
        global_state.write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(0, group_threads(read_threads(self.root))[0]["unread"])
        global_state.write_text("{}", encoding="utf-8")
        self.assertIsNone(read_threads(self.root)[0]["unread"])
        self.assertEqual("unknown", group_threads(read_project_threads(self.root))[0]["status"])

    def test_project_overview_includes_older_unread_and_sorts_by_activity(self):
        now = int(time.time() * 1000)
        rows = [
            (f"chat-{index:02d}", str(index), "", "D:/first", now // 1000,
             now - index * 1000, "vscode", 0)
            for index in range(51)
        ]
        rows.append(("old-project", "另一个项目", "", "D:/second", now // 1000,
                     now - 55000, "vscode", 0))
        with closing(sqlite3.connect(self.root / "state_5.sqlite")) as db, db:
            db.execute("CREATE TABLE threads (id, name, title, cwd, updated_at, updated_at_ms, "
                       "source, archived)")
            db.executemany("INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        with closing(sqlite3.connect(self.root / "thread_history_1.sqlite")) as db, db:
            db.execute("CREATE TABLE thread_turns (thread_id, turn_id, rollout_ordinal, status)")
            db.executemany("INSERT INTO thread_turns VALUES (?, 'turn', 1, ?)", [
                (row[0], "inProgress" if row[0] == "chat-00" else "completed") for row in rows
            ])
            db.execute("CREATE TABLE thread_items (thread_id, turn_id, item_type, rollout_ordinal, "
                       "item_json, created_at_ms)")
            db.execute("INSERT INTO thread_items VALUES "
                       "('old-project', 'turn', 'agentMessage', 1, '{}', ?)", (now + 1000,))
        state = {"electron-thread-read-state-v1": {
            "version": 1, "unreadByIdentity": {"profile": {"local": ["chat-50"]}},
        }}
        (self.root / ".codex-global-state.json").write_text(json.dumps(state), encoding="utf-8")

        self.assertEqual(50, len(read_threads(self.root, limit=50)))
        groups = group_threads(read_project_threads(self.root))
        self.assertEqual(["second", "first"], [group["title"] for group in groups])
        self.assertEqual(["read", "unread"], [group["status"] for group in groups])
        first = groups[1]
        self.assertEqual(51, len(first["threads"]))
        self.assertEqual("chat-00", first["threads"][0]["id"])
        self.assertEqual("chat-50", first["threads"][-1]["id"])
        self.assertEqual(1, first["unread"])

    def test_project_status_requires_known_activity_and_read_state(self):
        thread = {"id": "one", "updated": 0, "project_key": "one", "project": "项目",
                  "project_path": "", "unread_completed": False}
        for status, unread, expected in (
            ("running", False, "running"),
            ("stale", False, "unknown"),
            ("unknown", False, "unknown"),
            ("completed", None, "unknown"),
            ("failed", True, "unknown"),
            ("interrupted", False, "read"),
        ):
            with self.subTest(status=status, unread=unread):
                group, = group_threads([dict(thread, status=status, unread=unread)])
                self.assertEqual(expected, group["status"])

    def test_distinct_workspaces_with_the_same_name_do_not_merge(self):
        threads = [
            {"id": "one", "updated": 2, "project_key": "cwd:D:/first/app",
             "project": "app", "project_path": "D:/first/app",
             "status": "completed", "unread": False, "unread_completed": False},
            {"id": "two", "updated": 1, "project_key": "cwd:D:/second/app",
             "project": "app", "project_path": "D:/second/app",
             "status": "completed", "unread": True, "unread_completed": True},
        ]
        groups = group_threads(threads)
        self.assertEqual(2, len(groups))
        self.assertEqual([0, 1], [group["unread"] for group in groups])
        self.assertNotEqual(groups[0]["subtitle"], groups[1]["subtitle"])


if __name__ == "__main__":
    unittest.main()
