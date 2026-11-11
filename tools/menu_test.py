"""Right-click menu test (developer tool), rendered offscreen - the menu is never shown.

Checks the layout (Pause, Chat and Quit on top; Minigames, Cosmetics and Settings as
sections that fold open, one at a time), that a click on a game or action closes the menu
and does it, that a click on a setting toggles it and keeps the menu open with the new
state, the Cat Pass locks (games, skins, hats), the first-time game explanation, and
keyboard use.  No game is started on screen (that's games_ui_test.py).
Doesn't touch real settings ("Start with Windows" is only checked, not toggled).
Saves build/preview/menu_closed.png, menu_open.png, menu_cosmetics.png.
Usage:  python tools/menu_test.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pixelcat.desktop import win32  # noqa: E402
from pixelcat.logsetup import setup_logging  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""), flush=True)


def main() -> int:
    setup_logging(False)
    win32.set_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    from pixelcat import settings
    from pixelcat.app import PixelCatApp
    from pixelcat.persistence import SavedState
    from pixelcat.settings import load_config

    written: list[tuple[str, object]] = []
    settings.save_user_setting = lambda k, v: written.append((k, v))   # never touch the real config
    pet = PixelCatApp(app, load_config(), SavedState(autostart_asked=True), selftest=1)
    pet.save = lambda: None
    m = pet.menu
    out = ROOT / "build" / "preview"
    out.mkdir(parents=True, exist_ok=True)

    def render(name: str) -> None:
        m.u = 3
        w, h = m._layout()
        m.resize(w, h)
        m.grab().save(str(out / name))

    def row(key: str) -> int:
        return next(i for i, (it, _d, _r) in enumerate(m._rows) if it.key == key)

    m.items = pet._menu_items()
    m.expanded.clear()
    top = [it.key for it in m.items]
    check("on top: Pause, Chat, Minigames, Cosmetics, Settings, Quit",
          top == ["pause", "chat", "games", "cosmetics", "settings", "quit"], str(top))
    games = next(it for it in m.items if it.key == "games").children
    sets = next(it for it in m.items if it.key == "settings").children
    check("Minigames: all 8 games (and Feed)", [c.key for c in games] == [
        "game:ball", "game:laser", "game:treats", "game:knock", "game:mice", "game:fishing", "game:hide",
        "game:boxes", "feed"] and games[0].label == "Play ball", str([c.label for c in games]))
    check("at the start only Play ball, Laser pointer and Treat toss are unlocked; the rest shows its stage",
          [c.locked for c in games[:8]] == [False, False, False, True, True, True, True, True]
          and games[3].note.startswith("STAGE "), str([(c.label, c.note) for c in games]))
    cos = next(it for it in m.items if it.key == "cosmetics").children
    check("Cosmetics: Cat Pass (stage + progress bar), Skins, Hats", [c.key for c in cos] == ["pass", "skins", "hats"]
          and cos[0].bar is not None and cos[0].note == "STAGE 1", str([(c.label, c.note) for c in cos]))
    check("11 skins (only Charcoal unlocked at first), No hat + 15 hats (all locked at first)",
          len(cos[1].children) == 11 and [c.key for c in cos[1].children if not c.locked] == ["skin:charcoal"]
          and len(cos[2].children) == 16 and [c.key for c in cos[2].children if not c.locked] == ["hat:"],
          str([c.key for c in cos[1].children if not c.locked]))
    check("Settings: Style, Accent color, Size, Font, AI model, then the on/off settings",
          [c.key for c in sets] == ["set_style", "set_accent", "set_size", "set_font", "set_model", "quiet",
                                    "autostart", "automode", "preload_ai"], str([c.label for c in sets]))
    styles = sets[0].children
    check("10 styles to choose from, the current one marked", len(styles) == 10
          and sum(1 for c in styles if c.checked) == 1 and styles[0].label == "Cat Chat", str([c.label for c in styles]))
    check("AI models from tiny to huge, with sizes and which are downloaded",
          [c.label for c in sets[4].children][0] == "Tiny 0.8B" and [c.label for c in sets[4].children][-1]
          == "Huge 122B" and any("READY" in c.note for c in sets[4].children), str([c.note for c in sets[4].children]))
    render("menu_closed.png")
    check("the sections start folded: 6 rows", len(m._rows) == 6)
    m._activate(row("games"))
    check("clicking a section folds it open", len(m._rows) == 6 + len(games)
          and [d for _it, d, _r in m._rows].count(1) == len(games))
    m._activate(row("settings"))
    check("one section open at a time: opening Settings folds Minigames", len(m._rows) == 6 + len(sets)
          and "games" not in m.expanded and "settings" in m.expanded)
    m._activate(row("set_style"))
    check("sections fold open inside sections (Settings -> Style)", any(it.key == "style:midnight" for it, _d, _r
                                                                         in m._rows))
    render("menu_open.png")
    # a setting: toggles, menu stays open, new state shown
    closed: list[bool] = []
    real_close = m.close
    m.close = lambda: (closed.append(True), real_close())[1]  # type: ignore[method-assign]
    m.isVisible = lambda: True  # type: ignore[method-assign]   (as if it were open on screen)
    was = pet.saved.auto_mode
    m._activate(row("automode"))
    now = next(c for it in m.items for c in it.children if c.key == "automode")
    check("clicking a setting toggles it and keeps the menu open, showing the new state",
          pet.saved.auto_mode != was and not closed and now.checked == pet.saved.auto_mode)
    m._activate(row("automode"))
    pre = pet.cfg.preload_on_start
    m._activate(row("preload_ai"))
    check("'Load AI at start' is a setting too (saved in your own config.json)",
          pet.cfg.preload_on_start != pre and written[-1] == ("preload_on_start", not pre))
    m._activate(row("preload_ai"))
    check("the section stays open after a toggle", "settings" in m.expanded)
    # a style: applies at once, menu stays open
    from pixelcat.ui import theme

    looks: list[tuple] = []
    real_set = pet._set_look
    pet._set_look = lambda k, v: (looks.append((k, v)), theme.configure(**{k: v}))  # type: ignore[method-assign]
    m._activate(row("style:midnight"))
    check("clicking a style applies it at once and the menu stays open (style saved)",
          looks == [("style", "midnight")] and theme.current().key == "midnight" and not closed)
    m._activate(row("style:catchat"))
    pet._set_look = real_set  # type: ignore[method-assign]
    # a model that isn't downloaded: asks first
    asked: list[str] = []
    pet.open_chat = pet._ensure_chat  # type: ignore[method-assign]   (not shown on screen)
    pet._ensure_chat()
    pet.chat.ask_confirm = lambda text, cb, allow_always=False: asked.append(text)  # type: ignore[method-assign]
    before = pet.cfg.model
    m._activate(row("set_model"))
    m._activate(row("model:qwen3.5:122b-a10b"))
    check("picking a model that isn't downloaded asks before downloading it (81 GB)",
          asked and "81 GB" in asked[0] and pet.cfg.model == before, asked[0] if asked else "")
    # locked things do nothing
    from pixelcat import progress

    m.expanded = {"games"}
    m.items = pet._menu_items()
    m._layout()
    began: list[str] = []
    real_begin = pet._begin_game
    pet._begin_game = lambda k: began.append(k)  # type: ignore[method-assign]
    m._activate(row("game:hide"))
    check("clicking a locked game does nothing (menu stays open)", not began and not closed)
    # the first time: an explanation first (a fake popup - nothing on screen)
    from PySide6.QtCore import QObject, Signal

    class FakePop(QObject):
        answered = Signal(bool)

        def close_later(self, _s: float) -> None: ...

    pops: list[tuple] = []

    def fake_popup(title, text, ok, cancel=None, picture=None):  # type: ignore[no-untyped-def]
        fp = FakePop()
        pops.append((title, text, ok, cancel, picture, fp))
        return fp

    pet._popup = fake_popup  # type: ignore[method-assign]
    pet.selftest = 0
    m._activate(row("game:laser"))
    check("the first time a game is played, a little window explains it first", bool(pops) and not began
          and pops[0][0] == "Laser pointer" and "laser" in pops[0][1] and pops[0][2] == "LET'S PLAY!"
          and pops[0][4] is not None, str(pops[0][:4]) if pops else "")
    pops[0][5].answered.emit(True)
    check("'Let's play!' starts the game and it is not explained again", began == ["laser"]
          and "laser" in pet.saved.tutorials_seen)
    pet.start_minigame("laser")
    check("the second time it starts right away", began == ["laser", "laser"] and len(pops) == 1)
    pet.start_minigame("treats")
    pops[-1][5].answered.emit(False)
    check("'Not now' doesn't start it (and it is explained again next time)", began[-1] == "laser"
          and "treats" not in pet.saved.tutorials_seen)
    pet._begin_game = real_begin  # type: ignore[method-assign]
    # XP: stages unlock things, with a result window
    pet.saved.xp = progress.xp_to_reach(4) - 10
    pops.clear()
    pet._award("laser", "Laser pointer", 40, "12 pounces!", "")
    check("XP from a game fills the Cat Pass; a new stage unlocks something (shown in the result window)",
          progress.state(pet.saved.xp).stage == 4 and pops and "+40 XP" in pops[-1][1] and "Ginger" in pops[-1][1]
          and pops[-1][2] == "PUT IT ON", pops[-1][1] if pops else "")
    pops[-1][5].answered.emit(True)
    check("'Put it on' wears the new skin at once", pet.saved.skin == "ginger" and pet.sprites.skin.key == "ginger")
    pet.selftest = 1
    # cosmetics: pick a skin and a hat, menu stays open
    pet.saved.xp = progress.xp_to_reach(12)
    m.expanded = {"cosmetics", "hats"}
    m.items = pet._menu_items()
    m._layout()
    closed.clear()
    m._activate(row("hat:beanie"))
    check("Cosmetics -> Hats: a hat goes on at once and the menu stays open",
          pet.saved.hat == "beanie" and pet.overlay.hat == "beanie" and not closed)
    m._activate(row("hat:"))
    check("'No hat' takes it off", pet.saved.hat == "" and pet.overlay.hat == "")
    m._activate(row("hat:crown"))
    check("a locked hat can't be worn", pet.saved.hat == "")
    m.expanded = {"cosmetics", "skins"}
    m.items = pet._menu_items()
    m._layout()
    m._activate(row("skin:snow"))
    check("Cosmetics -> Skins: the cat changes skin at once", pet.sprites.skin.key == "snow" and not closed)
    m._activate(row("skin:galaxy"))
    check("a locked skin can't be picked", pet.sprites.skin.key == "snow")
    m.expanded = {"cosmetics", "pass"}
    m.items = pet._menu_items()
    m._layout()
    stages = [it for it, _d, _r in m._rows if it.key.startswith("pass:")]
    check("the Cat Pass lists the stages around you: what each unlocks, how much XP is still needed",
          len(stages) == 8 and any(not it.locked for it in stages) and any(it.locked and it.note.endswith("XP")
                                                                           for it in stages),
          str([(it.label, it.note) for it in stages]))
    render("menu_cosmetics.png")
    m.expanded = {"cosmetics", "hats"}
    m.items = pet._menu_items()
    render("menu_hats.png")
    pet._set_skin("charcoal")
    pet.saved.xp = 0
    # a game: menu closes, the game starts
    pet._refresh_windows()                       # the cat needs its world (monitors, windows) to play
    pet.brain.place(pet.brain.smap.floors[0].x1 + 400, pet.brain.smap.floors[0].y - 1)
    m.expanded = {"games"}
    m.items = pet._menu_items()
    m._layout()
    closed.clear()
    m._activate(row("game:ball"))
    check("clicking Play ball closes the menu and starts the game", bool(closed) and pet.game.active)
    m.items = pet._menu_items()
    m._layout()
    label = next(c.label for it in m.items for c in it.children if c.key == "stopgame")
    check("during a game it says 'Stop playing ball'", label == "Stop playing ball", label)
    pet.game.stop(poof=False)
    # keyboard: arrows move, Enter folds a section
    m.expanded.clear()
    m.items = pet._menu_items()
    m._layout()
    m._hover = -1
    for _ in range(3):
        m.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
    m.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    check("keyboard: arrow keys and Enter open Minigames", "games" in m.expanded)
    m._hover = -1
    m.expanded = {"cosmetics", "pass"}
    m.items = pet._menu_items()
    m._layout()
    seen = set()
    for _ in range(len(m._rows) + 2):
        m.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
        seen.add(m._rows[m._hover][0].key)
    check("keyboard skips the Cat Pass info rows", not any(k.startswith("pass:") or k == "pass_total" for k in seen),
          str(sorted(seen)))
    from pixelcat.desktop import system

    check("'Start with Windows' shows the real setting (not changed by this test)",
          next(c for c in sets if c.key == "autostart").checked is system.autostart_enabled())
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
