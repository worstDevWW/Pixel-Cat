"""A small harmless test app for the desktop-agent tests (developer tool).

Window title "PixelCat Test Editor": a name field, a big text editor, a
checkbox, a SAVE button (writes nothing - it only shows "Saved!" in the status
label) and a File menu.  Prints its state as JSON lines on stdout whenever
something changes, and obeys "quit" on stdin.
Usage:  python tools/test_editor.py [x y w h]
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit,  # noqa: E402
                               QMainWindow, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)


def main() -> None:
    app = QApplication(sys.argv[:1])
    win = QMainWindow()
    win.setWindowTitle("PixelCat Test Editor")
    central = QWidget()
    lay = QVBoxLayout(central)
    row = QHBoxLayout()
    row.addWidget(QLabel("Title:"))
    name = QLineEdit()
    name.setAccessibleName("Title")
    row.addWidget(name)
    lay.addLayout(row)
    editor = QPlainTextEdit()
    editor.setAccessibleName("Editor")
    f = editor.font()
    f.setPointSize(12)
    editor.setFont(f)
    lay.addWidget(editor)
    row2 = QHBoxLayout()
    check = QCheckBox("Important")
    save = QPushButton("Save")
    status = QLabel("Not saved")
    status.setAccessibleName("Status")
    row2.addWidget(check)
    row2.addStretch(1)
    row2.addWidget(status)
    row2.addWidget(save)
    lay.addLayout(row2)
    win.setCentralWidget(central)
    menu = win.menuBar().addMenu("&File")
    act_new = menu.addAction("New")
    act_new.triggered.connect(lambda: (editor.clear(), name.clear(), status.setText("New file")))

    def report() -> None:
        print(json.dumps({"title": name.text(), "text": editor.toPlainText(), "important": check.isChecked(),
                          "status": status.text()}), flush=True)

    save.clicked.connect(lambda: (status.setText("Saved!"), report()))
    check.toggled.connect(lambda _v: report())
    geo = [int(v) for v in sys.argv[1:5]] if len(sys.argv) >= 5 else [300, 200, 900, 640]
    win.setGeometry(*geo)
    win.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    win.show()
    print(json.dumps({"ready": True}), flush=True)

    cmds: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: [cmds.put(line.strip()) for line in sys.stdin], daemon=True).start()

    def poll() -> None:
        while not cmds.empty():
            c = cmds.get()
            if c == "quit":
                app.quit()
                return
            if c == "report":
                report()
            if c.startswith("text "):       # e.g. "text Exporting..." (watch tests)
                editor.setPlainText(c[5:])
            if c == "reset":
                name.clear()
                editor.clear()
                check.blockSignals(True)
                check.setChecked(False)
                check.blockSignals(False)
                status.setText("Not saved")
        QTimer.singleShot(50, poll)

    QTimer.singleShot(50, poll)
    app.exec()


if __name__ == "__main__":
    main()
