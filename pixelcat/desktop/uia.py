"""Read other apps' user interface through Windows UI Automation.

UI Automation is the accessibility API screen readers use: it lists a window's
buttons, fields, menus, tabs and links with their names and positions, and can
read a document's text exactly (no OCR guessing).  Implemented with plain ctypes
COM calls (vtable indices from UIAutomationClient.h) - no extra packages.

Every public function creates and releases its own COM objects, so it can run on
any thread (the chat runs these on a worker thread so the cat never freezes).
Read-only: nothing here clicks, types or changes anything.
"""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

ole32 = ctypes.windll.ole32
oleaut32 = ctypes.windll.oleaut32
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoUninitialize.argtypes = []
ole32.CoUninitialize.restype = None
ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.c_long
oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
oleaut32.SysFreeString.restype = None
oleaut32.SysStringLen.argtypes = [ctypes.c_void_p]
oleaut32.SysStringLen.restype = wintypes.UINT
oleaut32.VariantClear.argtypes = [ctypes.c_void_p]
oleaut32.VariantClear.restype = ctypes.c_long

COINIT_MULTITHREADED = 0x0
CLSCTX_INPROC_SERVER = 0x1
TreeScope_Children, TreeScope_Descendants, TreeScope_Subtree = 0x2, 0x4, 0x7
VT_EMPTY, VT_I4, VT_BSTR, VT_BOOL = 0, 3, 8, 11


class GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, s: str) -> "GUID":
        s = s.strip("{}")
        a, b, c, d, e = s.split("-")
        tail = bytes.fromhex(d + e)
        return cls(int(a, 16), int(b, 16), int(c, 16), (ctypes.c_ubyte * 8)(*tail))


CLSID_CUIAutomation = GUID.of("ff48dba4-60ef-4201-aa87-54103eef594e")
IID_IUIAutomation = GUID.of("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee")
IID_IUIAutomationTextPattern = GUID.of("32eba289-3583-42c9-9c59-3b6d9a1e9b6a")


class _VU(ctypes.Union):
    _fields_ = [("llVal", ctypes.c_longlong), ("lVal", ctypes.c_long), ("boolVal", ctypes.c_short),
                ("dblVal", ctypes.c_double), ("ptr", ctypes.c_void_p), ("rec", ctypes.c_void_p * 2)]


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("u", _VU)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


# ---- property / pattern / control type ids (UIAutomationClient.h) ----------------
P_BOUNDS, P_CONTROLTYPE, P_NAME = 30001, 30003, 30005
P_HASFOCUS, P_ENABLED, P_AUTOMATIONID = 30008, 30010, 30011
P_ISPASSWORD, P_OFFSCREEN = 30019, 30022
P_TEXTPATTERN_AVAILABLE, P_VALUE = 30040, 30045
P_TOGGLESTATE, P_EXPANDSTATE, P_SELECTED = 30086, 30070, 30079
PATTERN_TEXT = 10014

CONTROL_TYPES = {
    50000: "button", 50001: "calendar", 50002: "checkbox", 50003: "combobox", 50004: "edit", 50005: "link",
    50006: "image", 50007: "list item", 50008: "list", 50009: "menu", 50010: "menu bar", 50011: "menu item",
    50012: "progress bar", 50013: "radio button", 50014: "scroll bar", 50015: "slider", 50016: "spinner",
    50017: "status bar", 50018: "tab", 50019: "tab item", 50020: "text", 50021: "toolbar", 50022: "tooltip",
    50023: "tree", 50024: "tree item", 50025: "custom", 50026: "group", 50027: "thumb", 50028: "data grid",
    50029: "data item", 50030: "document", 50031: "split button", 50032: "window", 50033: "pane",
    50034: "header", 50035: "header item", 50036: "table", 50037: "title bar", 50038: "separator",
}
INTERACTIVE = (50000, 50002, 50003, 50004, 50005, 50007, 50011, 50013, 50015, 50016, 50019, 50024,
               50029, 50030, 50031, 50035)
READABLE = INTERACTIVE + (50020, 50017)

