"""Desktop actions the user can request through the chat.

These are only ever called by the whitelisted chat tools after validation (and,
for anything that changes something, after the user confirmed in the chat UI).
The cat's own behaviour never calls this module.  Closing is always graceful
(WM_CLOSE, exactly like clicking the window's X button, so apps can still ask to
save); processes are never killed.
"""
from __future__ import annotations

import ctypes
import difflib
import json
import subprocess
import threading
import logging
import os
import re
import shutil
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from . import win32

log = logging.getLogger(__name__)

WM_CLOSE = 0x0010
SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
KEYEVENTF_KEYUP = 0x0002
MEDIA_KEYS = {"next": 0xB0, "previous": 0xB1, "stop": 0xB2, "play_pause": 0xB3}
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


if win32.IS_WINDOWS:
    _u, _k = win32.user32, win32.kernel32
    _u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _u.PostMessageW.restype = wintypes.BOOL
    _u.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.ShowWindowAsync.restype = wintypes.BOOL
    _u.IsHungAppWindow.argtypes = [wintypes.HWND]
    _u.IsHungAppWindow.restype = wintypes.BOOL
    _u.SetForegroundWindow.argtypes = [wintypes.HWND]
    _u.SetForegroundWindow.restype = wintypes.BOOL
    _u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    _u.keybd_event.restype = None
    _u.LockWorkStation.argtypes = []
    _u.LockWorkStation.restype = wintypes.BOOL
    _u.HungWindowFromGhostWindow.argtypes = [wintypes.HWND]
    _u.HungWindowFromGhostWindow.restype = wintypes.HWND
    _k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k.OpenProcess.restype = wintypes.HANDLE
    _k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                              ctypes.POINTER(wintypes.DWORD)]
    _k.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _k.CloseHandle.argtypes = [wintypes.HANDLE]
    _k.CloseHandle.restype = wintypes.BOOL
    _k.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]
    _k.GetSystemPowerStatus.restype = wintypes.BOOL
    _k.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    _k.GlobalMemoryStatusEx.restype = wintypes.BOOL
    _k.GetTickCount64.argtypes = []
    _k.GetTickCount64.restype = ctypes.c_ulonglong
    _k.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
    _k.GetSystemTimes.restype = wintypes.BOOL


# ------------------------------------------------------------------ windows
@dataclass(frozen=True)
class AppWindow:
    hwnd: int
    title: str
    exe: str          # e.g. "chrome.exe"
    minimized: bool
    maximized: bool
    cls: str = ""
    pid: int = 0

    @property
    def app(self) -> str:
        return self.exe[:-4] if self.exe.lower().endswith(".exe") else self.exe

    def label(self) -> str:
        state = " (minimized)" if self.minimized else (" (maximized)" if self.maximized else "")
        title = self.title if len(self.title) <= 60 else self.title[:57] + "..."
        return f"{self.app}: {title}{state}"


def process_exe(pid: int) -> str:
    h = win32.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if win32.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name
        return ""
    finally:
        win32.kernel32.CloseHandle(h)


def list_app_windows(own_pid: int) -> list[AppWindow]:
    """Alt-Tab-like list of app windows (includes minimised ones), top of z-order first."""
    out: list[AppWindow] = []

    def _cb(hwnd, _lp):  # type: ignore[no-untyped-def]
        try:
            if not hwnd or not win32.user32.IsWindowVisible(hwnd) or win32.is_cloaked(hwnd):
                return True
            ex = win32.get_exstyle(hwnd)
            if ex & win32.WS_EX_TOOLWINDOW and not ex & win32.WS_EX_APPWINDOW:
                return True
            if win32.user32.GetWindow(hwnd, win32.GW_OWNER) and not ex & win32.WS_EX_APPWINDOW:
                return True
            pid = win32.window_pid(hwnd)
            if pid == own_pid or win32.class_name(hwnd) in _SHELL_CLASSES:
                return True
            title = win32.window_text(hwnd)
            if not title:
                return True
            cls = win32.class_name(hwnd)
            if cls == "Ghost":  # "(Not Responding)" stand-in window: report the real, hung app instead
                real = win32.user32.HungWindowFromGhostWindow(hwnd)
                if real:
                    pid = win32.window_pid(real)
                    if pid == own_pid:
                        return True
            out.append(AppWindow(int(hwnd), title, process_exe(pid) or "unknown",
                                 bool(win32.user32.IsIconic(hwnd)), bool(win32.user32.IsZoomed(hwnd)), cls, pid))
        except Exception:  # noqa: BLE001
            log.debug("window listing failed for %s", hwnd, exc_info=True)
        return True

    win32.user32.EnumWindows(win32.WNDENUMPROC(_cb), 0)
    return out


