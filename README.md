# Pixel Cat 🐾

A procedurally drawn kawaii pixel-art cat for Windows 11: soft charcoal fur, a wide rounded-square head with pointy corner ears, golden eyes, peach nose, pink blush, whiskers, stubby legs, a curly tail and pink toe beans. A light sticker-style rim keeps it visible on dark windows. It lives on your taskbar and on your window title bars, climbs window sides, naps, begs for fish and chats with you through a local Ollama model. Every sprite is generated in code: there are no image, font or sound files. Sound was left out on purpose.

## Architecture

```
main.py                     entry point: DPI awareness, single instance, Qt app, CLI flags
config.json                 user options (model, URL, app whitelist, folders, tuning overrides)
pixelcat/
  settings.py               Tuning (all speeds/probabilities/timings) + Config loading
  paths.py, logsetup.py     %APPDATA%/PixelCat paths, rotating log.txt, crash hooks
  persistence.py            state.json (needs, quiet mode, position) with atomic writes
  app.py                    controller: timers, wiring, menu actions, chat/tool flow
  sprites/
    raster.py               palette-indexed canvas: ellipses, polygons, outlines, flips
    palettes.py             palette indices + the cat's colours
    cat_art.py              parametric 32x32 cat: Pose -> pixels (18 body poses, eyes, mouths, ears, whiskers, tail)
    effects_art.py          hearts, Zzz, sparkles, notes, bubbles, fish, yarn, cushion, shadow, menu icons
    pixelfont.py            built-in 5x7 bitmap font
    library.py              Qt cache: nearest-neighbour scaling, hit masks, sprite-sheet export
  desktop/
    win32.py                typed ctypes bindings (EnumWindows, DWM bounds, DPI, styles)
    monitors.py             monitors with work areas and per-monitor DPI
    windows.py              read-only window enumeration + fullscreen detection
    system.py               mutex, HKCU Run autostart, typing/clicking activity tracker
    volume.py               master volume through Core Audio COM (pure ctypes)
    control.py              app/window actions, Start-menu apps, /force
    uia.py                  UI Automation (accessibility API): a window's controls and text, raw ctypes COM
    capture.py              screenshots for the model (the cat's own windows left out)
    inputs.py               SendInput keyboard/mouse, focus handling, clipboard
    escwatch.py             Esc-anywhere emergency stop while the chat uses the desktop
    elevation.py            does something need admin rights? (manifest, shortcut flag, UAC prompt on screen)
  engine/
    surfaces.py             surface graph: floors, visible title-bar segments, climbable walls
    planner.py              Dijkstra pathing with walk / jump / drop / climb edges
    animations.py           named animations (loops + one-shot transitions)
    states.py               21 behaviour states + their idle/enter animations
    needs.py                energy / hunger / mood model
    brain.py                state machine + locomotion executor + interactions
    particles.py            particles, bubbles, yarn prop
  ui/
    overlay.py              transparent click-through cat window, mouse handling
    menu.py                 pixel-art right-click menu
    chat.py                 pixel chat window with streaming and confirmation cards
    dialogs.py, tray.py     first-run consent dialog, tray icon
    geometry.py, theme.py   coordinate mapping, nearest-free-space placement, styles
  llm/
    ollama_client.py        streaming /api/chat in a QThread + cat-voice error messages
    prompt.py               system prompt (cat persona, accuracy comes first)
    tools.py                whitelisted desktop tools with validation and confirmation flags
    agent.py                the chat's eyes and hands: look, read, click, type, keys, scroll + guard rails
```

**How the parts connect.** `app.py` runs one adaptive `QTimer`. It runs at 30 FPS while the cat moves, about 10 FPS while it rests and 4 to 6 FPS while it sleeps. It drops to 1 FPS when a fullscreen app hides the cat. On each tick the brain advances and the overlay draws the current frame. The window list is refreshed 4 times per second and turned into a `SurfaceMap`. The brain plans trips over that map with Dijkstra. No LLM is involved in movement. The LLM can only request harmless named events such as `sit` through the `cat_action` tool, and the state machine carries them out.

**Coordinates.** The process is per-monitor-v2 DPI aware. Qt's own high-DPI scaling is switched off (`QT_ENABLE_HIGHDPI_SCALING=0`), so Qt and Win32 share one physical pixel space across all monitors. Pixel Cat scales itself instead: each monitor gets an integer pixel scale of `round(3 × DPI/96)`, so the cat stays crisp and roughly the same size on 100 % and 200 % displays.

**Click-through.** The overlay is a small layered tool window that follows the cat. A 25 Hz cursor poll switches `WS_EX_TRANSPARENT` on that window only. It is click-through everywhere except over the cat's opaque pixels. Hearts, Zzz and bubbles never block clicks. The window uses `WS_EX_NOACTIVATE`, so it never takes focus and never appears in the taskbar or Alt-Tab.