# ---- vtable indices -----------------------------------------------------------------
# IUIAutomation
_ElementFromHandle, _GetFocusedElement = 6, 8
_CreateCacheRequest, _CreateTrueCondition, _CreatePropertyCondition = 20, 21, 23
_CreateAndCondition, _CreateOrCondition = 25, 28
# IUIAutomationElement
_FindFirst, _FindAllBuildCache = 5, 8
_GetCurrentPropertyValue, _GetCachedPropertyValue, _GetCurrentPatternAs = 10, 12, 14
_CurControlType, _CurName, _CurHasFocus, _CurIsPassword, _CurBounds = 21, 23, 26, 35, 43
_CachedControlType, _CachedName, _CachedHasFocus, _CachedEnabled = 53, 55, 58, 60
_CachedIsPassword, _CachedBounds = 67, 75
# IUIAutomationCacheRequest
_AddProperty = 3
# IUIAutomationElementArray
_ArrLength, _ArrGet = 3, 4
# IUIAutomationTextPattern / IUIAutomationTextRange
_DocumentRange, _RangeGetText = 7, 12

_PROTOS: dict[tuple[Any, ...], Any] = {}


def _call(ptr: int, index: int, argtypes: tuple[Any, ...], *args: Any) -> int:
    """Call COM method ``index`` of interface pointer ``ptr``; raises OSError on failure HRESULTs."""
    key = (index, argtypes)
    proto = _PROTOS.get(key)
    if proto is None:
        proto = _PROTOS[key] = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    vtbl = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return proto(vtbl[index])(ptr, *args)


def _release(ptr: int | None) -> None:
    if ptr:
        vtbl = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(ptr)


def _out_ptr(ptr: int, index: int, argtypes: tuple[Any, ...] = (), *args: Any) -> int:
    out = ctypes.c_void_p()
    _call(ptr, index, argtypes + (ctypes.POINTER(ctypes.c_void_p),), *args, ctypes.byref(out))
    return out.value or 0


def _bstr(p: int) -> str:
    if not p:
        return ""
    try:
        return ctypes.wstring_at(p, oleaut32.SysStringLen(p))
    finally:
        oleaut32.SysFreeString(p)


