"""Does starting something need administrator rights?

Used so the chat can *always* ask the user first before anything that needs
admin rights - even in auto mode and even for tools set to ALWAYS.  Read-only
checks, the same ones Windows itself uses:
* the program's embedded manifest (requestedExecutionLevel requireAdministrator,
  or highestAvailable when the user is an administrator with UAC),
* the shortcut's own "Run as administrator" flag,
* the compatibility setting "Run this program as an administrator" (RUNASADMIN),
* Windows' installer detection (setup/install/update programs without a manifest).
Also tells whether a UAC prompt (consent.exe) is on screen right now.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import winreg
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)

k32 = ctypes.windll.kernel32
ole32 = ctypes.windll.ole32
advapi32 = ctypes.windll.advapi32
LOAD_LIBRARY_AS_DATAFILE, LOAD_LIBRARY_AS_IMAGE_RESOURCE = 0x2, 0x20
RT_MANIFEST = 24
k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
k32.LoadLibraryExW.restype = wintypes.HMODULE
k32.FreeLibrary.argtypes = [wintypes.HMODULE]
k32.FreeLibrary.restype = wintypes.BOOL
k32.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
k32.FindResourceW.restype = wintypes.HANDLE
k32.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
k32.LoadResource.restype = wintypes.HGLOBAL
k32.LockResource.argtypes = [wintypes.HGLOBAL]
k32.LockResource.restype = ctypes.c_void_p
k32.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
k32.SizeofResource.restype = wintypes.DWORD
k32.GetCurrentProcess.argtypes = []
k32.GetCurrentProcess.restype = wintypes.HANDLE
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
advapi32.GetTokenInformation.restype = wintypes.BOOL

TokenElevationType = 18           # 1 default (standard user / UAC off), 2 full (elevated), 3 limited (admin + UAC)
_INSTALLER_NAMES = re.compile(r"(setup|install|uninst|update|patch|upgrad)", re.I)


def elevation_type() -> int:
    tok = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(k32.GetCurrentProcess(), 0x8, ctypes.byref(tok)):
        return 1
    try:
        val, size = wintypes.DWORD(), wintypes.DWORD()
        if advapi32.GetTokenInformation(tok, TokenElevationType, ctypes.byref(val), 4, ctypes.byref(size)):
            return int(val.value)
        return 1
    finally:
        k32.CloseHandle(tok)


def manifest_level(exe: str) -> str | None:
    """requestedExecutionLevel from the program's manifest ('asInvoker', 'requireAdministrator',
    'highestAvailable'), '' if it has a manifest without one, None if there is no manifest."""
    h = k32.LoadLibraryExW(exe, None, LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE)
    if not h:
        return None
    try:
        for rid in (1, 2, 3):
            res = k32.FindResourceW(h, ctypes.c_void_p(rid), ctypes.c_void_p(RT_MANIFEST))
            if not res:
                continue
            size = k32.SizeofResource(h, res)
            data = k32.LockResource(k32.LoadResource(h, res))
            if not data or not size:
                continue
            text = ctypes.string_at(data, size).decode("utf-8", "ignore")
            m = re.search(r"requestedExecutionLevel[^>]*level\s*=\s*[\"'](\w+)", text)
            return m.group(1) if m else ""
        return None
    finally:
        k32.FreeLibrary(h)


def _compat_runas(exe: str) -> bool:
    key = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as k:
                val, _t = winreg.QueryValueEx(k, exe)
                if "RUNASADMIN" in str(val).upper():
                    return True
        except OSError:
            continue
    return False


def exe_needs_admin(exe: str) -> bool:
    if not exe or not os.path.isfile(exe):
        return False
    if _compat_runas(exe):
        return True
    level = manifest_level(exe)
    if level == "requireAdministrator":
        return True
    if level == "highestAvailable":
        return elevation_type() == 3
    if level is None and _INSTALLER_NAMES.search(Path(exe).stem):
        return True  # Windows' installer detection would ask for admin rights
    return False


# ---- .lnk shortcuts (IShellLinkW through ctypes COM) ------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, s: str) -> "_GUID":
        a, b, c, d, e = s.split("-")
        return cls(int(a, 16), int(b, 16), int(c, 16), (ctypes.c_ubyte * 8)(*bytes.fromhex(d + e)))


_CLSID_ShellLink = _GUID.of("00021401-0000-0000-c000-000000000046")
_IID_IShellLinkW = _GUID.of("000214f9-0000-0000-c000-000000000046")
_IID_IPersistFile = _GUID.of("0000010b-0000-0000-c000-000000000046")
ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.c_long
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoUninitialize.argtypes = []
ole32.CoUninitialize.restype = None


def _method(ptr: int, index: int, *argtypes):  # type: ignore[no-untyped-def]
    vtbl = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[index])


def _release(ptr: int) -> None:
    if ptr:
        vtbl = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(ptr)


def lnk_target(path: str | Path) -> tuple[str, bool]:
    """(target program, 'Run as administrator' flag) of a .lnk shortcut."""
    runas = False
    try:
        with open(path, "rb") as fh:
            head = fh.read(0x18)
        if len(head) >= 0x18:
            runas = bool(int.from_bytes(head[0x14:0x18], "little") & 0x2000)   # SLDF_RUNAS_USER
    except OSError:
        pass
    hr_init = ole32.CoInitializeEx(None, 0x2)   # apartment; harmless if already initialised
    link = ctypes.c_void_p()
    pf = ctypes.c_void_p()
    try:
        if ole32.CoCreateInstance(ctypes.byref(_CLSID_ShellLink), None, 1, ctypes.byref(_IID_IShellLinkW),
                                  ctypes.byref(link)) < 0 or not link.value:
            return "", runas
        qi = _method(link.value, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        if qi(link.value, ctypes.byref(_IID_IPersistFile), ctypes.byref(pf)) < 0 or not pf.value:
            return "", runas
        if _method(pf.value, 5, wintypes.LPCWSTR, wintypes.DWORD)(pf.value, str(path), 0) < 0:
            return "", runas
        buf = ctypes.create_unicode_buffer(1024)
        _method(link.value, 3, wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)(
            link.value, buf, 1024, None, 0)
        return os.path.expandvars(buf.value), runas
    except OSError:
        return "", runas
    finally:
        _release(pf.value or 0)
        _release(link.value or 0)
        if hr_init in (0, 1):
            ole32.CoUninitialize()


def make_lnk(path: str | Path, target: str | Path, args: str = "", workdir: str | Path = "",
             icon: str | Path = "", description: str = "") -> bool:
    """Create (or replace) a .lnk shortcut to ``target``."""
    hr_init = ole32.CoInitializeEx(None, 0x2)
    link = ctypes.c_void_p()
    pf = ctypes.c_void_p()
    try:
        if ole32.CoCreateInstance(ctypes.byref(_CLSID_ShellLink), None, 1, ctypes.byref(_IID_IShellLinkW),
                                  ctypes.byref(link)) < 0 or not link.value:
            return False
        L = link.value
        _method(L, 20, wintypes.LPCWSTR)(L, str(target))                 # SetPath
        if args:
            _method(L, 11, wintypes.LPCWSTR)(L, args)                    # SetArguments
        if workdir:
            _method(L, 9, wintypes.LPCWSTR)(L, str(workdir))             # SetWorkingDirectory
        if description:
            _method(L, 7, wintypes.LPCWSTR)(L, description[:250])        # SetDescription
        if icon:
            _method(L, 17, wintypes.LPCWSTR, ctypes.c_int)(L, str(icon), 0)  # SetIconLocation
        qi = _method(L, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        if qi(L, ctypes.byref(_IID_IPersistFile), ctypes.byref(pf)) < 0 or not pf.value:
            return False
        return _method(pf.value, 6, wintypes.LPCWSTR, wintypes.BOOL)(pf.value, str(path), True) >= 0   # Save
    except OSError:
        return False
    finally:
        _release(pf.value or 0)
        _release(link.value or 0)
        if hr_init in (0, 1):
            ole32.CoUninitialize()


def needs_admin(target: object) -> bool:
    """For an open_app target: command list, .lnk/.exe path, URI or Store app."""
    try:
        if isinstance(target, list) and target:
            first = str(target[0])
            if re.match(r"^[a-z][a-z0-9+.-]*:", first, re.I) and not re.match(r"^[a-z]:\\", first, re.I):
                return False   # URI / protocol
            exe = first if os.path.isabs(first) else (shutil.which(first) or "")
            return exe_needs_admin(exe)
        text = str(target)
        if text.lower().startswith("shell:"):
            return False       # Store apps
        if text.lower().endswith(".lnk"):
            exe, runas = lnk_target(text)
            if exe.lower().endswith(".msc"):   # management consoles open in mmc.exe
                exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "mmc.exe")
            return runas or exe_needs_admin(exe)
        if text.lower().endswith(".exe"):
            return exe_needs_admin(text)
    except Exception:  # noqa: BLE001 - a failed check must not block opening apps
        log.debug("admin check failed for %s", target, exc_info=True)
    return False


def uac_prompt_open() -> bool:
    """True while Windows shows its admin-rights prompt (consent.exe)."""
    from . import control

    try:
        return any(p.exe.lower() == "consent.exe" for p in control.list_processes())
    except Exception:  # noqa: BLE001
        return False
