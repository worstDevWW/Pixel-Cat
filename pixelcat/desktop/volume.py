"""Master volume via Core Audio (IAudioEndpointVolume) using raw ctypes COM.

Avoids extra dependencies (pycaw/comtypes).  We call interface methods through
their vtable slots; indices follow the declaration order in the Windows SDK
headers (mmdeviceapi.h / endpointvolume.h), counting IUnknown's 3 methods first.
"""
from __future__ import annotations

import ctypes
import logging
import uuid
from ctypes import wintypes

log = logging.getLogger(__name__)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_str(cls, s: str) -> "GUID":
        g = cls()
        ctypes.memmove(ctypes.byref(g), uuid.UUID(s).bytes_le, ctypes.sizeof(g))
        return g


CLSID_MMDeviceEnumerator = GUID.from_str("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID.from_str("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioEndpointVolume = GUID.from_str("{5CDF2C82-841E-4546-9722-0CF74078229A}")
CLSCTX_ALL = 23
E_RENDER, E_CONSOLE = 0, 0
COINIT_APARTMENTTHREADED = 0x2

_ole32 = ctypes.WinDLL("ole32")
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
_ole32.CoCreateInstance.restype = ctypes.c_long


def _method(obj: ctypes.c_void_p, index: int, restype, *argtypes):  # type: ignore[no-untyped-def]
    """Return a callable for vtable slot ``index`` of COM object ``obj``."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *args: fn(obj, *args)


def _release(obj: ctypes.c_void_p) -> None:
    if obj:
        _method(obj, 2, wintypes.ULONG)()


def _endpoint() -> tuple[ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]:
    _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)  # S_FALSE / RPC_E_CHANGED_MODE are fine
    enum = ctypes.c_void_p()
    hr = _ole32.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                                 ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(enum))
    if hr != 0:
        raise OSError(f"CoCreateInstance failed 0x{hr & 0xFFFFFFFF:08X}")
    device = ctypes.c_void_p()
    # IMMDeviceEnumerator::GetDefaultAudioEndpoint = slot 4
    hr = _method(enum, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
        E_RENDER, E_CONSOLE, ctypes.byref(device))
    if hr != 0:
        _release(enum)
        raise OSError("no default audio device")
    vol = ctypes.c_void_p()
    # IMMDevice::Activate = slot 3
    hr = _method(device, 3, ctypes.c_long, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p,
                 ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(IID_IAudioEndpointVolume), CLSCTX_ALL, None,
                                                  ctypes.byref(vol))
    if hr != 0:
        _release(device)
        _release(enum)
        raise OSError("could not activate endpoint volume")
    return enum, device, vol


def get_volume() -> tuple[int, bool]:
    """Return (percent 0-100, muted)."""
    enum, device, vol = _endpoint()
    try:
        level = ctypes.c_float()
        _method(vol, 9, ctypes.c_long, ctypes.POINTER(ctypes.c_float))(ctypes.byref(level))  # GetMasterVolumeLevelScalar
        muted = wintypes.BOOL()
        _method(vol, 15, ctypes.c_long, ctypes.POINTER(wintypes.BOOL))(ctypes.byref(muted))  # GetMute
        return int(round(level.value * 100)), bool(muted.value)
    finally:
        for o in (vol, device, enum):
            _release(o)


def set_volume(percent: int) -> int:
    percent = max(0, min(100, int(percent)))
    enum, device, vol = _endpoint()
    try:
        _method(vol, 7, ctypes.c_long, ctypes.c_float, ctypes.c_void_p)(percent / 100.0, None)  # SetMasterVolumeLevelScalar
        if percent > 0:
            _method(vol, 14, ctypes.c_long, wintypes.BOOL, ctypes.c_void_p)(False, None)  # SetMute(False)
        return percent
    finally:
        for o in (vol, device, enum):
            _release(o)


def set_mute(muted: bool) -> None:
    enum, device, vol = _endpoint()
    try:
        _method(vol, 14, ctypes.c_long, wintypes.BOOL, ctypes.c_void_p)(bool(muted), None)
    finally:
        for o in (vol, device, enum):
            _release(o)
