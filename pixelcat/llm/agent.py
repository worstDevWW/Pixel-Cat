"""The chat's eyes and hands on the desktop.

* Eyes: ``look`` takes a screenshot (sent only to the local model) with numbered
  boxes on the clickable elements; ``read`` lists a window's controls and its
  document text through UI Automation (exact text, no OCR guessing).
* Hands: ``click``, ``type``, ``keys``, ``scroll`` via SendInput.

Guard rails (enforced here, not by the model):
* Every action targets one app window, which is brought to the front first.
  Typing and key presses stop at once if another window comes to the front
  (e.g. because the user clicked somewhere else) or the user presses Esc.
* Clicks must land on the target app itself - never on another app that
  happens to cover the spot.  The cat and its chat let clicks pass through.
* Password fields are never typed into; apps running as administrator are left
  alone (Windows blocks that anyway); command lines and the Run box always need
  the user's OK, even in auto mode (decided in tools.py).

Everything runs on a worker thread so the cat keeps animating.
"""
from __future__ import annotations

import ctypes
import logging
import re as _re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from ..desktop import capture, control, inputs, uia, win32
from ..desktop.control import AppWindow
from ..settings import Config

log = logging.getLogger(__name__)

CODE_EDITORS = {"code.exe", "code - insiders.exe", "cursor.exe", "devenv.exe", "notepad++.exe", "sublime_text.exe",
                "idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe", "clion64.exe", "atom.exe"}
PLAIN_TEXT_APPS = CODE_EDITORS | {"notepad.exe", "notepad2.exe", "notepad3.exe", "notepads.exe", "wordpad.exe"}
RICH_HTML_APPS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "teams.exe",
                  "ms-teams.exe", "slack.exe", "discord.exe", "outlook.exe", "olk.exe", "winword.exe", "onenote.exe",
                  "powerpnt.exe", "excel.exe", "thunderbird.exe", "whatsapp.exe"}
COMMAND_LINES = {"windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe", "openconsole.exe",
                 "wsl.exe", "bash.exe", "mintty.exe", "regedit.exe", "powershell_ise.exe", "mmc.exe"}


class AgentError(Exception):
    """A desktop action could not be done; the message is shown to the user and the model."""


@dataclass
class ToolOutput:
    text: str                                   # what the model gets
    images: list[str] = field(default_factory=list)
    display: str | None = None                  # short line for the chat (default: text)


@dataclass
class Shot:
    hwnd: int                       # 0 = a whole monitor
    origin: tuple[int, int]         # screen position of the image's top-left pixel
    scale: float                    # image pixels per screen pixel
    size: tuple[int, int]


def _virtual_screen() -> tuple[int, int, int, int]:
    gm = win32.user32.GetSystemMetrics
    x, y = gm(76), gm(77)
    return (x, y, x + gm(78), y + gm(79))


win32.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
win32.user32.GetSystemMetrics.restype = ctypes.c_int