### Deviations from the suggested stack (and why)
* **ctypes only, no pywin32.** Every Win32 call is a small typed ctypes binding. This avoids pywin32's post-install step and PyInstaller hidden-import problems, and it needs one dependency less.
* **PySide6-Essentials instead of the full PySide6.** The app only uses QtCore, QtGui and QtWidgets, which makes the .exe much smaller.
* **No sound and no numpy.** You asked for no sounds, so there is no audio code and no mute toggle.

## Requirements

* Windows 11 (Windows 10 should work too, but only Windows 11 was tested)
* Python 3.11+ (64-bit)
* For chat: [Ollama](https://ollama.com) with the model pulled:

```powershell
ollama pull qwen3.5:35b-a3b
```

`qwen3.5:35b-a3b` can see images (screenshots), call tools and think before it answers. It is a mixture-of-experts model: 35B parameters, but only about 3B of them work on each word. That makes it clearly smarter than small models while staying fast on a normal PC. Measured on this laptop (RTX PRO 2000 8 GB, Core Ultra 7, 64 GB RAM) with `python tools/model_bench.py`:

| | `qwen3.5:9b` | `qwen3.5:35b-a3b` (default) |
|---|---|---|
| writing speed | 29 tokens/s | 37 tokens/s |
| reading a prompt | 1,246 tokens/s | 705 tokens/s (the cache absorbs most of this during tasks) |
| tricky reasoning question, with thinking | no answer after 138 s | correct after 102 s |
| memory while loaded | about 1.5 GB RAM + 5 GB GPU | about 16 GB RAM + 5.5 GB GPU |
| cold start | 11 s | 36 s (the chat preloads the model when it opens) |

Ollama unloads the model after 10 idle minutes (`keep_alive`), which frees the memory. On a PC with less than about 32 GB of RAM, use `qwen3.5:9b` instead: set `"model"` in `config.json` (or `PIXELCAT_MODEL` for tests).

## Run from source

```powershell
cd "Cat Assistant"
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw main.py
```

Useful flags (run with `python` instead of `pythonw` to see console output):

| flag | effect |
|---|---|
| `--debug` | verbose logging (state changes and similar) |
| `--selftest 20` | run 20 s, save an overlay snapshot to `%APPDATA%\PixelCat\cache`, then quit |
| `--export-sheets` | write the PNG sprite sheet to `%APPDATA%\PixelCat\cache` and exit |

Developer tools (in `tools/`):

| script | what it does |
|---|---|
| `python tools/preview.py` | labelled PNG sheets of every pose, face and effect in `build/preview/` |
| `python tools/sim_test.py` | headless 4-hour simulation with fake monitors (mixed DPI) and moving, opening and closing windows; checks invariants |
| `python tools/drag_test.py` | picking up the cat through the real Windows message path (mouse capture, double-click detection) while Windows reports the button as up, as it does when an app running as administrator is in front, and for touch and pen input: carrying for a full second, dropping where you let go, a press right after a click, a real double-click, and a release that really went to another window |
| `python tools/ball_test.py [games]` | headless ball game: hundreds of games with simulated players who hold the ball still, wave it around, throw it, or ignore it. Checks that nothing gets stuck or leaves the screen, every round ends in a catch (about 2–4 tries; never more than 12), another round follows about 75 % of the time, and the cat is back to normal afterwards |
| `python tools/ball_ui_test.py` | the ball game in the real app with a simulated pointer (the real mouse isn't moved): window styles, click-through except on the ball, grab, drag, throw, catch, the menu, fullscreen hiding, the saved record, frame time |
| `python tools/ball_preview.py` | storyboards of a simulated game drawn with the real rendering (`build/preview/ball_story*.png`, `ball_rounds.png`) |
| `python tools/control_test.py [--chat]` | opens two test windows and checks list, minimize, maximize, restore, focus and close on them only, plus app lookup, system info and the clipboard; with `--chat` it drives the whole chain (confirmation cards, ALWAYS, auto mode) through Ollama |
| `python tools/force_test.py` | starts small test apps that freeze on purpose and ends them with `/force` (with the card and in auto mode); checks the safety refusals |
| `python tools/climb_test.py` | opens two test windows (without taking focus) and checks that the cat climbs onto one, falls when it closes, and climbs the screen edge |
| `python tools/agent_test.py [--chat]` | the chat's eyes and hands on a harmless test app (`tools/test_editor.py`): screenshots with element marks, reading text, clicking by id and by position, exact Unicode typing, shortcuts, clicks through the cat's chat window, and the guard rails (covered spots, Stop/Esc, focus loss, command lines). With `--chat` the real model fills in the test app and does "open Notepad, make a new file and write a plan" (the test tab is emptied and closed afterwards) |
| `python tools/file_test.py [--chat]` | the file tools, inside `build/filetest` only: exact edits, encodings, BOM and line endings kept, backups, and refusals (overwriting, programs, outside folders, missing files). With `--chat`, the real model fixes a bug in a `.js` file and creates a list file |
| `python tools/model_bench.py <models…>` | compares local models: load time, prompt and writing speed, a thinking answer, a vision check on a test screenshot, and RAM/GPU use |
| `python tools/memory_test.py [--chat] [--long]` | context and memory, without a model: every earlier request stays in the condensed context; a 40-step task keeps its request and fits the budget; the context only grows at the end during a task and is compacted rarely; stuck detection; "continue" resumes the task. `--chat`: the real model still remembers a fact after tool-heavy turns, and calls tools instead of inventing results. `--long`: the real model does one task of 70+ steps in the test editor without pausing, and the per-step prompt time is measured |
| `python tools/watch_test.py [--chat]` | long tasks (`wait_for`), files only in `build/watchtest`: reading Windows notifications (a real test pop-up from PowerShell), app-name matching, every kind of watch firing (notification, time, file and folder, window opened / text appears / text gone / closed, with the test editor), "already the case", giving up, saving and restoring, wake-ups waiting for a running task and for the lock screen, and the empty-promise guard. With `--chat` the real model waits for a notification and reports it, does a task one minute later, reacts to a new file, and sets up and stops a Teams watch |
| `python tools/ui_test.py [--chat]` | runs the real app in-process: window styles, click-through, click, drag and drop, menu placement at edges, chat UI, idle CPU, and with `--chat` a real Ollama tool round trip |

## Build the .exe

```powershell
.venv\Scripts\python build.py
```

`build.py` draws the icon from the cat's sprite: a 25 px portrait, written as a multi-size `.ico` (16 to 256 px, pixel-perfect scaling, sticker rim). Then it runs this PyInstaller command:

```powershell
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name PixelCat --add-data "config.json;." --exclude-module tkinter --exclude-module numpy --icon build\pixelcat.ico main.py
```

The result is `dist\PixelCat.exe`, a single windowed exe with no console. The exe is built in `build\dist_staging` and then swapped into `dist` in one step, and Explorer is told to refresh its icon. This matters because Explorer caches the generic icon of a half-written exe. If Explorer still shows an old icon, run `ie4uinit.exe -show`. You can put a `config.json` next to the exe to override the bundled one.

## Using it

| action | what happens |
|---|---|
| click | hearts, a soft "purr" (♪ notes) and the cat gets happy; about 6 quick pokes make it grumpy, and it calms down fast |
| click a sleeping cat | it wakes up a little grumpy, then recovers |
| press & hold, or stroke it with the cursor | petting: hearts, then it goes cuddly and kneads |
| double-click | playful hop |
| drag | picks the cat up (it dangles with wiggling paws); release to drop it; dropped on a title bar, it sits there. Right-clicking while carrying it simply drops it |
| right-click | pixel menu: Pause/Resume, Chat, Feed, Play ball (Stop playing during a game), Quiet mode, Start with Windows, Quit |
| tray icon | Pause, Chat, Find my cat, Quiet mode, Quit (click the icon to call the cat back to the primary screen) |

**Behaviour.**
* **Movement and states.** The cat walks on the taskbar edge and across monitor boundaries. On normal (non-maximized) windows it leaps onto a window side, climbs it, hangs at the corner and pulls itself up onto the title bar. It also jumps between title bars and hangs from edges before dropping down. It falls safely when its window closes or is covered, and rides along when its window moves.
* **Maximized windows.** A maximized window's title bar is at the very top of the screen, so there is no room to sit on it and no side to climb. When every window is maximized, the cat climbs the side of the screen instead, clings there for a moment and leaps back down. You can also ask it in the chat ("climb!").
* **Needs.** Energy, hunger and mood persist in `%APPDATA%\PixelCat\state.json`. The time of day and your idle time affect sleepiness.
* **Staying out of the way.** The cat watches the cursor with its eyes. While you type or click, it keeps its distance. It hides automatically during fullscreen games, videos and presentations.
* **Quiet mode.** The cat walks to the bottom-right corner and only rests there.
* **Grumpy.** Ears swept back with sharp tips, narrowed eyes and a pout; woken up rudely, it arches and hisses with little fangs. (Before, the flat round ears with big pink insides looked like a mouse.)

## Playing ball

Right-click the cat and choose **Play ball** (or ask in the chat: "let's play"). A yarn ball pops out in front of the cat.

* **Grab it and move it anywhere** on the screen. The cat runs below it, keeps its eyes on it, sometimes crouches and wiggles its butt to aim, then leaps: paws up for a ball above it, a long leap for one off to the side, a low pounce for one near the floor.
* **Throw it** by letting go while moving, just like throwing the cat. The cat runs to where the ball will come down and jumps when it is within reach. Swing the ball around fast and the cat waits crouched below it for the moment you slow down.
* **It learns.** Every miss makes it better until it gets the ball:
  * it aims closer and predicts your movement more;
  * it steers more in the air and grabs more surely;
  * after a few misses it waits for the ball to stop going up and down, and jumps a little higher than the ball, so its paws sweep through it.

  It sweats a little after a miss, and after several it gets determined.
* **After a catch** the cat lands, struts with the ball in its mouth, rolls on its back with it, bats it away and pounces on it again. Then, with a **75 % chance**, it pushes the ball back to you ("?") and the next round starts. The chance shrinks by 7 points every round (75, 68, 61 … %), so a game lasts at most 12 rounds. Otherwise it hugs the ball, purrs, and the ball goes *poof*.
* **Every round adds something** (a banner shows what):

  | round | new |
  |---|---|
  | 2 | sparkle trail behind the ball |
  | 3 | rainbow ball with a rainbow trail |
  | 4 | backflip when it catches the ball, plus a star burst |
  | 5 | glowing ball, and a victory lap with the ball |
  | 6 | confetti on every catch |
  | 7 | a golden crown on the cat |
  | 8 | golden ball |
  | 9 | fireworks on every catch |
  | 10 | double backflip |
  | 11 | legendary: raining hearts |

  Beat your best game and the banner says **NEW RECORD!** (the best one is kept in `state.json`).
* **Details:**
  * The ball bounces off the floor (above the taskbar) and the screen edges, rolls to a stop, and crosses monitors.
  * The cat leaps to another monitor's floor if the ball rolls there.
  * While playing, the cat lands on the floor rather than on title bars, like the ball.
  * The ball window lets clicks through everywhere except on the ball, never takes the keyboard, and hides with the cat during fullscreen apps.
  * You can still pet or pick up the cat mid-game. Pause or **Stop playing** ends the game.
  * If nobody takes the ball for 45 s, the cat takes it and ends the game itself.
  * The game runs at 60 frames per second; one frame takes about 0.5 ms.

## Chat and desktop tools

**Memory and new chat.**
* **The current task is always budgeted.** Your request always stays at the start. Without this, Ollama silently cuts the *oldest* messages of an over-long prompt, which would be your request, and the AI would lose the goal halfway through.
* **During a task the prompt only grows at the end.** With `qwen3.5` (a hybrid model), Ollama reuses its cache only for an unchanged beginning. Appending a step costs about 0.2 s, while any change earlier in the prompt means re-reading all of it: 5 to 10 s per step. When the task gets close to the limit, the cat compacts it once (older steps become one line, old screenshots are dropped) and keeps appending from there. The log shows `model: N prompt tokens ... read in X s` for every request.
* Earlier exchanges are remembered in condensed form: your message, its last few tool steps (kept as real tool calls with a one-line result) and the cat's answer. Up to `max_history` exchanges (default 30) are kept, as far as the model's context (`num_ctx`, 64k tokens) allows.
* About 15 tool-heavy desktop requests take only about 6,000 tokens this way. Before, the window counted single messages, and one desktop task used 10–20 of them, which is why the cat forgot things after 2–3 requests.
* **Context size: 64k tokens.** `qwen3.5:35b-a3b` supports up to 262k natively; Hugging Face's "about 1 million" needs YaRN scaling, which Ollama doesn't offer for this model. Only 10 of its 40 layers keep every token; the other 30 keep a fixed-size summary. So a bigger context costs only about 20 KB per token. Measured on this laptop:

  | `num_ctx` | RAM | writing (short prompt / 15k tokens in the prompt) |
  |---|---|---|
  | 16k | +16.3 GB | 35 / 33 tokens/s |
  | 32k | +15.8 GB | 36 / 32 tokens/s |
  | **64k (default)** | +17.5 GB | 38 / 30 tokens/s |
  | 128k | +19.1 GB | 28 / 28 tokens/s |

  With 64k, `read_file` shows files up to 60,000 characters and `read_window` up to 20,000 characters. One cost remains: when the model has to read a long conversation from scratch (for example after Ollama unloaded it), it reads about 690 tokens/s.
* Click ＋ in the chat title bar or press Ctrl+N to start fresh. The cat suggests this once the oldest part no longer fits.
* The system prompt contains only the date, not the clock time, so its start stays the same between messages. That lets Ollama reuse its cache, so answers start faster.
* Opening the chat warms the model up in the background, and Ollama keeps it loaded for 10 idle minutes (`keep_alive`).

The chat streams from `http://localhost:11434/api/chat` (model `qwen3.5:35b-a3b`; change both in `config.json`). The cat answers in cat voice with meows, kaomoji and a little emoji slang. Code, facts and steps still have to be correct and appear in code blocks.

Desktop tools form a fixed whitelist. There is no shell, and nothing is force-killed unless you type `/force` yourself. **Permissions:**
* **Auto mode off.** Everything that changes something shows a permission card first. Only read-only things run without asking: listing windows, looking at or reading a window, the time. A tool you set to ALWAYS on a card stops asking; `/permissions reset` undoes that.
* **Admin rights.** Anything that needs admin rights **always** asks first, even in auto mode and even for tools set to ALWAYS.

Every result appears in the chat. Just ask in plain words, for example "close outlook", "switch to chrome", "minimize teams", "open spotify", "pause the music", "search the web for pixel art cats", "how much battery do I have?".

| tool | confirmation |
|---|---|
| `get_time`, `system_info` (battery, RAM, CPU, disk, uptime), `list_windows`, `list_files`, `get_volume`, `set_timer`, `set_reminder`, `cat_action`, `wait_for`, `stop_waiting` | none (read-only, or in-app only) |
| `open_app` (apps in `config.json → apps`, or any Start-menu app), `window_action` (focus / minimize / maximize / restore), `open_url`, `search_web`, `open_folder`, `open_settings` (Wi-Fi, Bluetooth, display...), `media_control` (play/pause, next, previous, stop), `copy_to_clipboard`, `take_screenshot`, `set_volume`, `mute` | **YES / ALWAYS / NO**: ALWAYS stops asking for that tool |
| `close_app` (graceful, like clicking X, so apps can still ask you to save), `create_note` (.txt/.md, never overwrites), `lock_screen` | **YES / NO**, always asked |
| `look_at_screen`, `read_window`, `wait` | none: read-only, they never bring a window to the front or change it. Screenshots only go to your local model; if `ollama_url` points at another PC, they ask first |
| `click`, `type_text`, `replace_text`, `press_keys`, `scroll` | **YES / ALWAYS / NO**. ALWAYS covers all of them at once ("desktop control"). Closing shortcuts (Alt+F4, Ctrl+W, Ctrl+Q, Shift+Del, Win+L) always ask |

### Waiting and long tasks

The cat can only act while a request is running. Before, "wait for a Teams message" made it answer "I'll wait!" and stop, because nothing was watching. Now it has `wait_for`:

* **How it works.** The AI calls `wait_for` with what to watch for and a note to itself about what to do then. A background thread checks cheaply, without the AI: Ollama may even unload the model meanwhile, which frees the RAM. When it happens, the cat wakes up with what happened, its note and your original request, and carries on. You can keep chatting meanwhile.
* **What it can watch:**

  | event | example | how it is checked |
  |---|---|---|
  | `notification` | "tell me when Anna writes on Teams", "let me know when an email from IT arrives" | new Windows notifications every 2 s, read-only from Windows' own notification list (`wpndatabase.db`, no admin rights; nothing is marked read or dismissed). If an app's pop-ups are off, a rising unread counter on its icon counts too |
  | `window_text` | "when the installer says 'Finished'…", "tell me when 'Exporting…' is gone" | the window's text through UI Automation every 5 s (less often for slow apps). The window may be covered, but not minimized |
  | `window_opened`, `window_closed` | "when the export dialog closes, open the file" | the list of open windows every 2 s |
  | `file` | "when the download is done, open it", "when report.txt appears, read it" | the file or folder every 3 s. Unfinished downloads (`.crdownload`, `.part`…) and files that are still growing are ignored |
  | `time` | "at 17:00 open Outlook and…", "in 20 minutes…" | the clock |

* **Limits.** A watch gives up after 8 hours unless the AI sets `minutes` (at most 7 days), and the cat then tells you. At most 10 watches run at once, and the same watch requested twice is kept only once.
* **You see it.** A yellow *Watching for* bar in the chat lists every watch with a *stop* link, and the tray tooltip shows how many there are. `/watches` lists them, `/unwatch` stops all of them and `/unwatch 3` stops one. You can also just tell the cat to stop waiting.
* **When it fires.** A 🔔 line appears in the chat and the cat shows "!". If the chat is closed, the answer comes as a notification from Pixel Cat; click it to open the chat. A wake-up waits while another task runs, and while the PC is locked (clicks and typing can't work on the lock screen); it starts once you're back.
* **Permissions stay the same.** Watching is read-only, so it needs no card. Whatever the cat does after waking up asks as usual unless auto mode is on, and admin rights always ask. If a card is needed while the chat is closed, the chat appears without taking your keyboard, together with a notification.
* **Messages are data.** The text of a notification or window comes from someone else. The cat is told to treat it as information, never as instructions.
* **Restarts.** Watches are saved in `state.json` and continue after the cat restarts. A notification that arrived while the cat was closed still counts. A time that passed meanwhile fires late and says so.
* **No more empty promises.** If the AI's final answer says "I'll wait", "I'll let you know" or "I'll keep an eye on it" (also German, such as "ich sage dir Bescheid" or "ich melde mich") without a watch, the app reminds it once to start `wait_for` or to tell you honestly that it can't. "I'll wait for your answer" is fine.
* `set_timer` and `set_reminder` stay simple alarms. `wait` only pauses a few seconds within a task; asking it for longer gets an error that points the AI to `wait_for`.
* **What it can't see.** Teams, Outlook and similar apps only show up if they send Windows notifications or update their icon badge, which is the default. While you are looking at a chat in Teams, Teams sends nothing for it. The cat's own notifications never count.

### Files

For anything that lives in a file, the cat works on the file directly. This is far more reliable than clicking and typing in an editor, and it is how a developer (or Claude) edits code.

| tool | what it does | confirmation |
|---|---|---|
| `read_file` | reads a text file exactly (code, notes, lists) | none (read-only) |
| `edit_file` | changes part of a file: exact `old` → `new`, with the same tolerant matching as `replace_text` | YES / ALWAYS / NO ("files" group) |
| `write_file` | creates a text file. Replacing an existing one needs `overwrite` and always asks | YES / ALWAYS / NO; overwriting: YES / NO |
| `open_file` | shows a file in Notepad or VS Code. It never runs it | YES / ALWAYS / NO |

* **Allowed folders.** Only files inside `allowed_roots` (your *real* Desktop, Documents, Downloads, Pictures, Music, Videos and PixelCat Notes). Paths look like `desktop/list.txt`, `downloads/project/app.js` or a full path.
* **Text files only.** Programs and system files (`.exe`, `.bat`, `.ps1`, `.vbs`, `.reg`, `.lnk`, ...) are never written.
* **Backups.** Every change first copies the old version to `%APPDATA%\PixelCat\backups`; the newest 100 are kept.
* **Nothing else changes.** Encoding (UTF-8 with or without BOM, UTF-16, ANSI) and line endings stay exactly as they were. Every write is atomic, and the file is read back to check it.
* **Helpful errors.** A missing file gets "did you mean …" suggestions. Text that isn't in the file gets an error that shows the AI the real content.

### Seeing and using apps

The cat can look at your screen and use apps for you, for example "open Notepad, make a new file and write a plan for my weekend", "read what's in this window and summarize it", or "in Outlook, start a new email to my team about Friday" (it stops before sending unless you ask it to send).

* **Eyes (read-only).**
  * `look_at_screen` takes a screenshot of a window, or of the whole screen. The window is drawn as it is, even if other windows cover it, and it is not brought to the front. A minimized window has to be restored first, which is an action and asks. It draws pink numbered boxes on the clickable elements and sends the picture to the model together with the list. The model can then say "click 7" instead of guessing pixels.
  * `read_window` uses Windows UI Automation, the accessibility API screen readers use. It reads a window's exact text (documents, editors, web pages) and its controls, with no guessing from pixels.
* **Hands.**
  * `open_app` waits until the new window has finished drawing (up to 15 s). Keys sent to a half-started app, such as VS Code during its first seconds, are lost.
  * `click` takes an element id, or a pixel position in the last screenshot.
  * `type_text` writes text exactly, including Unicode and new lines.
    * Anything longer than a few characters is pasted.
    * Everything on your clipboard (text, images, files) is backed up first and put back afterwards.
    * The cat's temporary text never shows up in your Win+V clipboard history.
    * Short text is typed one key at a time, about 20 ms apart. Windows 11 Notepad scrambles keys that arrive in batches ("Dinner tt a cozy eestaurant").
    * Afterwards the cat checks where the text went, and never reports success blindly:
      * It reads the field back. If the text is there, the AI is told so.
      * If nothing changed at all, for example because the keyboard focus was on a button or a start page, the tool reports an **error**. The AI then has to tell you or fix it.
      * Some apps hide their text from the accessibility interface; VS Code says "The editor is not accessible at this time". If the window changed in such an app, the AI gets a screenshot and must check where the text landed. In a fresh VS Code the focus can sit in the Copilot Chat box, and pasted text would end up there instead of in a file.
    * Multi-line text is never typed key by key, because an Enter key could send a chat message or submit a form.
  * `replace_text` *changes* existing text, to fix a bug, a typo or a line. `type_text` only inserts at the text cursor, which is how a fix could land in the wrong place, such as `sort();` turning into `[...]()` on line 1.
    * The cat copies the editor's whole text (Ctrl+A, Ctrl+C), which also works in VS Code, where nothing else can read the text.
    * It finds the exact snippet. Spaces may differ slightly ("(b,a)" also finds "(b, a)"). If the snippet is missing or appears more than once, the AI gets an error that shows it the real text.
    * It pastes the corrected text back and copies it once more to check every character.
    * Your clipboard is restored and nothing is left selected. One Ctrl+Z undoes the change.
    * It works in plain-text editors such as Notepad, VS Code and Notepad++. It refuses in Word, Outlook and similar apps and in browsers, where it would lose the formatting.
  * `press_keys` presses shortcuts such as `ctrl+n` or `tab tab enter`.
  * `scroll` scrolls. `wait` pauses up to 10 seconds inside a task (a page loading); anything longer goes through `wait_for` (see *Waiting and long tasks*).
* **Multi-step.** The cat works through a whole task by itself and checks every result before its next step. There is no small step limit:
  * It stops when it is **stuck**: the same action three times in a row (six for scrolling, waiting or key presses), or four failures in a row.
  * It also stops if a task reaches 100 steps (`agent_max_steps`), as a last safety net.
  * The model is told not to ask "should I continue?".
  * **"continue"** (also "go on", "weiter", "mach weiter", "continue with …") resumes the *same* task, with its original request kept in view.
* **Stop at any time.** Press **Esc anywhere**, or click **STOP** in the chat. Typing also stops at once if another window comes to the front, for example because you clicked somewhere else.
* **Guard rails, enforced in code rather than by the model:**
  * Input only goes to the intended window, after it has been brought to the front.
  * A click is refused if another app covers that spot. The cat and its chat let clicks pass through.
  * Password fields are never typed into.
  * **Admin rights always ask, even in auto mode and with ALWAYS.** This covers:
    * opening an app that needs admin rights, detected from the program's manifest, the shortcut's "Run as administrator" flag, the compatibility setting, or Windows refusing to start it without them (for example Registry Editor and management consoles);
    * `/force open`;
    * `/force end` for processes that can only be ended with admin rights.

    These cards have no ALWAYS button. Windows then shows its own UAC prompt as well. If a UAC prompt appears after some other action, the cat stops and tells you, because only you can answer it and the cat never touches it.
  * Apps that already run as administrator can't be clicked or typed into: Windows blocks this, and the cat won't try to get admin rights for it.
  * Typing into a terminal, PowerShell or the Run box, and pressing Win+R or Win+X, **always asks, even in auto mode**.
  * Screenshots leave out the cat's own windows. They are kept only in memory, and only the newest one stays in the conversation.
* **Auto mode** also covers these desktop actions. The 6-actions-per-message limit does not count clicks and typing; `agent_max_steps` and the stuck detection cap them instead.

**Auto mode.** Click ⚡ in the chat title bar, type `/auto on`, or tick "Chat auto mode" in the right-click menu. The cat then simply does what you ask, with no permission cards. Every action is still listed in the chat, marked "(auto)". Two guardrails remain in case the AI misunderstands: at most 6 actions per message (`auto_mode_max_actions`), and closing more than 3 windows at once still asks (`auto_mode_max_close`). The setting is remembered; `/auto off` turns it off.

**Folders.** Aliases such as `desktop`, `documents` or `pictures` (also `schreibtisch` and `dokumente`) resolve to your *real* folders through Windows, including company folder redirection to a network share or OneDrive (for example `\\server\user$\Desktop` or `OneDrive\Bilder`).

`open_app` finds desktop apps (Start-menu shortcuts) and Microsoft Store apps such as Teams or Spotify, using a fixed, read-only `Get-StartApps` query that runs once in the background. English names also match localized ones (for example, "calculator" finds "Rechner").

**/force.** This is your own power command; the AI is never involved and can't trigger it.
* `/force end <app>` ends an app the way Task Manager's *End task* does: immediately, even when it is frozen. You can also write kill, close, quit or stop instead of end. Example: `/force end teams`.
  * **What gets ended:** the app's own helper processes go with it, but separate apps it started do not.
  * **Admin rights:** if a process can only be ended with admin rights, the cat first ends what it can, then asks you on a separate card whether to use admin rights for the rest. It asks even in auto mode, and Windows then shows its UAC prompt.
  * **Refused:** core Windows processes (csrss, lsass, winlogon, svchost, dwm…) and the cat itself.
* `/force open <app>` starts an app as administrator, via the UAC prompt. It always asks first, even in auto mode.
* **Confirmation:**
  * Without auto mode, `/force end` shows one confirmation card, because ending an app loses its unsaved work.
  * With auto mode on, it ends your own (non-admin) app at once.
  * Anything that needs admin rights is still asked.

Chat commands: `/new` starts a fresh chat, `/auto on|off` toggles auto mode, `/force end|open <app>` as above, `/watches` lists what the cat is waiting for, `/unwatch` (or `/unwatch 3`) stops that, `/permissions` shows which tools you set to ALWAYS, `/permissions reset` makes the cat ask every time again, and `/help` lists what it can do. Set `allow_start_menu_apps` to `false` in `config.json` to limit `open_app` to the `apps` list. `search_url` picks the search engine.

File tools only accept paths inside `allowed_roots` (Desktop, Documents, Downloads, Pictures, Music, Videos and `Documents\PixelCat Notes`). Timers and reminders (`set_timer`, `set_reminder`) live in memory and are lost when you quit; watches from `wait_for` are saved and continue after a restart. Tool calls use Ollama's native tool calling. Some models (for example `qwen2.5-coder`) often write the call as a JSON code block instead. Pixel Cat detects JSON objects that name a known tool (also inside `<tool_call>` tags), runs them through the same validation and confirmation, and hides that markup in the chat.

Pixel Cat never needs admin rights. Autostart is a per-user `HKCU\…\Run` value. On first launch the cat asks before setting it (YES is the default).

## Files

* `%APPDATA%\PixelCat\state.json`: needs, quiet mode, last position, auto mode, the running `wait_for` watches, and your best ball game
* `%APPDATA%\PixelCat\log.txt`: rotating log (1 MB × 3)
* `%APPDATA%\PixelCat\cache\`: exported sprite sheets and self-test snapshots
* `%APPDATA%\PixelCat\config.json` (optional): your overrides; wins over the bundled `config.json`

To uninstall, turn off "Start with Windows" in the menu, quit, and delete `%APPDATA%\PixelCat`.

## How to extend

**Add a pose.** Write `_mypose(cv, p)` in `sprites/cat_art.py` that draws with the helpers (`cv.outlined_ellipse`, `cv.round_rect`, `leg`, `limb`, `tail`, `head`), facing right on the 32×32 canvas with the ground at y = 31. Register it in `BODIES`, and add a head position to `HEAD_POS` so bubbles and Zzz appear in the right place.

**Add an animation.** In `engine/animations.py`, call `loop("name", [(Pose(body="mypose", ...), seconds), ...])` for idles or `once(...)` for transitions. Blinks, ear twitches and eye tracking are applied on top automatically.

**Add a state.** Add a member to `S` in `engine/states.py` and a `StateDef(idle=..., enter=(...), duration=(min, max), travel=..., calm=...)`. Give it a weight in `Brain._weighted_choice` and, if it needs one, a forced follow-up in `Brain._next_state`. Per-state idle behaviour (particles, bubbles, swats) goes in `Brain._idle_behaviour`.

**Add a tool.** In `llm/tools.py`, call `self._add(name, description, json_props, required, confirm, run_fn, describe_fn)` in `_register`, then add argument validation to `prepare()`. Use `confirm="soft"` or `"hard"` for anything that changes the system. Pass `background=True` for anything slow (it runs on a worker thread, so the cat keeps moving), and `group="desktop"` to share the ALWAYS approval of the input tools. `run_fn` may return a string, or a `ToolOutput` with images for the model. The schema is sent to Ollama automatically.

**Change the colours.** All cat colours are in the `CAT` palette in `sprites/palettes.py` (8-digit hex values carry alpha, as used for the rim).

**Tune the feel.** Every speed, probability and timing is in `settings.Tuning`. Values under `"tuning"` in `config.json` override the defaults.

## Edge cases and how the code handles them

* **Multi-monitor with mixed DPI.** Monitors come from `EnumDisplayMonitors` and `GetDpiForMonitor`, and the pixel scale is chosen per monitor at the cat's feet. Floors at the same height merge, so the cat walks across. Hot-plugging triggers a re-scan; a cat left outside every monitor is dropped onto the primary one.
* **A window closes or moves under the cat.** The 4 Hz refresh notices the missing window or the covered title-bar segment, and the cat falls, lands and looks startled. A moving window carries the cat along, and large jumps make it fall.
* **Fullscreen app.** The check combines `SHQueryUserNotificationState` (D3D fullscreen, presentations) with a check that the foreground window covers the cat's monitor and has no caption. Both the cat and the chat hide, and the loop drops to 1 FPS.
* **Chat scrolling.** Only the message that changes, usually the one being written, is redrawn. The view stays where you scrolled it and only follows new text when you are already at the bottom.
* **Chat window on another monitor.** When the chat moves to a monitor with a different DPI, it resizes itself and lays its text out again. Fonts are set in device pixels, because point sizes made layout and drawing disagree across monitors.
* **Desktop tasks.**
  * **Clicks.** Each click carries its own screen position, so moving your mouse at the same moment can't redirect it.
  * **Slow apps.** Electron and Chromium apps can take very long to list their elements. The cat gives up after 4 s and works from the screenshot instead.
  * **Wrong window.** If the user switches windows mid-task, typing stops. If a dialog opens (for example "Save as"), the keys and text go to that dialog, because it belongs to the same app.
  * **Moved windows and stale ids.** A clicked element is located again first, in case the window moved; an id from an old look is rejected.
  * **Emoji.** Characters outside the basic plane (emoji) are sent in their own input batch, because some apps reorder them otherwise.
  * **Context size.** Older tool output is shortened and only the newest screenshot is kept, so long tasks fit the context (`num_ctx`, 64k).
* **Thinking.** With `"think": "auto"` (the default), the model thinks before it answers a new message and after a failed step, where planning pays off. Routine steps such as "type the next item" stay fast. While it thinks, the chat shows "💭 thinking… (N words)". `think_max_tokens` (1,500) caps runaway thinking, and if it is reached, the request is repeated without thinking. Set `"think": true` or `false` to always or never think.
* **A broken-off answer.** Now and then Ollama can't parse a tool call the model is writing and ends the answer (its log says `tool call parsing failed`). The cat then simply asks once more instead of showing an error.
* **Waiting.** A watch that fires while the cat is busy waits until the task is done; while you type in the chat it waits up to a minute so the input box doesn't lock mid-sentence; on the lock screen it waits until you're back. Checks that fail now and then are retried; a watch that keeps failing (30 times) stops and the cat tells you why.
* **Picking up the cat.** While you carry the cat, its window holds the mouse capture (Qt takes it on every press), so Windows sends it the release wherever you let go. The safety net for a release that went somewhere else (a popup or a UAC prompt took the mouse) only acts when the capture is gone. It used to trust `GetAsyncKeyState` alone, which reads "not pressed" while the button is held whenever an app running as administrator is in front, and for touch and pen input; the cat was dropped after 0.1 s and fell back to where it was. A press right after a click (which Qt reports as a double-click) still picks the cat up; only a double-click without dragging makes it hop.
* **Ollama offline, model missing or timeouts.** These produce cat-voice errors with the `ollama serve` or `ollama pull` hint. Networking runs in a `QThread`, so the cat keeps moving.
* **Menu at a screen edge.** `place_near` tries the right, left, above, below and diagonal spots, clamps each one into the monitor work area, and picks the one that doesn't cover the cat and is closest to it.
