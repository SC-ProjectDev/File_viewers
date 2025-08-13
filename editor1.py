# two_pane_editor.py
# A Qt (PySide6) editor with:
# - Left: directory tree (choose a folder and browse files)
# - Right: two panes
#     * Top/right: READ-ONLY preview of the selected file (never edits originals)
#     * Bottom/right: your WORK area (editable). You can copy from preview → work, then Save/Save As.
# - Line numbers, current-line highlight, basic Python syntax highlighting
# - Dark/Light theme toggle
# - Status bar with Ln/Col and file path hints
#
# How to run:
#   pip install PySide6
#   python two_pane_editor.py
#
# How to build:
#   pyinstaller --onefile --windowed --name TwoPaneEditor two_pane_editor.py
#
# Notes:
# - The preview is ALWAYS read-only. You can copy its text into the Work area with the toolbar button.
# - The Work area starts empty. "Save" will prompt for a file path the first time (i.e., Save As).
# - "Snapshot" writes a timestamped copy of your Work area to a ".history" folder next to your chosen save file
#   (or to a local "snapshots" folder if you haven't saved yet).

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QRect, QSize, QRegularExpression, QModelIndex
from PySide6.QtGui import (
    QColor,
    QPainter,
    QTextFormat,
    QSyntaxHighlighter,
    QTextCharFormat,
    QFont,
    QFontDatabase,
    QAction,
    QKeySequence,
    QFont,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
    QStatusBar,
    QSplitter,
    QToolBar,
    QTreeView,
    QFileSystemModel,
    QLabel,
    QTextEdit,
)

# ------------------------------
# Line number gutter
# ------------------------------
class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Monospace font that works across platforms
        try:
            font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        except Exception:
            font = QFont("Courier New")
        font.setPointSize(11)
        self.setFont(font)

        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._lineNumberArea = LineNumberArea(self)

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()

    # --- line numbers plumbing ---
    def lineNumberAreaWidth(self):
        digits = 1
        max_block = max(1, self.blockCount())
        while max_block >= 10:
            max_block //= 10
            digits += 1
        space = 6 + self.fontMetrics().horizontalAdvance("9") * digits
        return space

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self._lineNumberArea.scroll(0, dy)
        else:
            self._lineNumberArea.update(0, rect.y(), self._lineNumberArea.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._lineNumberArea.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self._lineNumberArea)
        bg = self.palette().alternateBase().color()
        painter.fillRect(event.rect(), bg)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        if QApplication.instance().palette().color(QPalette.Window).lightness() > 128:
            painter.setPen(QColor("black"))
        else:
            painter.setPen(QColor("white"))

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(
                    0,
                    top,
                    self._lineNumberArea.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    # --- niceties ---
    def highlightCurrentLine(self):
        if self.isReadOnly():
            # still highlight, but lighter
            selection = QTextEdit.ExtraSelection()
            line_color = self.palette().alternateBase().color()
            line_color.setAlpha(60)
            selection.format.setBackground(line_color)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            self.setExtraSelections([selection])
            return
        selection = QTextEdit.ExtraSelection()
        line_color = self.palette().alternateBase().color()
        line_color.setAlpha(90)
        selection.format.setBackground(line_color)
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])


# ------------------------------
# Simple Python syntax highlighter (extend as needed)
# ------------------------------
class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []

        def fmt(color: str, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        keyword_format = fmt("#4d7cfe", bold=True)
        keywords = (
            "and|as|assert|break|class|continue|def|del|elif|else|except|False|finally|for|from|global|if|import|in|is|"
            "lambda|None|nonlocal|not|or|pass|raise|return|True|try|while|with|yield"
        )
        self.rules.append((QRegularExpression(rf"\b(?:{keywords})\b"), keyword_format))

        builtin_format = fmt("#8a2be2")
        builtins = "len|range|print|dict|list|set|tuple|int|float|str|bool|type|isinstance|enumerate|zip|map|filter|open"
        self.rules.append((QRegularExpression(rf"\b(?:{builtins})\b"), builtin_format))

        number_format = fmt("#e879f9")
        self.rules.append((QRegularExpression(r"\b[0-9]+(\.[0-9]+)?\b"), number_format))

        string_format = fmt("#16a34a")
        self.rules.append((QRegularExpression(r'\".*?\"'), string_format))
        self.rules.append((QRegularExpression(r"\'.*?\''"), string_format))
        self.rules.append((QRegularExpression(r"\'.*?\'"), string_format))

        comment_format = fmt("#9aa0a6", italic=True)
        self.rules.append((QRegularExpression(r"#.*"), comment_format))

    def highlightBlock(self, text):
        for regex, form in self.rules:
            it = regex.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), form)