_ALIASES = {
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt", "outlook": "outlook", "teams": "ms-teams",
    "edge": "msedge", "microsoft edge": "msedge", "chrome": "chrome", "google chrome": "chrome", "firefox": "firefox",
    "vs code": "code", "vscode": "code", "visual studio code": "code", "file explorer": "explorer",
    "explorer": "explorer", "notepad": "notepad", "spotify": "spotify", "discord": "discord", "slack": "slack",
    "terminal": "windowsterminal", "task manager": "taskmgr", "paint": "mspaint",
}


def find_windows(query: str, windows: list[AppWindow]) -> list[AppWindow]:
    """Match by app name (exe), alias, or window title - best match group first."""
    q = query.strip().lower()
    q = q[:-4] if q.endswith(".exe") else q
    if not q:
        return []
    target = _ALIASES.get(q, q)
    by_exe = [w for w in windows if w.app.lower() == target or (target == "ms-teams" and w.app.lower() in ("teams", "ms-teams"))]
    if by_exe:
        return by_exe
    by_exe_part = [w for w in windows if target in w.app.lower()]
    if by_exe_part:
        return by_exe_part
    by_title = [w for w in windows if q in w.title.lower()]
    if by_title:
        return by_title
    names = {w.title.lower(): w for w in windows}
    close = difflib.get_close_matches(q, list(names), n=3, cutoff=0.75)
    return [names[c] for c in close]


def close_windows(windows: list[AppWindow]) -> int:
    """Politely ask windows to close (same as clicking X). Never kills processes."""
    n = 0
    for w in windows:
        if win32.user32.PostMessageW(w.hwnd, WM_CLOSE, 0, 0):
            n += 1
    return n


def window_action(w: AppWindow, action: str) -> None:
    """Change another app's window state.  ShowWindowAsync never blocks, so a hung
    app cannot freeze the cat (plain ShowWindow waits for the target thread)."""
    if win32.user32.IsHungAppWindow(w.hwnd):
        raise RuntimeError(f"{w.app} is not responding right now")
    if action == "minimize":
        win32.user32.ShowWindowAsync(w.hwnd, SW_MINIMIZE)
    elif action == "maximize":
        win32.user32.ShowWindowAsync(w.hwnd, SW_MAXIMIZE)
    elif action == "restore":
        win32.user32.ShowWindowAsync(w.hwnd, SW_RESTORE)
    elif action == "focus":
        if win32.user32.IsIconic(w.hwnd):
            win32.user32.ShowWindowAsync(w.hwnd, SW_RESTORE)
        win32.user32.SetForegroundWindow(w.hwnd)
    else:
        raise ValueError(action)


# ------------------------------------------------------------------ start menu apps
_shortcut_cache: tuple[float, dict[str, Path]] | None = None


def start_menu_shortcuts() -> dict[str, Path]:
    """Installed apps from the Start menu (per-user and all-users), name -> shortcut."""
    global _shortcut_cache
    if _shortcut_cache is not None and time.monotonic() - _shortcut_cache[0] < 120:
        return _shortcut_cache[1]
    roots = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
             Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs"]
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in (".lnk", ".url", ".appref-ms"):
                continue
            name = path.stem
            if re.search(r"uninstall|deinstall|readme|release notes|documentation|website", name, re.I):
                continue
            found.setdefault(name, path)
    _shortcut_cache = (time.monotonic(), found)
    return found


_store_apps: dict[str, str] | None = None
_store_lock = threading.Lock()


def store_apps() -> dict[str, str]:
    """Start-menu apps incl. Microsoft Store apps (name -> AppID) via the fixed,
    read-only PowerShell query ``Get-StartApps``.  Cached for the session."""
    global _store_apps
    with _store_lock:
        if _store_apps is not None:
            return _store_apps
        found: dict[str, str] = {}
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                 "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, creationflags=0x08000000)  # CREATE_NO_WINDOW
            data = json.loads(res.stdout or "[]")
            for item in data if isinstance(data, list) else [data]:
                name, app_id = item.get("Name"), item.get("AppID")
                if name and app_id and not re.search(r"uninstall", name, re.I):
                    found[name] = app_id
        except Exception:  # noqa: BLE001 - optional source; shortcuts still work
            log.info("Get-StartApps unavailable", exc_info=True)
        _store_apps = found
        return found


