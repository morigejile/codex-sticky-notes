import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "codex-sticky-notes"))
from lifecycle import Event, Instance
from startup import LaunchState
import window


class LifecycleTests(unittest.TestCase):
    def test_duplicate_instance_and_release(self):
        name = "test-" + uuid4().hex
        first = Instance(name)
        self.addCleanup(first.close)
        self.assertTrue(first.primary)
        second = Instance(name)
        self.assertFalse(second.primary)
        self.assertTrue(Instance.running(name))
        first.close()
        self.assertFalse(Instance.running(name))
        third = Instance(name)
        self.addCleanup(third.close)
        self.assertTrue(third.primary)

    def test_activation_is_consumed_once(self):
        name = "test-" + uuid4().hex
        receiver, sender = Event(name), Event(name)
        self.addCleanup(receiver.close)
        self.addCleanup(sender.close)
        self.assertFalse(receiver.wait())
        sender.signal()
        self.assertTrue(receiver.wait())
        self.assertFalse(receiver.wait())

    def test_window_launch_uses_base_pythonw_from_a_virtual_environment(self):
        from launch import start_gui

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "Python 安装"
            base.mkdir()
            pythonw = base / "pythonw.exe"
            pythonw.touch()
            shim = Path(folder) / "venv" / "Scripts" / "pythonw.exe"
            script = Path(folder) / "便签" / "window.py"
            with (patch.object(sys, "base_prefix", str(base)),
                  patch.object(sys, "executable", str(shim)), patch("launch.subprocess.Popen") as popen):
                start_gui(script, "--background")
                self.assertEqual(popen.call_args.args[0], [str(pythonw), "-B", str(script), "--background"])
                self.assertEqual(popen.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)

    def test_main_launchers_use_the_same_orange_instance(self):
        for args in ([], ["--background"], ["--orange-demo"]):
            with (self.subTest(args=args), patch.object(sys, "argv", ["window.py", *args]),
                  patch.object(window, "Instance") as instance, patch.object(window, "Event") as event,
                  patch.object(window.tk, "Tk") as tk, patch.object(window, "StickyWindow") as notes,
                  patch.object(window.ctypes.windll.user32, "SetProcessDPIAware")):
                window.main()
                instance.assert_called_once_with("window")
                event.assert_called_once_with("window-activate")
                notes.assert_called_once_with(tk.return_value, preview=False, project_color_demo=None)
                self.assertEqual(tk.return_value.withdraw.called, args == ["--background"])
                self.assertEqual(tk.return_value.after_idle.called, args == ["--background"])
                if args == ["--background"]:
                    tk.return_value.after_idle.assert_called_once_with(notes.return_value.collapse)

    def test_start_retry_close_and_next_codex_launch(self):
        state = LaunchState()
        first = {(123, 456)}
        self.assertFalse(state.needs_launch(set(), False))
        self.assertTrue(state.needs_launch(first, False))
        self.assertTrue(state.needs_launch(first, False))
        self.assertFalse(state.needs_launch(first, True))
        self.assertFalse(state.needs_launch(first, False))
        self.assertFalse(state.needs_launch(set(), False))
        self.assertTrue(state.needs_launch(first, False))
        self.assertFalse(state.needs_launch(first, True))
        # A recycled PID with a different creation time represents a fresh launch.
        self.assertTrue(state.needs_launch({(123, 789)}, False))


if __name__ == "__main__":
    unittest.main()