# ------------------------------
# Theme helpers
# ------------------------------
class Theme:
    LIGHT = "light"
    DARK = "dark"


def apply_theme(app: QApplication, theme: str):
    if theme == Theme.DARK:
        dark = app.palette()
        dark.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        dark.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
        dark.setColor(QPalette.ColorRole.Base, QColor(20, 20, 20))
        dark.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 40, 40))
        dark.setColor(QPalette.ColorRole.ToolTipBase, QColor(30, 30, 30))
        dark.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
        dark.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
        dark.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
        dark.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
        dark.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        dark.setColor(QPalette.ColorRole.Highlight, QColor(64, 128, 255))
        dark.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        dark.setColor(QPalette.ColorRole.PlaceholderText, QColor(160, 160, 160))
        app.setPalette(dark)
        app.setStyleSheet("QToolTip { color: #eee; background-color: #222; border: 1px solid #555; }")
    else:
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet("")


# ------------------------------
# Main window
# ------------------------------
class MainWindow(QMainWindow):
    def __init__(self, start_path: Path | None = None):
        super().__init__()
        self.setWindowTitle("Two-Pane Editor[*]")
        self.resize(1200, 750)

        self._work_path: Path | None = None

        # --- Left: directory tree ---
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setReadOnly(True)
        # show files and dirs; you can restrict with setNameFilters if you want only *.txt;*.py
        # self.fs_model.setNameFilters(["*.txt", "*.py", "*.md", "*.json"])
        # self.fs_model.setNameFilterDisables(False)

        self.tree = QTreeView(self)
        self.tree.setModel(self.fs_model)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setHeaderHidden(False)
        self.tree.doubleClicked.connect(self._maybe_preview)

        root = str(start_path or Path.cwd())
        root_index = self.fs_model.setRootPath(root)
        self.tree.setRootIndex(root_index)
        # Tidy columns: Name, Size, Type, Date Modified
        self.tree.setColumnWidth(0, 260)
        for col, w in [(1, 90), (2, 120), (3, 160)]:
            self.tree.setColumnWidth(col, w)

        # --- Right: two editors (preview + work) ---
        self.preview_editor = CodeEditor()
        self.preview_editor.setReadOnly(True)
        self.preview_highlighter = PythonHighlighter(self.preview_editor.document())

        self.work_editor = CodeEditor()
        self.work_highlighter = PythonHighlighter(self.work_editor.document())

        # Splitter for preview/work
        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.addWidget(self.preview_editor)
        right_split.addWidget(self.work_editor)
        right_split.setStretchFactor(0, 1)
        right_split.setStretchFactor(1, 1)

        # Main splitter: tree | right
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.addWidget(self.tree)
        main_split.addWidget(right_split)
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)
        self.setCentralWidget(main_split)

        # --- Toolbar ---
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.act_open_folder = QAction("Open Folder…", self)
        self.act_open_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.act_open_folder.triggered.connect(self._open_folder)

        self.act_copy_to_work = QAction("Copy Preview → Work", self)
        self.act_copy_to_work.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.act_copy_to_work.triggered.connect(self._copy_preview_to_work)

        self.act_new_work = QAction("New Work Doc", self)
        self.act_new_work.setShortcut(QKeySequence.StandardKey.New)
        self.act_new_work.triggered.connect(self._new_work_doc)

        self.act_save_work = QAction("Save Work", self)
        self.act_save_work.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save_work.triggered.connect(self._save_work)

        self.act_save_work_as = QAction("Save Work As…", self)
        self.act_save_work_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_work_as.triggered.connect(self._save_work_as)

        self.act_snapshot = QAction("Snapshot", self)
        self.act_snapshot.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.act_snapshot.triggered.connect(self._snapshot_work)

        self.act_toggle_wrap = QAction("Word Wrap", self)
        self.act_toggle_wrap.setCheckable(True)
        self.act_toggle_wrap.setChecked(False)
        self.act_toggle_wrap.triggered.connect(self._toggle_wrap)

        self.act_theme = QAction("Dark Mode", self)
        self.act_theme.setCheckable(True)
        self.act_theme.setChecked(False)
        self.act_theme.triggered.connect(self._toggle_theme)

        for a in (
            self.act_open_folder,
            self.act_copy_to_work,
            self.act_new_work,
            self.act_save_work,
            self.act_save_work_as,
            self.act_snapshot,
            self.act_toggle_wrap,
            self.act_theme,
        ):
            tb.addAction(a)

        # --- Status bar ---
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._cursor_label = QLabel("")
        self.status.addPermanentWidget(self._cursor_label)

        self.preview_editor.cursorPositionChanged.connect(lambda: self._update_cursor_status(self.preview_editor))
        self.work_editor.cursorPositionChanged.connect(lambda: self._update_cursor_status(self.work_editor))
        self._update_cursor_status(self.work_editor)

        self._sync_titles()

    # ------------- Actions -------------
    def _open_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose folder", str(Path.cwd()))
        if not path:
            return
        root_index = self.fs_model.setRootPath(path)
        self.tree.setRootIndex(root_index)
        self.status.showMessage(f"Opened folder: {path}", 2000)

    def _maybe_preview(self, index: QModelIndex):
        if not index.isValid():
            return
        file_path = Path(self.fs_model.filePath(index))
        if file_path.is_dir():
            return
        try:
            # Attempt UTF-8 read; if it fails, show an error
            text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Preview failed", f"Could not preview file:\n{file_path}\n\n{e}")
            return
        self.preview_editor.setPlainText(text)
        self.status.showMessage(f"Preview: {file_path}", 2000)

    def _copy_preview_to_work(self):
        self.work_editor.setPlainText(self.preview_editor.toPlainText())
        self.work_editor.document().setModified(True)
        # Reset work path so you don't accidentally overwrite something old
        self._work_path = None
        self._sync_titles()
        self.status.showMessage("Copied preview to work area (unsaved)", 2000)

    def _new_work_doc(self):
        if not self._ask_to_save_work_if_dirty():
            return
        self.work_editor.clear()
        self.work_editor.document().setModified(False)
        self._work_path = None
        self._sync_titles()

    def _save_work(self) -> bool:
        if self._work_path is None:
            return self._save_work_as()
        try:
            self._work_path.write_text(self.work_editor.toPlainText(), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not save file:\n{e}")
            return False
        self.work_editor.document().setModified(False)
        self.status.showMessage(f"Saved: {self._work_path}", 1500)
        self._sync_titles()
        return True

    def _save_work_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Work As",
            str(self._work_path or Path.cwd()),
            "All files (*)"
        )
        if not path:
            return False
        self._work_path = Path(path)
        return self._save_work()

    def _snapshot_work(self):
        text = self.work_editor.toPlainText()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        if self._work_path is not None:
            base_dir = self._work_path.parent / ".history"
            base_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{self._work_path.stem}-{timestamp}{self._work_path.suffix}"
            snap_path = base_dir / fname
        else:
            base_dir = Path.cwd() / "snapshots"
            base_dir.mkdir(parents=True, exist_ok=True)
            snap_path = base_dir / f"unsaved-{timestamp}.txt"
        try:
            snap_path.write_text(text, encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Snapshot failed", f"Could not write snapshot:\n{e}")
            return
        self.status.showMessage(f"Snapshot saved: {snap_path}", 2000)

    def _toggle_wrap(self, checked: bool):
        mode = QPlainTextEdit.LineWrapMode.WidgetWidth if checked else QPlainTextEdit.LineWrapMode.NoWrap
        self.preview_editor.setLineWrapMode(mode)
        self.work_editor.setLineWrapMode(mode)

    def _toggle_theme(self, checked: bool):
        app = QApplication.instance()
        apply_theme(app, Theme.DARK if checked else Theme.LIGHT)
        # refresh highlight backgrounds
        self.preview_editor.highlightCurrentLine()
        self.work_editor.highlightCurrentLine()

    # ------------- Helpers -------------
    def _ask_to_save_work_if_dirty(self) -> bool:
        if not self.work_editor.document().isModified():
            return True
        btn = QMessageBox.question(
            self,
            "Unsaved changes",
            "Your Work document has unsaved changes. Save them?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if btn == QMessageBox.StandardButton.Save:
            return self._save_work()
        if btn == QMessageBox.StandardButton.Discard:
            return True
        return False

    def _sync_titles(self):
        work_name = self._work_path.name if self._work_path else "(unsaved)"
        mod_mark = "*" if self.work_editor.document().isModified() else ""
        self.setWindowTitle(f"Two-Pane Editor — Work: {work_name}{mod_mark}")

    def _update_cursor_status(self, which: CodeEditor):
        c = which.textCursor()
        line = c.blockNumber() + 1
        col = c.positionInBlock() + 1
        role = "Work" if which is self.work_editor else "Preview"
        self._cursor_label.setText(f"{role} Ln {line}, Col {col}")

    def closeEvent(self, event):
        if self._ask_to_save_work_if_dirty():
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    apply_theme(app, Theme.LIGHT)  # start in light; use toolbar toggle for dark
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
