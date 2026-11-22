import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "codex-sticky-notes"))
import data
import launch
from window import ScrollPage


class PlatformTests(unittest.TestCase):
    def test_mac_projects_keep_path_case_and_respect_directory_boundaries(self):
        projects = {"main": ("应用", ["/Users/test/Work/App"])}
        workspaces = [("/Users/test/Work/App", "main")]

        def project(cwd):
            row = {"id": "one", "project_id": None, "cwd": cwd}
            return data._thread_project(row, {}, projects, {}, workspaces)

        self.assertEqual(project("/Users/test/Work/App/src")[0], "project:main")
        self.assertEqual(project("/Users/test/Work/Application")[0], "cwd:/Users/test/Work/Application")
        self.assertEqual(project("/Users/test/Work/app")[0], "cwd:/Users/test/Work/app")

    def test_mac_source_launch_uses_base_python_and_detaches(self):
        script = Path("source folder") / "window.py"
        with (patch.object(sys, "platform", "darwin"),
              patch.object(sys, "_base_executable", "/usr/local/bin/python3"),
              patch.object(launch.subprocess, "Popen") as popen):
            launch.start_gui(script, "--background")
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0],
                         ["/usr/local/bin/python3", "-B", str(script), "--background"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_mac_thread_link_is_passed_directly_to_launch_services(self):
        with (patch.object(sys, "platform", "darwin"),
              patch.object(launch.subprocess, "run") as run):
            launch.open_thread_link("sample/id")
        run.assert_called_once_with(
            ["/usr/bin/open", "codex://threads/sample%2Fid"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def test_mac_thread_link_without_a_handler_reports_a_launch_error(self):
        failed = subprocess.CalledProcessError(1, ["/usr/bin/open"])
        with (patch.object(sys, "platform", "darwin"),
              patch.object(launch.subprocess, "run", side_effect=failed)):
            with self.assertRaises(OSError):
                launch.open_thread_link("sample")

    def test_tk9_touchpad_scroll_uses_the_vertical_pixel_delta(self):
        page = SimpleNamespace(canvas=Mock(), content=42, tk=Mock())
        page.canvas.bbox.return_value = (0, 0, 100, 200)
        page.canvas.yview.return_value = (0.4, 0.8)
        page.tk.splitlist.return_value = (9, -20)
        ScrollPage.scroll_touchpad(page, SimpleNamespace(widget=page, delta=655340))
        page.tk.call.assert_called_once_with("tk::PreciseScrollDeltas", 655340)
        page.canvas.yview_moveto.assert_called_once_with(0.5)