_prefetching = False


def prefetch_store_apps() -> None:
    global _prefetching
    if _store_apps is None and not _prefetching:
        _prefetching = True
        threading.Thread(target=store_apps, name="store-apps", daemon=True).start()


# English names -> localized Start-menu names (German Windows and friends)
_APP_NAME_ALIASES = {
    "calculator": ["rechner"], "photos": ["fotos"], "settings": ["einstellungen"], "camera": ["kamera"],
    "clock": ["uhr"], "alarms": ["uhr"], "calendar": ["kalender"], "weather": ["wetter"], "maps": ["karten"],
    "notepad": ["editor"], "store": ["microsoft store"], "voice recorder": ["sprachrekorder", "audiorekorder"],
    "media player": ["medienwiedergabe"], "movies": ["filme & tv"], "file explorer": ["explorer", "datei-explorer"],
    "task manager": ["task-manager"], "control panel": ["systemsteuerung"], "sticky notes": ["kurznotizen"],
}


def find_shortcut(name: str) -> tuple[str, Path | str] | None:
    for candidate in [name] + _APP_NAME_ALIASES.get(name.strip().lower(), []):
        hit = _find_shortcut(candidate)
        if hit is not None:
            return hit
    return None


def _find_shortcut(name: str) -> tuple[str, Path | str] | None:
    """Best Start-menu match: .lnk shortcuts first, then Store apps
    (returned as a ``shell:AppsFolder`` target)."""
    apps: dict[str, Path | str] = dict(start_menu_shortcuts())
    if _store_apps is None:  # never block the GUI: use Store apps once the background load is done
        prefetch_store_apps()
    for app_name, app_id in (_store_apps or {}).items():
        apps.setdefault(app_name, "shell:AppsFolder\\" + app_id)
    q = name.strip().lower()
    if not q:
        return None
    low = {k.lower(): k for k in apps}
    if q in low:
        k = low[q]
        return k, apps[k]
    starts = sorted((k for lk, k in low.items() if lk.startswith(q)), key=len)
    if starts:
        return starts[0], apps[starts[0]]
    words = sorted((k for lk, k in low.items() if re.search(rf"\b{re.escape(q)}\b", lk)), key=len)
    if words:
        return words[0], apps[words[0]]
    close = difflib.get_close_matches(q, list(low), n=1, cutoff=0.72)
    if close:
        k = low[close[0]]
        return k, apps[k]
    return None


def launch(path_or_uri: str | Path) -> None:
    os.startfile(str(path_or_uri))  # opens via the shell association, no command line


# ------------------------------------------------------------------ misc actions
def media_key(action: str) -> None:
    vk = MEDIA_KEYS[action]
    win32.user32.keybd_event(vk, 0, 0, 0)
    win32.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def lock_screen() -> bool:
    return bool(win32.user32.LockWorkStation())


SETTINGS_PAGES = {
    "home": "ms-settings:", "display": "ms-settings:display", "night light": "ms-settings:nightlight",
    "sound": "ms-settings:sound", "bluetooth": "ms-settings:bluetooth", "wifi": "ms-settings:network-wifi",
    "network": "ms-settings:network", "vpn": "ms-settings:network-vpn", "notifications": "ms-settings:notifications",
    "focus": "ms-settings:quiethours", "power": "ms-settings:powersleep", "battery": "ms-settings:batterysaver",
    "storage": "ms-settings:storagesense", "apps": "ms-settings:appsfeatures", "default apps": "ms-settings:defaultapps",
    "startup apps": "ms-settings:startupapps", "personalization": "ms-settings:personalization",
    "background": "ms-settings:personalization-background", "colors": "ms-settings:colors",
    "themes": "ms-settings:themes", "taskbar": "ms-settings:taskbar", "mouse": "ms-settings:mousetouchpad",
    "keyboard": "ms-settings:typing", "printers": "ms-settings:printers", "date and time": "ms-settings:dateandtime",
    "language": "ms-settings:regionlanguage", "privacy": "ms-settings:privacy", "windows update": "ms-settings:windowsupdate",
    "about": "ms-settings:about", "accessibility": "ms-settings:easeofaccess",
}