def _clip(r: tuple[int, int, int, int], to: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return (max(r[0], to[0]), max(r[1], to[1]), min(r[2], to[2]), min(r[3], to[3]))


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = win32.frame_bounds(hwnd)
    if r is None:
        rc = win32.RECT()
        win32.user32.GetWindowRect(hwnd, ctypes.byref(rc))
        r = (rc.left, rc.top, rc.right, rc.bottom)
    return r


class DesktopAgent:
    def __init__(self, cfg: Config, own_pid: int) -> None:
        self.cfg = cfg
        self.own_pid = own_pid
        self.cancel = threading.Event()
        self.overlay_hwnd = 0
        self.last_hwnd = 0
        self.snap: uia.Snapshot | None = None
        self.shot: Shot | None = None
        self._uia_busy: dict[int, threading.Thread] = {}

    # ================================================================ helpers
    def _uia_snapshot(self, hwnd: int, kinds: tuple[int, ...] = uia.INTERACTIVE, limit: int = 80,
                      timeout: float = 4.0) -> uia.Snapshot | None:
        """UI Automation snapshot, given up after ``timeout`` s (some apps build huge trees)."""
        busy = self._uia_busy.get(hwnd)
        if busy is not None and busy.is_alive():
            return None   # the last request for this window is still running
        box: list[object] = []

        def work() -> None:
            try:
                box.append(uia.snapshot(hwnd, kinds, limit))
            except Exception as exc:  # noqa: BLE001
                box.append(exc)

        th = threading.Thread(target=work, daemon=True)
        self._uia_busy[hwnd] = th
        th.start()
        th.join(timeout)
        if th.is_alive():
            log.info("UI Automation too slow for %s - continuing without an element list", self.describe_hwnd(hwnd))
            return None
        res = box[0] if box else None
        return res if isinstance(res, uia.Snapshot) else None

    def _window_image(self, hwnd: int):  # type: ignore[no-untyped-def]
        """The window's pixels (drawn by the window itself if possible)."""
        frame = window_rect(hwnd)
        rect = _clip(frame, _virtual_screen())
        img = capture.grab_window(hwnd, frame) if rect == frame else None
        if img is None and rect[2] - rect[0] > 4 and rect[3] - rect[1] > 4:
            img = capture.grab_without(rect, self.own_pid)
        return img, rect

    def _fingerprint(self, hwnd: int) -> bytes | None:
        """Small grayscale picture of the window, to notice whether anything changed."""
        try:
            img, _r = self._window_image(hwnd)
        except Exception:  # noqa: BLE001
            return None
        if img is None:
            return None
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QImage as _QImage

        small = img.scaled(400, 300, _Qt.AspectRatioMode.IgnoreAspectRatio,
                           _Qt.TransformationMode.FastTransformation).convertToFormat(_QImage.Format.Format_Grayscale8)
        ptr = small.constBits()
        return bytes(ptr)[: small.bytesPerLine() * small.height()]

    @staticmethod
    def _changed(a: bytes | None, b: bytes | None) -> bool | None:
        """True if two fingerprints differ by more than a blinking caret would."""
        if a is None or b is None or len(a) != len(b):
            return None
        diff = sum(1 for x, y in zip(a, b) if abs(x - y) > 30)
        return diff > 40

    def _shot_output(self, hwnd: int, text: str, display: str) -> ToolOutput:
        """A tool result with a fresh screenshot of the window, so the model can check it."""
        img, rect = self._window_image(hwnd)
        if img is None:
            return ToolOutput(text, display=display)
        img, scale = capture.fit(img, self.cfg.vision_max_px)
        self.shot = Shot(hwnd, (rect[0], rect[1]), scale, (img.width(), img.height()))
        return ToolOutput(text, [capture.to_base64_png(img)], display=display)

    def wait_until_drawn(self, hwnd: int, max_s: float = 15.0) -> float:
        """Wait until a starting app's window stops changing (splash screens, loading)."""
        t0 = time.time()
        last = self._fingerprint(hwnd)
        calm = 0
        while time.time() - t0 < max_s and not self.cancel.is_set():
            time.sleep(0.5)
            now = self._fingerprint(hwnd)
            changed = self._changed(last, now)
            calm = calm + 1 if changed is False else 0
            last = now
            if calm >= 3 and time.time() - t0 >= 1.5:
                break
        return time.time() - t0

    # ================================================================ windows
    def windows(self) -> list[AppWindow]:
        return control.list_app_windows(self.own_pid)

    def describe_hwnd(self, hwnd: int) -> str:
        exe = control.process_exe(win32.window_pid(hwnd)) or "app"
        app = exe[:-4] if exe.lower().endswith(".exe") else exe
        title = win32.window_text(hwnd) or "(untitled)"
        return f"{app}: '{title if len(title) <= 70 else title[:67] + '...'}'"

    def resolve(self, target: str | None) -> AppWindow:
        """The window an action is meant for: the named one, else the one the cat
        worked with last, else the app the user was using before opening the chat."""
        wins = self.windows()
        if target and str(target).strip():
            hits = control.find_windows(str(target), wins)
            if not hits:
                raise AgentError(f"no open window matches '{target}' (open windows: "
                                 + ", ".join(w.label() for w in wins[:8]) + ")")
            for w in hits:
                if w.hwnd == self.last_hwnd:
                    return w
            return next((w for w in hits if not w.minimized), hits[0])
        for w in wins:
            if w.hwnd == self.last_hwnd:
                return w
        for w in wins:
            if not w.minimized:
                return w
        raise AgentError("no app window is open")

    def exe_of(self, hwnd: int) -> str:
        return control.process_exe(win32.window_pid(hwnd)).lower()

    def is_command_line(self, hwnd: int) -> bool:
        """Terminals, consoles, registry editor - and the Win+R 'Run' box."""
        hwnd = inputs.active_popup(hwnd)
        exe = self.exe_of(hwnd)
        if exe in COMMAND_LINES:
            return True
        return exe == "explorer.exe" and win32.class_name(hwnd) == "#32770"

    def _focus(self, hwnd: int) -> int:
        """Bring the window (or its open dialog) to the front; returns the window that has focus."""
        if not win32.user32.IsWindow(hwnd):
            raise AgentError("that window is gone (it was closed)")
        target = inputs.active_popup(hwnd)
        if not inputs.bring_to_front(target):
            if not inputs.is_foreground(target):
                raise AgentError(f"I couldn't bring {self.describe_hwnd(target)} to the front - "
                                 "please click on it once, then ask again")
        self.last_hwnd = hwnd
        time.sleep(0.12)
        return target

    def _check_input_allowed(self, hwnd: int) -> None:
        pid = win32.window_pid(hwnd)
        if inputs.is_elevated(pid) and not inputs.self_elevated():
            raise AgentError(f"{self.describe_hwnd(hwnd)} runs as administrator - Windows doesn't let me "
                             "type or click in it (and I won't ask for admin rights for that)")

    def after(self, settle: float = 0.2) -> str:
        """Short description of what's in front now (helps the model notice dialogs)."""
        time.sleep(settle)
        from ..desktop import elevation

        if elevation.uac_prompt_open():
            return (" Windows is now showing its admin-rights prompt (UAC). Only the user can answer it - "
                    "stop here and tell the user; never try to click it.")
        fg = int(win32.user32.GetForegroundWindow() or 0)
        if not fg or win32.window_pid(fg) == self.own_pid:
            return ""
        text = f" Now in front: {self.describe_hwnd(fg)}."
        el = uia.focused_element()
        if el is not None and el.kind in ("edit", "document", "combobox"):
            text += f" Keyboard focus: {el.kind}{(' ' + repr(el.name[:40])) if el.name else ''}."
        return text

    # ================================================================ eyes
    def look(self, hwnd: int | None) -> ToolOutput:
        # Looking is read-only: the window is NOT brought to the front (that would be an action).
        snap: uia.Snapshot | None = None
        img = None
        if hwnd:
            if not win32.user32.IsWindow(hwnd):
                raise AgentError("that window is gone (it was closed)")
            if win32.user32.IsIconic(hwnd):
                raise AgentError(f"{self.describe_hwnd(hwnd)} is minimized - restore it first "
                                 "(window_action restore), then look again")
            focus = inputs.active_popup(hwnd)
            if win32.user32.IsHungAppWindow(focus):
                raise AgentError(f"{self.describe_hwnd(focus)} is not responding right now")
            frame = window_rect(focus)
            rect = _clip(frame, _virtual_screen())
            label = self.describe_hwnd(focus)
            snap = self._uia_snapshot(focus, limit=self.cfg.vision_max_elements)
            shot_hwnd = focus
            self.last_hwnd = hwnd
            if rect == frame:   # fully on screen: draw the window itself, even if something covers it
                img = capture.grab_window(focus, frame)
        else:
            wins = [w for w in self.windows() if not w.minimized]
            top = wins[0] if wins else None
            cx, cy = win32.cursor_pos()
            if top is not None:
                r = window_rect(top.hwnd)
                cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
            mon = control_monitor(cx, cy)
            rect = mon
            label = "the whole screen"
            if top is not None:
                snap = self._uia_snapshot(top.hwnd, limit=self.cfg.vision_max_elements)
            shot_hwnd = 0
        if rect[2] - rect[0] < 4 or rect[3] - rect[1] < 4:
            raise AgentError("that window is not visible on any screen")
        if img is None:
            img = capture.grab_without(rect, self.own_pid)
        img, scale = capture.fit(img, self.cfg.vision_max_px)
        ox, oy = rect[0], rect[1]
        lines: list[str] = []
        marks: list[tuple[int, int, int, int, int]] = []
        if snap is not None:
            for e in snap.elements:
                l, t, r, b = e.rect
                if r <= rect[0] or l >= rect[2] or b <= rect[1] or t >= rect[3]:
                    continue
                marks.append((e.id, int((l - ox) * scale), int((t - oy) * scale), int((r - ox) * scale),
                              int((b - oy) * scale)))
                lines.append(e.describe((ox, oy), scale))
        if snap is None and hwnd:
            lines = []
        if self.cfg.vision_marks and marks:
            capture.draw_marks(img, marks)
        self.snap = snap
        self.shot = Shot(shot_hwnd, (ox, oy), scale, (img.width(), img.height()))
        text = f"Screenshot of {label}, {img.width()}x{img.height()} px."
        if lines:
            text += (" Pink numbered boxes mark the clickable elements (use click with element=ID):\n"
                     + "\n".join(lines))
        else:
            text += " (No element list for this window - use x/y pixel positions in this image to click.)"
        if not hwnd:
            text += "\nOpen windows: " + " | ".join(w.label() for w in self.windows()[:12])
        return ToolOutput(text, [capture.to_base64_png(img)])

    def read(self, hwnd: int) -> str:
        """Read-only: never changes the window (a minimized window is read as it is)."""
        if not win32.user32.IsWindow(hwnd):
            raise AgentError("that window is gone (it was closed)")
        target = inputs.active_popup(hwnd)
        if win32.user32.IsHungAppWindow(target):
            raise AgentError(f"{self.describe_hwnd(target)} is not responding right now")
        snap = self._uia_snapshot(target, uia.READABLE, limit=self.cfg.read_max_elements, timeout=6.0)
        if snap is None:
            raise AgentError(f"{self.describe_hwnd(target)} doesn't let me read its contents (or is too slow) - "
                             "use look_at_screen instead")
        self.snap = snap
        self.last_hwnd = hwnd
        doc = uia.document_text(target, self.cfg.read_max_chars)
        if not doc:
            boxes = [e for e in snap.elements if e.kind in ("document", "edit") and e.value and not e.password]
            if boxes:
                doc = max(boxes, key=lambda e: len(e.value)).value[: self.cfg.read_max_chars]
        lines = [e.describe() for e in snap.elements]
        lines = [ln.rsplit(" at ", 1)[0] for ln in lines]
        out = f"Window {self.describe_hwnd(target)}" + (" (minimized)." if win32.user32.IsIconic(target) else ".")
        if snap.focused is not None:
            out += f" Keyboard focus is on [{snap.focused.id}]."
        out += "\nElements (use click with element=ID):\n" + ("\n".join(lines) if lines else "(none found)")
        if doc:
            cut = len(doc) >= self.cfg.read_max_chars
            out += f"\n\nText content{' (beginning)' if cut else ''}:\n\"\"\"\n{doc}\n\"\"\""
        return out

    # ================================================================ hands
    def element(self, eid: int) -> tuple[uia.Element, int]:
        """Element ``eid`` from the latest look/read, re-located in case the window moved."""
        if self.snap is None:
            raise AgentError("I need to look at the window first (look_at_screen or read_window)")
        old = next((e for e in self.snap.elements if e.id == eid), None)
        if old is None:
            raise AgentError(f"there is no element [{eid}] in my last look - look again")
        hwnd = self.snap.hwnd
        if not win32.user32.IsWindow(hwnd):
            raise AgentError("that window is gone (it was closed)")
        return old, hwnd

    def _relocate(self, old: uia.Element, hwnd: int) -> uia.Element:
        snap = self._uia_snapshot(hwnd, uia.READABLE, limit=400, timeout=3.0)
        if snap is None:
            return old
        fresh = snap.elements
        same = [e for e in fresh if e.kind == old.kind and e.name == old.name]
        if not same:
            return old
        ox, oy = old.center
        return min(same, key=lambda e: abs(e.center[0] - ox) + abs(e.center[1] - oy))

    @contextmanager
    def _passthrough(self) -> Iterator[None]:
        """Let clicks fall through the cat and its chat while we click."""
        changed: list[int] = []
        inputs.passthrough_until = time.monotonic() + 3.0
        own: list[int] = []

        def _cb(h, _lp):  # type: ignore[no-untyped-def]
            if win32.user32.IsWindowVisible(h) and win32.window_pid(h) == self.own_pid and h != self.overlay_hwnd:
                own.append(int(h))
            return True

        win32.user32.EnumWindows(win32.WNDENUMPROC(_cb), 0)
        for h in own:
            ex = win32.get_exstyle(h)
            if ex & win32.WS_EX_LAYERED and not ex & win32.WS_EX_TRANSPARENT:
                win32.set_exstyle(h, ex | win32.WS_EX_TRANSPARENT)
                changed.append(h)
        time.sleep(0.09)  # the cat's 25 Hz hover check switches it to click-through
        try:
            yield
        finally:
            for h in changed:
                if win32.user32.IsWindow(h):
                    win32.set_exstyle(h, win32.get_exstyle(h) & ~win32.WS_EX_TRANSPARENT)
            inputs.passthrough_until = 0.0

    def click(self, eid: int | None, x: float | None, y: float | None, hwnd: int | None,
              button: str = "left", double: bool = False, quiet: bool = False) -> str:
        what = ""
        if eid is not None:
            old, hwnd = self.element(eid)
            self._check_input_allowed(hwnd)
            self._focus(hwnd)
            el = self._relocate(old, hwnd)
            px, py = el.center
            what = f"[{eid}] {el.kind}{(' ' + repr(el.name[:50])) if el.name else ''}"
        else:
            if self.shot is None or x is None or y is None:
                raise AgentError("give an element id, or x and y from a screenshot (look_at_screen first)")
            sw, sh = self.shot.size
            if not (0 <= x <= sw and 0 <= y <= sh):
                raise AgentError(f"x/y must be inside the last screenshot ({sw}x{sh})")
            px = int(self.shot.origin[0] + x / self.shot.scale)
            py = int(self.shot.origin[1] + y / self.shot.scale)
            hwnd = hwnd or self.shot.hwnd or None
            if hwnd:
                self._check_input_allowed(hwnd)
                self._focus(hwnd)
            what = f"the spot {int(x)},{int(y)}"
        vs = _virtual_screen()
        if not (vs[0] <= px < vs[2] and vs[1] <= py < vs[3]):
            raise AgentError("that spot is off-screen")
        with self._passthrough():
            at = inputs.window_at(px, py)
            if at and win32.window_pid(at) == self.own_pid:
                raise AgentError("my own chat window covers that spot - move the chat aside and ask again")
            if hwnd and at and not inputs.same_app(at, hwnd):
                raise AgentError(f"{self.describe_hwnd(at)} covers that spot, so I didn't click")
            if not hwnd and at:
                self._check_input_allowed(at)
            old_pos = win32.cursor_pos()
            inputs.click(px, py, button, double)
            time.sleep(0.05)
        if win32.cursor_pos() == (px, py) and button == "left":
            inputs.move_cursor(*old_pos)  # put the pointer back where the user left it
        verb = {"left": "Clicked", "right": "Right-clicked", "middle": "Middle-clicked"}[button]
        if double:
            verb = "Double-clicked"
        state = ""
        if eid is not None and el.checked is not None and hwnd:
            time.sleep(0.25)
            now = self._relocate(el, hwnd)
            if now.checked is not None:
                state = f" It is now {'checked' if now.checked else 'unchecked'}."
        if quiet:   # clicking into a field before typing: wait until the field really has the focus
            end = time.time() + 0.4
            while time.time() < end:
                time.sleep(0.05)
                f = uia.focused_element()
                if f is not None and f.kind in ("edit", "document", "combobox"):
                    break
            return ""
        return f"{verb} {what} in {self.describe_hwnd(hwnd or at)}.{state}" + self.after()

    def type(self, text: str, hwnd: int, eid: int | None = None, method: str = "auto") -> str | ToolOutput:
        if eid is not None:
            self.click(eid, None, None, None, quiet=True)
            hwnd = self.snap.hwnd if self.snap else hwnd
        self._check_input_allowed(hwnd)
        target = self._focus(hwnd)
        el = uia.focused_element()
        if el is not None and el.password:
            raise AgentError("the keyboard focus is on a password field - I never type passwords")
        multiline = "\n" in text
        if method == "auto":
            # Anything but a few characters is pasted: exact and fast in every app, and new lines
            # arrive as text - typing them as Enter could send a chat message or submit a form.
            method = "type" if len(text) <= 12 and not multiline else "paste"
        label = self.describe_hwnd(target)
        before_txt = uia.focused_text()
        before_img = self._fingerprint(target)
        saved = None
        if method == "paste":
            saved = inputs.backup_clipboard()
            if saved is None:
                if multiline:
                    raise AgentError("the clipboard is busy right now, and typing several lines key by key could "
                                     "press Enter in the wrong place - try again in a moment")
                method = "type"   # clipboard busy or huge: type instead (slower, still exact)
        if method == "paste":
            if not inputs.set_clipboard_private_text(text):
                inputs.write_clipboard(saved or [], private=False)
                raise AgentError("the clipboard is busy - try again")
            try:
                if not inputs.is_foreground(target):
                    raise AgentError(f"{label} is no longer in front, so I stopped")
                inputs.press_combo(inputs.parse_combo("ctrl+v"))
                self._wait_for_text(text, before_txt)   # restore the clipboard only once the app has it
            finally:
                if saved:
                    inputs.write_clipboard(saved)
                else:
                    inputs.clear_clipboard()
            how = "Pasted"
        else:
            typed = inputs.type_text(text, lambda: inputs.is_foreground(target), self.cancel,
                                     chunk=max(1, self.cfg.typing_chunk))
            if typed < len(text):
                why = "you pressed Esc / Stop" if self.cancel.is_set() else f"{label} was no longer in front"
                return f"Stopped typing after {typed} of {len(text)} characters because {why}."
            how = "Typed"
        return self._confirm_written(text, target, label, how, before_txt, before_img)

    def _confirm_written(self, text: str, target: str | int, label: str, how: str, before_txt: str | None,
                         before_img: bytes | None) -> str | ToolOutput:
        """Never report success blindly: read the text back, or compare the window before/after."""
        hwnd = int(target)
        check = self._verify(text, before_txt)
        if check == "unknown":       # the app may still be busy: one more look
            time.sleep(0.3)
            check = self._verify(text, before_txt)
        if check in ("exact", "tail"):
            # show the model how the field ends now, so it notices e.g. missing line breaks
            now = (uia.focused_text() or "").replace("\r\n", "\n").replace("\r", "\n")
            last = now.rstrip("\n").split("\n")[-3:] if now.strip() else []
            shown = ("\nThe last lines of the field are now (one per line):\n" + "\n".join(
                f"  | {ln[-100:]}" for ln in last) + "\n") if last else ""
            return (f"{how} {len(text)} characters into {label}. Checked: the text arrived"
                    + (" exactly." if check == "exact" else " (its end is visible).") + shown + self.after(0.05))
        focus = uia.focused_element()
        where = f"{focus.kind} {focus.name[:50]!r}" if focus is not None else "unknown"
        if check == "differs":
            raise AgentError(f"the text in {label} does not match what I sent (keyboard focus: {where}). "
                             "Look at the window and fix it, or tell the user")
        changed = self._changed(before_img, self._fingerprint(hwnd))
        if changed is False:
            raise AgentError(f"nothing changed in {label} - the keyboard focus is not in a text field "
                             f"(focus: {where}). Open or click the right text area first (in editors press "
                             "ctrl+n for a new file), then try again")
        msg = (f"{how} {len(text)} characters into {label}, but this app does not let me read text back. "
               "Here is a screenshot of the window now - CHECK where the text landed (e.g. in the editor, not in a "
               "chat panel or search box) before you tell the user it worked." + self.after(0.2))
        return self._shot_output(hwnd, msg, f"{how} {len(text)} characters into {label} (checking with a screenshot)")

    @staticmethod
    def _wait_for_text(text: str, before: str | None, max_s: float = 0.8) -> None:
        """After pasting: return as soon as the text shows up in the field (then the app has read
        the clipboard).  Apps that hide their text get the full ``max_s``."""
        if before is None:
            time.sleep(max_s)
            return
        norm = lambda t: t.replace("\r\n", "\n").replace("\r", "\n")  # noqa: E731
        want = norm(text).strip()
        end = time.time() + max_s
        while time.time() < end:
            time.sleep(0.05)
            now = uia.focused_text()
            if now is not None and want in norm(now):
                time.sleep(0.05)
                return
        return

    @staticmethod
    def _verify(text: str, before: str | None) -> str:
        """Read the focused field back (UI Automation): 'exact', 'tail' (end of the text visible,
        e.g. editors that only expose the lines around the cursor), 'unchanged', 'differs', 'unknown'."""
        time.sleep(0.05)
        after = uia.focused_text()
        if after is None:
            return "unknown"
        norm = lambda t: t.replace("\r\n", "\n").replace("\r", "\n")  # noqa: E731
        if norm(text).strip() in norm(after):
            return "exact"
        if before is not None and norm(after) == norm(before):
            return "unchanged"
        lines = [ln.strip() for ln in norm(text).split("\n") if len(ln.strip()) >= 4]
        if lines and lines[-1] in norm(after) and (len(lines) < 2 or lines[-2] in norm(after)):
            return "tail"
        return "differs"

    # ---------------------------------------------------------------- editing existing text
    def _copy_all(self, target: int) -> str | None:
        """Select everything in the focused editor and copy it (the exact text, even from editors
        that hide it from UI Automation, like VS Code).  Leaves everything selected."""
        seq = inputs.clipboard_sequence()
        inputs.press_combo(inputs.parse_combo("ctrl+a"))
        time.sleep(0.08)
        inputs.press_combo(inputs.parse_combo("ctrl+c"))
        end = time.time() + 1.5
        while time.time() < end:
            time.sleep(0.05)
            if inputs.clipboard_sequence() != seq:
                time.sleep(0.05)
                if inputs.clipboard_has_format(15):   # files, not text: this is not an editor
                    return None
                return inputs.get_clipboard_text()
        return None

    @staticmethod
    def find_span(doc: str, old: str, replace_all: bool = False) -> list[tuple[int, int]]:
        """Where ``old`` occurs in ``doc`` (both with \\n line ends).  Exact match first; else
        tolerate different amounts of spaces/tabs/line breaks.  Raises AgentError if it is missing
        or (without replace_all) not unique."""
        spans = [(m.start(), m.end()) for m in _re.finditer(_re.escape(old), doc)]
        if not spans:   # same words, different amount of spaces/line breaks
            words = [w for w in _re.split(r"\s+", old.strip()) if w]
            if words:
                pattern = r"\s+".join(_re.escape(w) for w in words)
                spans = [(m.start(), m.end()) for m in _re.finditer(pattern, doc)]
        if not spans:   # spaces missing or added (e.g. "(b,a)" read off a screenshot as "(b, a)")
            bare = _re.sub(r"\s+", "", old)
            if len(bare) >= 6:
                pos = [i for i, ch in enumerate(doc) if not ch.isspace()]
                flat = "".join(doc[i] for i in pos)
                found = [m.start() for m in _re.finditer(_re.escape(bare), flat)]
                spans = [(pos[f], pos[f + len(bare) - 1] + 1) for f in found]
        if not spans:
            preview = doc if len(doc) <= 1500 else doc[:1500] + "\n..."
            raise AgentError(f"I can't find {old[:80]!r} in the document. Its current text is:\n{preview}\n"
                             "Use an exact piece of that text as 'old'")
        if len(spans) > 1 and not replace_all:
            raise AgentError(f"{old[:80]!r} appears {len(spans)} times - include more of the surrounding text "
                             "so it is unique (or set replace_all)")
        return spans

    def replace(self, hwnd: int, old: str, new: str, replace_all: bool = False) -> str:
        """Change existing text in an editor: copy its whole text, replace ``old`` with ``new``,
        paste it back over the selection and copy again to check every character."""
        self._check_input_allowed(hwnd)
        target = self._focus(hwnd)
        label = self.describe_hwnd(target)
        el = uia.focused_element()
        if el is not None and el.password:
            raise AgentError("the keyboard focus is on a password field - I never touch passwords")
        if el is None or el.kind not in ("edit", "document"):
            where = f"{el.kind} {el.name[:40]!r}" if el is not None else "nothing"
            raise AgentError(f"the keyboard focus in {label} is not in a text editor (it's on {where}) - "
                             "click into the text first")
        saved = inputs.backup_clipboard()
        if saved is None:
            raise AgentError("the clipboard is busy right now - try again in a moment")
        exe = self.exe_of(target)
        selected = False
        try:
            raw = self._copy_all(target)
            selected = True
            if raw is None:
                raise AgentError(f"I couldn't copy the text of {label} - is the keyboard focus in the editor?")
            # Plain editors (VS Code, Notepad, ...) also copy an HTML version; real formatting shows up as
            # Rich Text Format (Word, WordPad, Outlook) or as HTML in browsers/office/chat apps.
            rich = exe not in PLAIN_TEXT_APPS and (inputs.clipboard_has_format("Rich Text Format") or (
                inputs.clipboard_has_format("HTML Format") and exe in RICH_HTML_APPS))
            if rich:
                raise AgentError(f"{label} holds formatted text - replace_text only works in plain-text editors "
                                 "(Notepad, VS Code...), it would lose the formatting here")
            crlf = "\r\n" in raw
            doc = raw.replace("\r\n", "\n").replace("\r", "\n")
            old_n = old.replace("\r\n", "\n").replace("\r", "\n")
            new_n = new.replace("\r\n", "\n").replace("\r", "\n")
            spans = self.find_span(doc, old_n, replace_all)
            out, pos = [], 0
            for a, b in spans:
                out += [doc[pos:a], new_n]
                pos = b
            result = "".join(out) + doc[pos:]
            paste = result.replace("\n", "\r\n") if crlf else result
            if not inputs.is_foreground(target):
                raise AgentError(f"{label} is no longer in front, so I stopped")
            if paste:                                          # everything is still selected
                inputs.set_clipboard_private_text(paste)
                inputs.press_combo(inputs.parse_combo("ctrl+v"))
            else:                                              # nothing left: pasting "" would do nothing
                inputs.press_combo(inputs.parse_combo("delete"))
            time.sleep(0.4)
            check = self._copy_all(target)
            if check is None and not result.strip():
                check = ""                                     # an empty editor has nothing to copy
            ok = check is not None and check.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") == result.rstrip("\n")
        finally:
            if selected and inputs.is_foreground(target):
                inputs.press_combo(inputs.parse_combo("ctrl+end"))   # never leave the whole text selected
            inputs.write_clipboard(saved)
        n = len(spans)
        what = f"{n} place{'s' if n != 1 else ''}"
        if not ok:
            raise AgentError(f"I replaced the text in {label}, but reading it back it doesn't match exactly "
                             "(the editor may have reformatted it) - look at it and fix it if needed; "
                             "ctrl+z undoes the change")
        return (f"Replaced {old[:60]!r} with {new[:60]!r} in {label} ({what}). Checked: the whole text is exactly "
                "as intended. (ctrl+z would undo it.)" + self.after(0.05))

    def keys(self, combos: list[tuple[str, list[int]]], hwnd: int) -> str:
        self._check_input_allowed(hwnd)
        target = self._focus(hwnd)
        done: list[str] = []
        for name, vks in combos:
            if self.cancel.is_set():
                break
            if not inputs.is_foreground(target):
                # Only the same app may have come to the front (e.g. its "Save as" dialog opened by a key).
                break
            inputs.press_combo(vks)
            done.append(name)
            time.sleep(0.12)
        if len(done) < len(combos):
            why = "you pressed Esc / Stop" if self.cancel.is_set() else "another app came to the front"
            return f"Pressed {', '.join(done) or 'nothing'}; stopped before {combos[len(done)][0]} because {why}."
        return f"Pressed {', '.join(done)} in {self.describe_hwnd(target)}." + self.after()

    def scroll(self, direction: str, amount: int, hwnd: int, eid: int | None = None) -> str:
        if eid is not None:
            old, hwnd = self.element(eid)
            self._check_input_allowed(hwnd)
            self._focus(hwnd)
            px, py = self._relocate(old, hwnd).center
        else:
            self._check_input_allowed(hwnd)
            self._focus(hwnd)
            r = window_rect(inputs.active_popup(hwnd))
            px, py = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
        clicks = max(1, min(30, int(amount)))
        sign = 1 if direction in ("up", "left") else -1
        with self._passthrough():
            at = inputs.window_at(px, py)
            if at and not inputs.same_app(at, hwnd):
                raise AgentError(f"{self.describe_hwnd(at)} covers that spot, so I didn't scroll")
            old_pos = win32.cursor_pos()
            inputs.scroll(px, py, sign * clicks, horizontal=direction in ("left", "right"))
        inputs.move_cursor(*old_pos)
        return f"Scrolled {direction} {clicks}x in {self.describe_hwnd(hwnd)}." + self.after(0.25)

    def wait(self, seconds: float) -> str:
        end = time.time() + seconds
        while time.time() < end and not self.cancel.is_set():
            time.sleep(0.1)
        return f"Waited {seconds:.1f} s." + self.after(0.0)

    def wait_for_window(self, before: set[int], name: str, timeout: float = 15.0) -> str:
        """After launching an app: find its new window, wait until it has finished loading
        (keys sent to a half-started app get lost) and remember it as the target."""
        end = time.time() + timeout
        key = name.lower().split()[0] if name else ""
        while time.time() < end and not self.cancel.is_set():
            time.sleep(0.25)
            new = [w for w in self.windows() if w.hwnd not in before and not w.minimized]
            if new:
                best = next((w for w in new if key and (key in w.app.lower() or key in w.title.lower())), new[0])
                self.last_hwnd = best.hwnd
                inputs.bring_to_front(best.hwnd, timeout=0.8)
                waited = self.wait_until_drawn(best.hwnd, max_s=max(3.0, end - time.time()))
                inputs.bring_to_front(best.hwnd, timeout=0.8)
                label = self.describe_hwnd(best.hwnd) if win32.user32.IsWindow(best.hwnd) else best.label()
                return f" Its window is ready and in front ({waited:.0f} s to load): {label}."
        fg = int(win32.user32.GetForegroundWindow() or 0)
        if fg and win32.window_pid(fg) != self.own_pid and fg not in before:
            self.last_hwnd = fg
            return f" In front now: {self.describe_hwnd(fg)}."
        return " (I don't see a new window yet - it may still be starting, or it reused an open window.)"


def control_monitor(x: int, y: int) -> tuple[int, int, int, int]:
    from ..desktop.monitors import enumerate_monitors, monitor_at

    return tuple(monitor_at(enumerate_monitors(), x, y).rect)  # type: ignore[return-value]
