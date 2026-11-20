"""Start the notes once for each Codex desktop application lifetime."""

import argparse
import logging
import subprocess
import sys
import winreg
from pathlib import Path

from data import APP_HOME
from lifecycle import Event, Instance, codex_processes

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CodexStickyNotes"


def enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, _ = winreg.QueryValueEx(key, RUN_NAME)
            return bool(command)
    except FileNotFoundError:
        return False


def set_enabled(value):
    if value:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            raise FileNotFoundError("找不到 pythonw.exe。")
        command = subprocess.list2cmdline([str(pythonw), "-B", str(Path(__file__).resolve()), "watch"])
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        subprocess.Popen([str(pythonw), "-B", str(Path(__file__).resolve()), "watch"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
        event = Event("watcher-stop")
        try:
            event.signal()
        finally:
            event.close()


class LaunchState:
    """Latch successful startup, allowing the user to close the notes afterward."""

    def __init__(self):
        self.handled = set()

    def needs_launch(self, current, notes_running):
        self.handled.intersection_update(current)
        if notes_running:
            self.handled.update(current)
        return bool(current - self.handled)


def watch():
    instance = Instance("watcher")
    if not instance.primary:
        return
    stop = Event("watcher-stop")
    state = LaunchState()
    child = None
    try:
        while enabled():
            current = codex_processes()
            should_launch = state.needs_launch(current, Instance.running("window"))
            if should_launch and (child is None or child.poll() is not None):
                try:
                    child = subprocess.Popen(
                        [str(Path(sys.executable).with_name("pythonw.exe")), "-B",
                         str(Path(__file__).with_name("window.py")), "--background"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    logging.exception("Unable to start sticky notes")
            if stop.wait(3000):
                break
    finally:
        stop.close()
        instance.close()


if __name__ == "__main__":
    APP_HOME.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=APP_HOME / "startup.log", level=logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("enable", "disable", "watch", "status"))
    action = parser.parse_args().action
    if action == "watch":
        watch()
    elif action == "status":
        print("enabled" if enabled() else "disabled")
    else:
        set_enabled(action == "enable")
        print("enabled" if action == "enable" else "disabled")
