Two-Pane Editor

A PySide6-based desktop application for browsing, previewing, and editing files in a dual-pane interface.
The left pane shows a directory tree, the right pane has a read-only file preview (top) and a work area (bottom) for editing.

Features

Directory tree browser to navigate folders and files.

Read-only preview pane to safely view files without modifying them.

Editable work area for creating or editing documents.

Copy from preview to work area with a single click.

Save / Save As with automatic unsaved-change prompts.

Snapshot feature: stores timestamped versions in .history or snapshots folders.

Python syntax highlighting, line numbers, and current-line highlighting.

Dark/Light theme toggle.

Word-wrap toggle.

Status bar with line/column position and file hints.

Requirements
pip install PySide6

How to Run
python two_pane_editor.py

Build Executable
pyinstaller --onefile --windowed --name TwoPaneEditor two_pane_editor.py

Keyboard Shortcuts

Open Folder — Ctrl+Shift+O

Copy Preview → Work — Ctrl+Shift+C

New Work Doc — Ctrl+N

Save Work — Ctrl+S

Save Work As — Ctrl+Shift+S (snapshot uses same shortcut but from toolbar)

Toggle Word Wrap — Toolbar button

Toggle Dark Mode — Toolbar button

Notes

The preview is always read-only to protect original files.

First-time saving in the work area prompts for a file path.

Snapshots are auto-saved copies with timestamps for version history.