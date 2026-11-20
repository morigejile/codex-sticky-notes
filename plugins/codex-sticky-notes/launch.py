"""Open the notes with the base Python installation's GUI interpreter."""

import subprocess
import sys
from pathlib import Path


def gui_command(script, *args):
    pythonw = Path(sys.base_prefix) / "pythonw.exe"
    if not pythonw.is_file():
        raise FileNotFoundError("找不到 Python 安装目录中的 pythonw.exe。")
    return [str(pythonw), "-B", str(script), *args]


def start_gui(script, *args):
    return subprocess.Popen(
        gui_command(script, *args),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


if __name__ == "__main__":
    try:
        start_gui(Path(__file__).with_name("window.py"), *sys.argv[1:])
    except OSError as error:
        raise SystemExit(str(error)) from error
