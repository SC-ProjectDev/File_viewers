📝 Two-Pane Editor

A sleek, PySide6-powered desktop application for browsing, previewing, and editing files — all within a clean, dual-pane interface.

✨ Overview

Two-Pane Editor helps you quickly navigate directories, preview files safely, and edit with ease. Its intuitive split layout boosts productivity for developers, writers, and power users alike.

Left Pane: Browse through the directory tree.

Right Pane:

🔍 Top: Read-only preview — view files securely.

✍️ Bottom: Work area — create or edit content.

🚀 Features

🗂 Directory Tree — Easily navigate files and folders.

🔒 Read-Only Preview — View content safely without risk of modification.

✏️ Work Area — Create or edit files freely.

🔁 One-Click Copy — Transfer content from Preview → Work area.

💾 Smart Save — Auto-prompts for unsaved changes. Includes:

Save

Save As

🕒 Snapshot System — Auto-saves timestamped versions in .history/ or snapshots/.

🧠 Smart Editor Tools:

Python syntax highlighting

Line numbers

Highlighted current line

🎨 Themes — Toggle between Dark and Light modes.

📝 Word Wrap — Optional toggle for cleaner readability.

📊 Status Bar — Shows line/column info and file hints.

🛠 Requirements
pip install PySide6

▶️ How to Run
python two_pane_editor.py

📦 Build Executable

Using PyInstaller:

pyinstaller --onefile --windowed --name TwoPaneEditor two_pane_editor.py

⌨️ Keyboard Shortcuts
Action	Shortcut
Open Folder	Ctrl+Shift+O
Copy Preview → Work	Ctrl+Shift+C
New Work Document	Ctrl+N
Save Work	Ctrl+S
Save As / Snapshot	Ctrl+Shift+S (same shortcut, toolbar toggle)
Toggle Word Wrap	Toolbar button
Toggle Dark Mode	Toolbar button
🧾 Notes

🛡 Preview is always read-only — ensures original files stay intact.

💡 First-time Save — prompts for file path in the Work area.

🕘 Snapshots — every saved version is auto-backed up with timestamps.