def _filetime(ft: wintypes.FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def cpu_percent(sample_s: float = 0.15) -> float:
    a = [wintypes.FILETIME() for _ in range(3)]
    b = [wintypes.FILETIME() for _ in range(3)]
    win32.kernel32.GetSystemTimes(*[ctypes.byref(x) for x in a])
    time.sleep(sample_s)
    win32.kernel32.GetSystemTimes(*[ctypes.byref(x) for x in b])
    idle, kern, user = (_filetime(b[i]) - _filetime(a[i]) for i in range(3))
    total = kern + user  # kernel time includes idle time
    return max(0.0, min(100.0, (total - idle) * 100.0 / total)) if total else 0.0


def system_info() -> str:
    parts: list[str] = []
    ps = SYSTEM_POWER_STATUS()
    if win32.kernel32.GetSystemPowerStatus(ctypes.byref(ps)):
        if ps.BatteryFlag == 128 or ps.BatteryLifePercent == 255:
            parts.append("Power: no battery (desktop)")
        else:
            plug = "plugged in" if ps.ACLineStatus == 1 else "on battery"
            parts.append(f"Battery: {ps.BatteryLifePercent}% ({plug})")
    ms = MEMORYSTATUSEX()
    ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if win32.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
        used = (ms.ullTotalPhys - ms.ullAvailPhys) / 2**30
        parts.append(f"RAM: {used:.1f} of {ms.ullTotalPhys / 2**30:.1f} GB used ({ms.dwMemoryLoad}%)")
    parts.append(f"CPU: {cpu_percent():.0f}%")
    try:
        du = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        parts.append(f"Disk {os.environ.get('SystemDrive', 'C:')} {du.free / 2**30:.0f} GB free of {du.total / 2**30:.0f} GB")
    except OSError:
        pass
    up = win32.kernel32.GetTickCount64() / 1000
    parts.append(f"Uptime: {int(up // 86400)}d {int(up % 86400 // 3600)}h {int(up % 3600 // 60)}m")
    return "; ".join(parts)


# ------------------------------------------------------------------ force end / run as admin
# Used only by the user's explicit "/force" chat command - never by the AI or the cat.
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
ERROR_ACCESS_DENIED = 5
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_FLAG_NO_UI = 0x00000400

# Ending any of these could crash or log off Windows, so /force refuses them.
PROTECTED_PROCESSES = {
    "system", "registry", "secure system", "memory compression", "idle", "smss.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe",
    "sihost.exe", "ctfmon.exe", "audiodg.exe", "spoolsv.exe", "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe",
    "taskhostw.exe", "runtimebroker.exe", "startmenuexperiencehost.exe", "searchhost.exe", "shellexperiencehost.exe",
    "textinputhost.exe", "applicationframehost.exe", "userinit.exe", "logonui.exe", "lockapp.exe", "wudfhost.exe",
}


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


if win32.IS_WINDOWS:
    _k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _k.Process32FirstW.restype = wintypes.BOOL
    _k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _k.Process32NextW.restype = wintypes.BOOL
    _k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k.TerminateProcess.restype = wintypes.BOOL
    _k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k.WaitForSingleObject.restype = wintypes.DWORD
    _k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k.GetExitCodeProcess.restype = wintypes.BOOL
    _k.IsProcessCritical.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    _k.IsProcessCritical.restype = wintypes.BOOL
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    _shell32.ShellExecuteExW.restype = wintypes.BOOL


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    exe: str


def list_processes() -> list[Proc]:
    snap = win32.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out: list[Proc] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = win32.kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.append(Proc(int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
            ok = win32.kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        win32.kernel32.CloseHandle(snap)
    return out


def _is_critical(pid: int) -> bool:
    h = win32.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        crit = wintypes.BOOL(False)
        return bool(win32.kernel32.IsProcessCritical(h, ctypes.byref(crit)) and crit.value)
    finally:
        win32.kernel32.CloseHandle(h)


@dataclass
class KillPlan:
    label: str               # what the user will see, e.g. "chrome.exe (14 processes)"
    pids: list[int]
    exes: list[str]


def plan_force_end(target: str, own_pid: int) -> KillPlan:
    """Work out which processes "/force end <target>" means, like Task Manager:
    an app name ends every process of that app (and its child processes); a
    window title ends that window's process tree.  Raises ValueError if nothing
    matches or the target is a protected Windows process."""
    q = target.strip().strip("\"'").lower()
    q = q[:-4] if q.endswith(".exe") else q
    if not q:
        raise ValueError("tell me which app to end, e.g. /force end chrome")
    stem = _ALIASES.get(q, q)
    procs = list_processes()
    by_pid = {p.pid: p for p in procs}
    roots = [p for p in procs if p.exe.lower()[:-4] == stem or (stem == "ms-teams" and p.exe.lower() in ("ms-teams.exe", "teams.exe"))]
    if not roots and len(stem) >= 3:
        roots = [p for p in procs if stem in p.exe.lower()[:-4]]
    if not roots:  # fall back to window titles (incl. "Not Responding" windows)
        wins = find_windows(target, list_app_windows(own_pid))
        roots = [by_pid[w.pid] for w in wins if w.pid in by_pid]
    if not roots:
        raise ValueError(f"no running app matches '{target}'")
    blocked = sorted({p.exe for p in roots if p.exe.lower() in PROTECTED_PROCESSES or p.pid in (0, 4)})
    if blocked:
        raise ValueError(f"I won't end {', '.join(blocked)} - it's a core part of Windows")
    # Like Task Manager's "End task": take the app's own helper processes along, but
    # never separate apps that merely were started from it (e.g. everything you
    # launch is a child of explorer.exe) - a child with its own window is its own app.
    window_pids = {w.pid for w in list_app_windows(own_pid)}
    root_pids = {p.pid for p in roots}
    chosen: dict[int, Proc] = {}
    frontier = [p.pid for p in roots]
    while frontier:
        pid = frontier.pop()
        if pid in chosen or pid == own_pid or pid not in by_pid:
            continue
        proc = by_pid[pid]
        if proc.exe.lower() in PROTECTED_PROCESSES:
            continue
        chosen[pid] = proc
        if proc.exe.lower() == "explorer.exe":
            continue  # the shell's children are other apps
        for c in procs:
            if c.ppid == pid and (c.exe.lower() == proc.exe.lower() or c.pid not in window_pids or c.pid in root_pids):
                frontier.append(c.pid)
    chosen = {pid: p for pid, p in chosen.items() if not _is_critical(pid)}
    if not chosen:
        raise ValueError(f"nothing I'm allowed to end matches '{target}'")
    exes = sorted({p.exe for p in chosen.values()}, key=str.lower)
    label = f"{', '.join(exes[:3])}{' ...' if len(exes) > 3 else ''} ({len(chosen)} process{'es' if len(chosen) != 1 else ''})"
    return KillPlan(label, sorted(chosen), exes)


def force_end(plan: KillPlan) -> tuple[list[int], list[int]]:
    """TerminateProcess every PID. Returns (ended, access_denied)."""
    ended, denied = [], []
    for pid in plan.pids:
        h = win32.kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
        if not h:
            err = ctypes.get_last_error()
            if err == ERROR_ACCESS_DENIED:
                denied.append(pid)
            continue  # already gone
        try:
            if win32.kernel32.TerminateProcess(h, 1):
                win32.kernel32.WaitForSingleObject(h, 2000)
                ended.append(pid)
            elif ctypes.get_last_error() == ERROR_ACCESS_DENIED:
                denied.append(pid)
        finally:
            win32.kernel32.CloseHandle(h)
    return ended, denied


def _shell_execute_admin(file: str, params: str | None, show: int, wait_ms: int) -> tuple[bool, str]:
    """ShellExecuteEx with the "runas" verb: Windows shows its UAC prompt and the
    user decides.  Returns (started, message)."""
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = file
    info.lpParameters = params
    info.nShow = show
    if not _shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        return False, "the admin prompt was cancelled" if err == 1223 else f"Windows refused (error {err})"
    if info.hProcess:
        try:
            if wait_ms:
                win32.kernel32.WaitForSingleObject(info.hProcess, wait_ms)
        finally:
            win32.kernel32.CloseHandle(info.hProcess)
    return True, "ok"


def force_end_elevated(pids: list[int]) -> tuple[bool, str]:
    """End processes that need admin rights via an elevated taskkill (UAC prompt)."""
    args = "/F /T " + " ".join(f"/PID {int(p)}" for p in pids)
    return _shell_execute_admin("taskkill.exe", args, 0, 15000)


def alive(pids: list[int]) -> list[int]:
    running = {p.pid for p in list_processes()}
    return [p for p in pids if p in running]


def run_as_admin(target: str | Path) -> tuple[bool, str]:
    """Start an app elevated (Windows shows the UAC prompt)."""
    return _shell_execute_admin(str(target), None, 1, 0)