def _get_bstr(ptr: int, index: int) -> str:
    out = ctypes.c_void_p()
    _call(ptr, index, (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(out))
    return _bstr(out.value or 0)


def _get_int(ptr: int, index: int) -> int:
    out = ctypes.c_int()
    _call(ptr, index, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(out))
    return out.value


def _get_rect(ptr: int, index: int) -> tuple[int, int, int, int]:
    r = RECT()
    _call(ptr, index, (ctypes.POINTER(RECT),), ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def _variant_str(ptr: int, index: int, prop: int) -> str:
    v = VARIANT()
    _call(ptr, index, (ctypes.c_int, ctypes.POINTER(VARIANT)), prop, ctypes.byref(v))
    try:
        if v.vt == VT_BSTR and v.u.ptr:
            return ctypes.wstring_at(v.u.ptr, oleaut32.SysStringLen(v.u.ptr))
        if v.vt == VT_I4:
            return str(v.u.lVal)
        if v.vt == VT_BOOL:
            return "true" if v.u.boolVal else "false"
        return ""
    finally:
        oleaut32.VariantClear(ctypes.byref(v))


@dataclass
class Element:
    id: int
    kind: str
    name: str
    rect: tuple[int, int, int, int]       # physical screen pixels
    value: str = ""
    enabled: bool = True
    focused: bool = False
    password: bool = False
    checked: bool | None = None           # checkboxes / toggle buttons; None = not a toggle

    @property
    def center(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return ((l + r) // 2, (t + b) // 2)

    def describe(self, origin: tuple[int, int] = (0, 0), scale: float = 1.0) -> str:
        cx, cy = self.center
        x, y = int((cx - origin[0]) * scale), int((cy - origin[1]) * scale)
        name = self.name.replace("\n", " ").strip()
        name = name if len(name) <= 60 else name[:57] + "..."
        bits = [f"[{self.id}] {self.kind}"]
        if name:
            bits.append(f"'{name}'")
        if self.value and not self.password and self.kind not in ("document",):
            v = self.value.replace("\n", " ")
            bits.append(f"value='{v[:50] + '...' if len(v) > 50 else v}'")
        if self.checked is not None:
            bits.append("(checked)" if self.checked else "(unchecked)")
        if self.focused:
            bits.append("(focused)")
        if not self.enabled:
            bits.append("(disabled)")
        if self.password:
            bits.append("(password field)")
        bits.append(f"at {x},{y}")
        return " ".join(bits)


@dataclass
class Snapshot:
    hwnd: int
    window_rect: tuple[int, int, int, int]
    elements: list[Element] = field(default_factory=list)
    focused: Element | None = None
    took_ms: float = 0.0


class Client:
    """One IUIAutomation instance on the current thread (use as a context manager)."""

    def __init__(self) -> None:
        hr = ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        self._uninit = hr in (0, 1)        # S_OK / S_FALSE; RPC_E_CHANGED_MODE -> already STA, fine
        out = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(CLSID_CUIAutomation), None, CLSCTX_INPROC_SERVER,
                                    ctypes.byref(IID_IUIAutomation), ctypes.byref(out))
        if hr < 0 or not out.value:
            if self._uninit:
                ole32.CoUninitialize()
            raise OSError(f"UI Automation is not available (0x{hr & 0xFFFFFFFF:08x})")
        self.ptr: int = out.value
        self._bag: list[int] = []

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        for p in reversed(self._bag):
            _release(p)
        self._bag.clear()
        _release(self.ptr)
        self.ptr = 0
        if self._uninit:
            ole32.CoUninitialize()
            self._uninit = False

    def _keep(self, p: int) -> int:
        if p:
            self._bag.append(p)
        return p

    # -- conditions -------------------------------------------------------------
    def _prop_cond(self, prop: int, value: int | bool) -> int:
        v = VARIANT()
        if isinstance(value, bool):
            v.vt, v.u.boolVal = VT_BOOL, (-1 if value else 0)
        else:
            v.vt, v.u.lVal = VT_I4, int(value)
        return self._keep(_out_ptr(self.ptr, _CreatePropertyCondition, (ctypes.c_int, VARIANT), prop, v))

    def _or(self, conds: list[int]) -> int:
        acc = conds[0]
        for c in conds[1:]:
            acc = self._keep(_out_ptr(self.ptr, _CreateOrCondition, (ctypes.c_void_p, ctypes.c_void_p), acc, c))
        return acc

    def _and(self, a: int, b: int) -> int:
        return self._keep(_out_ptr(self.ptr, _CreateAndCondition, (ctypes.c_void_p, ctypes.c_void_p), a, b))

    def element_from_handle(self, hwnd: int) -> int:
        return self._keep(_out_ptr(self.ptr, _ElementFromHandle, (wintypes.HWND,), hwnd))

    # -- queries ----------------------------------------------------------------
    def snapshot(self, hwnd: int, kinds: tuple[int, ...] = INTERACTIVE, limit: int = 150,
                 with_values: bool = True) -> Snapshot:
        """Visible elements of ``kinds`` inside window ``hwnd`` in reading order."""
        t0 = time.perf_counter()
        root = self.element_from_handle(hwnd)
        wr = _get_rect(root, _CurBounds)
        cache = self._keep(_out_ptr(self.ptr, _CreateCacheRequest))
        props = [P_NAME, P_CONTROLTYPE, P_BOUNDS, P_ENABLED, P_HASFOCUS, P_ISPASSWORD]
        if with_values:
            props += [P_VALUE, P_TOGGLESTATE]
        for prop in props:
            _call(cache, _AddProperty, (ctypes.c_int,), prop)
        cond = self._and(self._prop_cond(P_OFFSCREEN, False), self._or([self._prop_cond(P_CONTROLTYPE, k) for k in kinds]))
        arr = self._keep(_out_ptr(root, _FindAllBuildCache, (ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p),
                                  TreeScope_Descendants, cond, cache))
        n = _get_int(arr, _ArrLength) if arr else 0
        found: list[Element] = []
        for i in range(n):
            el = _out_ptr(arr, _ArrGet, (ctypes.c_int,), i)
            if not el:
                continue
            try:
                rect = _get_rect(el, _CachedBounds)
                if rect[2] - rect[0] < 2 or rect[3] - rect[1] < 2:
                    continue
                # keep only elements that are at least partly inside the window
                if rect[2] <= wr[0] or rect[0] >= wr[2] or rect[3] <= wr[1] or rect[1] >= wr[3]:
                    continue
                ctype = _get_int(el, _CachedControlType)
                pw = bool(_get_int(el, _CachedIsPassword))
                toggle = _variant_str(el, _GetCachedPropertyValue, P_TOGGLESTATE) if with_values else ""
                found.append(Element(0, CONTROL_TYPES.get(ctype, "element"), _get_bstr(el, _CachedName), rect,
                                     "" if pw or not with_values else _variant_str(el, _GetCachedPropertyValue, P_VALUE),
                                     bool(_get_int(el, _CachedEnabled)), bool(_get_int(el, _CachedHasFocus)), pw,
                                     (toggle == "1") if toggle in ("0", "1") else None))
            except OSError:
                continue
            finally:
                _release(el)
        found.sort(key=lambda e: (e.rect[1] // 12, e.rect[0]))   # rows of ~12 px, then left to right
        out: list[Element] = []
        for e in found:
            if not e.name and not e.value and e.kind in ("text", "list item", "data item", "custom"):
                continue
            e.id = len(out) + 1
            out.append(e)
            if len(out) >= limit:
                break
        snap = Snapshot(hwnd, wr, out, next((e for e in out if e.focused), None))
        snap.took_ms = (time.perf_counter() - t0) * 1000
        return snap

    def focused(self) -> Element | None:
        """The element that has keyboard focus (in any app)."""
        el = self._keep(_out_ptr(self.ptr, _GetFocusedElement))
        if not el:
            return None
        ctype = _get_int(el, _CurControlType)
        pw = bool(_get_int(el, _CurIsPassword))
        return Element(0, CONTROL_TYPES.get(ctype, "element"), _get_bstr(el, _CurName), _get_rect(el, _CurBounds),
                       "" if pw else _variant_str(el, _GetCurrentPropertyValue, P_VALUE), True, True, pw)

    def focused_text(self, max_chars: int = 50000) -> str | None:
        """Full text of the focused text field/document (None if it can't be read)."""
        el = self._keep(_out_ptr(self.ptr, _GetFocusedElement))
        if not el or _get_int(el, _CurIsPassword):
            return None
        try:
            pat = self._keep(_out_ptr(el, _GetCurrentPatternAs, (ctypes.c_int, ctypes.POINTER(GUID)),
                                      PATTERN_TEXT, ctypes.byref(IID_IUIAutomationTextPattern)))
        except OSError:
            pat = 0
        if pat:
            rng = self._keep(_out_ptr(pat, _DocumentRange))
            if rng:
                out = ctypes.c_void_p()
                _call(rng, _RangeGetText, (ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)), max_chars, ctypes.byref(out))
                return _bstr(out.value or 0)
        ctype = _get_int(el, _CurControlType)
        if ctype in (50004, 50030, 50003):  # edit, document, combobox: ValuePattern
            return _variant_str(el, _GetCurrentPropertyValue, P_VALUE)
        return None

    def document_text(self, hwnd: int, max_chars: int = 8000) -> str:
        """Text of the window's main document/editor (TextPattern), or ''."""
        root = self.element_from_handle(hwnd)
        cond = self._prop_cond(P_TEXTPATTERN_AVAILABLE, True)
        el = self._keep(_out_ptr(root, _FindFirst, (ctypes.c_int, ctypes.c_void_p), TreeScope_Subtree, cond))
        if not el:
            return ""
        if _get_int(el, _CurIsPassword):
            return ""
        pat = self._keep(_out_ptr(el, _GetCurrentPatternAs, (ctypes.c_int, ctypes.POINTER(GUID)),
                                  PATTERN_TEXT, ctypes.byref(IID_IUIAutomationTextPattern)))
        if not pat:
            return ""
        rng = self._keep(_out_ptr(pat, _DocumentRange))
        if not rng:
            return ""
        out = ctypes.c_void_p()
        _call(rng, _RangeGetText, (ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)), max_chars, ctypes.byref(out))
        return _bstr(out.value or 0)


def snapshot(hwnd: int, kinds: tuple[int, ...] = INTERACTIVE, limit: int = 150) -> Snapshot:
    with Client() as c:
        return c.snapshot(hwnd, kinds, limit)


def focused_element() -> Element | None:
    try:
        with Client() as c:
            return c.focused()
    except OSError:
        return None


def document_text(hwnd: int, max_chars: int = 8000) -> str:
    try:
        with Client() as c:
            return c.document_text(hwnd, max_chars)
    except OSError:
        log.debug("document_text failed", exc_info=True)
        return ""


def focused_text(max_chars: int = 50000) -> str | None:
    try:
        with Client() as c:
            return c.focused_text(max_chars)
    except OSError:
        return None
