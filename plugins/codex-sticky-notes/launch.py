"""Open the notes and hand Codex links to the desktop."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


MAC_BUNDLE_ID = "com.morigejile.codex-sticky-notes"


def gui_command(script, *args):
    if sys.platform == "darwin":
        return [sys._base_executable, "-B", str(script), *args]
    pythonw = Path(sys.base_prefix) / "pythonw.exe"
    if not pythonw.is_file():
        raise FileNotFoundError("找不到 Python 安装目录中的 pythonw.exe。")
    return [str(pythonw), "-B", str(script), *args]


def start_gui(script, *args):
    options = ({"start_new_session": True} if sys.platform == "darwin" else
               {"creationflags": subprocess.CREATE_NO_WINDOW})
    return subprocess.Popen(
        gui_command(script, *args),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **options,
    )


def thread_url(thread_id):
    return "codex://threads/" + quote(thread_id, safe="")


def open_thread_link(thread_id):
    url = thread_url(thread_id)
    if sys.platform == "darwin":
        try:
            subprocess.run(["/usr/bin/open", url], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as error:
            raise OSError("macOS 无法打开 Codex 会话链接。") from error
    else:
        os.startfile(url)


def open_notes():
    if sys.platform == "darwin":
        opened = subprocess.run(
            ["/usr/bin/open", "-b", MAC_BUNDLE_ID],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if opened.returncode == 0:
            return
    start_gui(Path(__file__).with_name("window.py"))


if __name__ == "__main__":
    try:
        start_gui(Path(__file__).with_name("window.py"), *sys.argv[1:])
    except OSError as error:
        raise SystemExit(str(error)) from error
