"""Build a portable desktop archive on the host OS."""

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = Path("plugins/codex-sticky-notes")
APP = "Codex Sticky Notes"
sys.path.insert(0, str(ROOT / PLUGIN))
from launch import MAC_BUNDLE_ID


def build(output):
    mac = sys.platform == "darwin"
    if not mac and sys.platform != "win32":
        raise SystemExit("请在 Windows 或 macOS 上构建对应的安装包。")
    system = "macos" if mac else "windows"
    machine = platform.machine().lower()
    if machine == "amd64":
        machine = "x86_64"
    stem = output / f"codex-sticky-notes-{system}-{machine}"

    with tempfile.TemporaryDirectory(dir=output) as folder:
        work = Path(folder)
        dist = work / "dist"
        args = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
            "--name", APP, "--distpath", str(dist), "--workpath", str(work / "build"),
            "--specpath", str(work), "--add-data", f"{ROOT / PLUGIN / 'assets'}:assets",
        ]
        if mac:
            args += ["--osx-bundle-identifier", MAC_BUNDLE_ID,
                     "--exclude-module", "native_frame", "--exclude-module", "lifecycle"]
        else:
            args += ["--exclude-module", "mac_lifecycle"]
        subprocess.run([*args, str(PLUGIN / "window.py")], cwd=ROOT, check=True)

        if mac:
            bundle = dist / f"{APP}.app"
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)],
                           check=True)
            archive = work / "mac.zip"
            subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                            str(bundle), str(archive)], check=True)
        else:
            archive = Path(shutil.make_archive(str(work / "windows"), "zip", dist, APP))
        archive.replace(stem.with_suffix(".zip"))
    return stem.with_suffix(".zip")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(build(output))
