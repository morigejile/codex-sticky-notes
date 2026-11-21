import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "codex-sticky-notes"))
from i18n import Translator, load_language, project_name, save_language, system_language, thread_title


class LanguageTests(unittest.TestCase):
    def test_default_and_saved_preference(self):
        with tempfile.TemporaryDirectory() as folder, patch("i18n.system_language", return_value="zh-CN"):
            settings = Path(folder) / "CodexStickyNotes" / "settings.json"
            self.assertEqual(Translator(load_language(settings))("todo.heading"), "待办")
            save_language(settings, "en")
            self.assertEqual(Translator(load_language(settings))("todo.heading"), "Todos")
            save_language(settings, "system")
            self.assertEqual(load_language(settings), "system")
            self.assertEqual(Translator(load_language(settings))("todo.heading"), "待办")
            settings.write_text('{"language": ["en"]}', encoding="utf-8")
            self.assertEqual(load_language(settings), "system")

    def test_mac_system_language_uses_first_preference(self):
        with (patch("i18n.sys.platform", "darwin"),
              patch("i18n.subprocess.run") as run):
            run.return_value.stdout = '(\n    "zh-Hant-TW",\n    "en-US"\n)\n'
            self.assertEqual(system_language(), "zh-CN")
            run.return_value.stdout = '(\n    "fr-CA",\n    "zh-CN"\n)\n'
            self.assertEqual(system_language(), "en")

    def test_plural_and_generated_fallback_names(self):
        tr = Translator("en")
        self.assertEqual(tr.count("sessions.count", 1), "1 session")
        self.assertEqual(tr.count("sessions.count", 0), "0 sessions")
        self.assertEqual(project_name("unassigned", "未分组", tr), "Unassigned")
        self.assertEqual(project_name("real-project", "未分组", tr), "未分组")
        self.assertEqual(thread_title({"title": "未命名会话", "untitled": True}, tr), "Untitled session")
        self.assertEqual(thread_title({"title": "未命名会话"}, tr), "未命名会话")
