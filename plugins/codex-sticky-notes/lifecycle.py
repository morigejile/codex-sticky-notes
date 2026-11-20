"""Windows process detection and per-user, per-session instance coordination."""

import ctypes
import hashlib
from ctypes import wintypes
from pathlib import Path

from data import APP_HOME

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
kernel.OpenMutexW.restype = wintypes.HANDLE
kernel.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
kernel.CreateEventW.restype = wintypes.HANDLE
kernel.SetEvent.argtypes = (wintypes.HANDLE,)
kernel.SetEvent.restype = wintypes.BOOL
kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
kernel.WaitForSingleObject.restype = wintypes.DWORD
kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel.CloseHandle.restype = wintypes.BOOL


def object_name(name):
    identity = hashlib.sha256(str(APP_HOME.resolve()).casefold().encode("utf-8")).hexdigest()[:24]
    return f"Local\\CodexStickyNotes-{identity}-{name}"


class Instance:
    def __init__(self, name):
        self.name = object_name(name)
        self.handle = kernel.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not self.handle:
            raise ctypes.WinError(error)
        self.primary = error != 183  # ERROR_ALREADY_EXISTS
        if not self.primary:
            self.close()

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None

    @staticmethod
    def running(name):
        handle = kernel.OpenMutexW(0x00100000, False, object_name(name))
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True


class Event:
    def __init__(self, name):
        self.handle = kernel.CreateEventW(None, False, False, object_name(name))
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def signal(self):
        if not kernel.SetEvent(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, milliseconds=0):
        result = kernel.WaitForSingleObject(self.handle, milliseconds)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None


class ProcessEntry(ctypes.Structure):
    _fields_ = (
        ("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
        ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
        ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
        ("exe", wintypes.WCHAR * 260),
    )


kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
kernel.Process32FirstW.restype = wintypes.BOOL
kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
kernel.Process32NextW.restype = wintypes.BOOL
kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel.GetProcessTimes.argtypes = (
    wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
kernel.GetProcessTimes.restype = wintypes.BOOL
kernel.ProcessIdToSessionId.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
kernel.ProcessIdToSessionId.restype = wintypes.BOOL
kernel.GetCurrentProcessId.restype = wintypes.DWORD


def codex_processes():
    """Identify desktop roots in this session, excluding CLI and Chromium children."""
    session = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    candidates = []
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.exe.casefold() in ("chatgpt.exe", "codex.exe"):
                candidates.append((entry.pid, entry.parent))
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)

    desktop = {}
    for pid, parent in candidates:
        process_session = wintypes.DWORD()
        if not kernel.ProcessIdToSessionId(pid, ctypes.byref(process_session)):
            continue
        if process_session.value != session.value:
            continue
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                continue
            executable = Path(path.value)
            package = executable.parent.parent.name
            if executable.parent.name.casefold() != "app" or not package.startswith("OpenAI.Codex_"):
                continue
            created, exited, cpu_kernel, cpu_user = (wintypes.FILETIME() for _ in range(4))
            if kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                      ctypes.byref(cpu_kernel), ctypes.byref(cpu_user)):
                timestamp = (created.dwHighDateTime << 32) | created.dwLowDateTime
                desktop[pid] = (parent, timestamp)
        finally:
            kernel.CloseHandle(handle)
    return {(pid, created) for pid, (parent, created) in desktop.items() if parent not in desktop}
