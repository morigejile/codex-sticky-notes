#!/bin/bash
set -eu

project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
window="$project_dir/plugins/codex-sticky-notes/window.py"

if [[ -f "$window" ]]; then
    for python in "$(command -v python3 || true)" /usr/local/bin/python3 /opt/homebrew/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
        if [[ -n "$python" && -x "$python" && "$python" != /usr/bin/python3 ]] &&
            "$python" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            exec "$python" -B "$window" "$@"
        fi
    done
    message="请先安装带 Tkinter 的 Python 3.11 或更新版本（python.org），再打开 Codex 便签。"
else
    message="请先解压整个 Codex 便签文件夹，再打开其中的启动脚本。"
fi
printf '%s\n' "$message" >&2
/usr/bin/osascript -e 'on run argv' \
    -e 'display alert "Codex 便签" message (item 1 of argv)' -e 'end run' "$message"
exit 1
