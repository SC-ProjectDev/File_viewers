# project_trakcer.py
# A minimal-but-complete PySide6 project tracker with:
# - Two-pane layout (list + form)
# - Search filter on the left
# - Status color dots (Completed/In Progress/Not Started/Blocked/On Hold)
# - Line-numbered Goals/Notes with MM/DD/YYYY highlighter (“highlighter green”)
# - Light/Dark theme toggle (remembered)
# - Autosave (debounced + on close) to JSON with .bak backups and atomic write
# - KPI panel (Open, Completed, In Progress, Completion Rate, Avg Lead Time, Avg WIP Age)
# - Core actions: New, Duplicate, Delete, Start, Mark Complete, Quick Timestamp, Save As, Open Data File
#
# Tested with PySide6 6.6+

import json
import os
import sys
import uuid
import shutil
import time
from dataclasses import dataclass, asdict
from datetime import datetime, date, timezone
from typing import List, Optional, Dict

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QSortFilterProxyModel, QTimer, QModelIndex, QRect
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QPainter, QFont, QAction, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListView,
    QLineEdit, QLabel, QFormLayout, QComboBox, QDateEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QMessageBox, QFileDialog, QToolBar, QStyle, QSizePolicy, QFrame
)

APP_NAME = "ProjectTrakcer"  # yes: chaotic on purpose 😉
ORG_NAME = "UnhingedLabs"

# --------------------------
# Utilities / constants
# --------------------------
STATUSES = ["not_started", "in_progress", "completed", "blocked", "on_hold"]
STATUS_LABEL = {
    "not_started": "Not Started",
    "in_progress": "In Progress",
    "completed": "Completed",
    "blocked": "Blocked",
    "on_hold": "On Hold",
}
PRIORITIES = ["low", "medium", "high", "urgent"]
PRIORITY_LABEL = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "urgent": "Urgent",
}
STATUS_COLOR = {
    "not_started": QColor("#FFA500"),  # orange
    "in_progress": QColor("#7E57C2"),  # purple
    "completed": QColor("#2E7D32"),    # green
    "blocked": QColor("#D32F2F"),      # red
    "on_hold": QColor("#1976D2"),      # blue
}
HIGHLIGHTER_GREEN = QColor("#B7F774")

DATE_DISPLAY_FMT = "MM/dd/yyyy"
ISO_FMT = "%Y-%m-%d"

def today_iso():
    return date.today().strftime(ISO_FMT)

def iso_to_qdate(iso: Optional[str]) -> QtCore.QDate:
    if not iso:
        return QtCore.QDate()
    try:
        d = datetime.strptime(iso, ISO_FMT).date()
        return QtCore.QDate(d.year, d.month, d.day)
    except Exception:
        return QtCore.QDate()

def qdate_to_iso(qd: QtCore.QDate) -> Optional[str]:
    if not qd or not qd.isValid():
        return None
    return date(qd.year(), qd.month(), qd.day()).strftime(ISO_FMT)


# --------------------------
# Data model
# --------------------------
@dataclass
class Project:
    id: str
    name: str
    status: str
    priority: str
    date_assigned: Optional[str]  # ISO YYYY-MM-DD
    date_completed: Optional[str] # ISO YYYY-MM-DD
    goals: str
    notes: str

def sample_projects() -> List[Project]:
    return [
        Project(
            id=str(uuid.uuid4()),
            name="Landing Page Revamp",
            status="in_progress",
            priority="high",
            date_assigned=today_iso(),
            date_completed=None,
            goals="Polish hero; improve CLS; add A/B test for CTA.\nTarget ship: 09/15/2025",
            notes="Kickoff 08/10/2025\nQA window: 09/10/2025–09/14/2025",
        ),
        Project(
            id=str(uuid.uuid4()),
            name="Ops Runbook",
            status="not_started",
            priority="medium",
            date_assigned=None,
            date_completed=None,
            goals="Document on-call rotations, playbooks, and escalation.\nDue 08/31/2025",
            notes="Ask SRE for latest pager policy by 08/20/2025.",
        ),
        Project(
            id=str(uuid.uuid4()),
            name="Refactor Auth",
            status="completed",
            priority="urgent",
            date_assigned="2025-07-01",
            date_completed="2025-08-01",
            goals="Replace legacy tokens; add refresh flow; rotate keys.",
            notes="Backfilled tests on 07/20/2025. Retro on 08/05/2025.",
        ),
    ]


# --------------------------
# Storage with autosave
# --------------------------
class ProjectStore(QtCore.QObject):
    dirtyChanged = QtCore.Signal(bool)
    dataChanged = QtCore.Signal()  # whenever projects list mutates

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.projects: List[Project] = []
        self.version = 1
        self.meta = {"created": datetime.now(timezone.utc).isoformat(), "last_modified": None}
        self._dirty = False

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.timeout.connect(self._save_now)

    def set_dirty(self, dirty: bool, debounce_ms: int = 1200):
        prev = self._dirty
        self._dirty = dirty
        if prev != dirty:
            self.dirtyChanged.emit(dirty)
        if dirty:
            self._autosave.start(debounce_ms)

    def is_dirty(self) -> bool:
        return self._dirty

    def load(self):
        if not os.path.exists(self.path):
            # create with samples
            self.projects = sample_projects()
            self.save_atomic()
            self.dataChanged.emit()
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.version = data.get("version", 1)
        self.meta = data.get("meta", self.meta)
        self.projects = [Project(**p) for p in data.get("projects", [])]
        self.dataChanged.emit()

    def to_dict(self) -> Dict:
        return {
            "version": self.version,
            "meta": {
                **self.meta,
                "last_modified": datetime.now(timezone.utc).isoformat()
            },
            "projects": [asdict(p) for p in self.projects]
        }

    def save_atomic(self):
        # Write to temp then replace + keep .bak
        data = self.to_dict()
        tmp_path = self.path + ".tmp"
        bak_path = self.path + ".bak"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # backup current
        if os.path.exists(self.path):
            shutil.copy2(self.path, bak_path)
        os.replace(tmp_path, self.path)
        self.set_dirty(False)

    def _save_now(self):
        try:
            self.save_atomic()
        except Exception as e:
            QMessageBox.critical(None, "Save Error", f"Failed to autosave:\n{e}")

    def add_project(self, p: Project):
        self.projects.append(p)
        self.set_dirty(True)
        self.dataChanged.emit()

    def delete_project(self, pid: str):
        self.projects = [p for p in self.projects if p.id != pid]
        self.set_dirty(True)
        self.dataChanged.emit()

    def find_by_id(self, pid: str) -> Optional[Project]:
        for p in self.projects:
            if p.id == pid:
                return p
        return None


# --------------------------
# Qt Models / Delegates
# --------------------------
class ProjectListModel(QtCore.QAbstractListModel):
    IdRole = Qt.UserRole + 1
    StatusRole = Qt.UserRole + 2
    PriorityRole = Qt.UserRole + 3

    def __init__(self, store: ProjectStore):
        super().__init__()
        self.store = store
        self.store.dataChanged.connect(self._on_store_changed)

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.store.projects)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        p = self.store.projects[index.row()]
        if role == Qt.DisplayRole:
            return p.name
        if role == ProjectListModel.IdRole:
            return p.id
        if role == ProjectListModel.StatusRole:
            return p.status
        if role == ProjectListModel.PriorityRole:
            return p.priority
        return None

    def _on_store_changed(self):
        self.beginResetModel()
        self.endResetModel()

class StatusDotDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index):
        painter.save()
        # fill selection
        if option.state & QtWidgets.QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        rect = option.rect
        name = index.data(Qt.DisplayRole) or ""
        status = index.data(ProjectListModel.StatusRole)
        color = STATUS_COLOR.get(status, QColor("#9E9E9E"))

        # draw dot
        dot_d = min(rect.height(), 14)
        dot_x = rect.left() + 8
        dot_y = rect.center().y() - dot_d // 2
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRect(dot_x, dot_y, dot_d, dot_d))

        # draw text
        text_rect = QRect(dot_x + dot_d + 8, rect.top(), rect.width() - (dot_d + 24), rect.height())
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.TextSingleLine, name)
        painter.restore()

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QtCore.QSize(base.width(), max(base.height(), 24))


# --------------------------
# Line-numbered editor + date highlighter
# --------------------------
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QtCore.QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint_event(event)

class LinedPlainTextEdit(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

        # make it nicer for long notes
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        space = 3 + self.fontMetrics().horizontalAdvance('9') * digits
        return space + 10

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), self.palette().alternateBase())
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(self.palette().text().color())
                fm = self.fontMetrics()
                painter.drawText(0, int(top), self._line_area.width() - 4, fm.height(),
                                 Qt.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def highlight_current_line(self):
        if self.isReadOnly():
            self.setExtraSelections([])
            return
        selection = QtWidgets.QTextEdit.ExtraSelection()
        line_color = self.palette().alternateBase().color().lighter(110)
        selection.format.setBackground(line_color)
        selection.format.setProperty(QTextCharFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])


class DateHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self.fmt = QTextCharFormat()
        self.fmt.setBackground(HIGHLIGHTER_GREEN)

        # MM/DD/YYYY (accepts 1 or 2 digits for M/D)
        self.pattern = QtCore.QRegularExpression(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12][0-9]|3[01])/\d{4}\b")

    def highlightBlock(self, text: str):
        it = self.pattern.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), self.fmt)


# --------------------------
# KPI Panel
# --------------------------
class KpiPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        self.labels = {}
        for key in ["Open", "Completed", "In Progress", "Completion Rate", "Avg Lead Time (d)", "Avg WIP Age (d)"]:
            w = self._kpi_chip(key, "-")
            layout.addWidget(w)

    def _kpi_chip(self, title, value):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setObjectName("kpiFrame")
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 6, 8, 6)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600;")
        val = QLabel(value)
        val.setStyleSheet("font-size: 14px;")
        v.addWidget(t)
        v.addWidget(val)
        self.labels[title] = val
        return frame

    def update_values(self, store: ProjectStore):
        total = len(store.projects)
        completed = sum(1 for p in store.projects if p.status == "completed")
        in_prog = sum(1 for p in store.projects if p.status == "in_progress")
        open_count = total - completed

        # lead time: assigned->completed for completed ones
        lead_times = []
        for p in store.projects:
            if p.status == "completed" and p.date_assigned and p.date_completed:
                try:
                    da = datetime.strptime(p.date_assigned, ISO_FMT).date()
                    dc = datetime.strptime(p.date_completed, ISO_FMT).date()
                    if dc >= da:
                        lead_times.append((dc - da).days)
                except Exception:
                    pass
        avg_lead = round(sum(lead_times) / len(lead_times), 1) if lead_times else 0.0

        # WIP age: today - assigned for open ones with assigned set
        ages = []
        tday = date.today()
        for p in store.projects:
            if p.status != "completed" and p.date_assigned:
                try:
                    da = datetime.strptime(p.date_assigned, ISO_FMT).date()
                    if tday >= da:
                        ages.append((tday - da).days)
                except Exception:
                    pass
        avg_wip = round(sum(ages) / len(ages), 1) if ages else 0.0

        comp_rate = f"{(completed / total * 100):.0f}%" if total else "0%"

        self.labels["Open"].setText(str(open_count))
        self.labels["Completed"].setText(str(completed))
        self.labels["In Progress"].setText(str(in_prog))
        self.labels["Completion Rate"].setText(comp_rate)
        self.labels["Avg Lead Time (d)"].setText(str(avg_lead))
        self.labels["Avg WIP Age (d)"].setText(str(avg_wip))


# --------------------------
# Main window
# --------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Project Trakcer")
        self.resize(1100, 720)

        # Settings
        self.settings = QtCore.QSettings(ORG_NAME, APP_NAME)
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects.json")
        self.current_path = self.settings.value("current_path", default_path)
        theme = self.settings.value("theme", "light")
        if theme == "dark":
            self.apply_dark_palette()
        else:
            self.apply_light_palette()

        # Store and models
        self.store = ProjectStore(self.current_path)
        self.store.load()
        self.store.dirtyChanged.connect(self.on_dirty_changed)
        self.store.dataChanged.connect(self.on_store_changed)

        self.list_model = ProjectListModel(self.store)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.list_model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(0)

        # Build UI
        self._build_menus()
        self._build_ui()

        # Select first item if any
        if self.proxy.rowCount() > 0:
            self.list_view.setCurrentIndex(self.proxy.index(0, 0))
            self._load_selected_into_form()

    # ---------- UI
    def _build_menus(self):
        tb = QToolBar("Main")
        tb.setIconSize(QtCore.QSize(20, 20))
        self.addToolBar(tb)

        self.act_new = QAction(self.style().standardIcon(QStyle.SP_FileIcon), "New", self)
        self.act_dup = QAction(self.style().standardIcon(QStyle.SP_FileLinkIcon), "Duplicate", self)
        self.act_del = QAction(self.style().standardIcon(QStyle.SP_TrashIcon), "Delete", self)
        self.act_start = QAction("Start", self)
        self.act_complete = QAction("Mark Complete", self)
        self.act_timestamp = QAction("Insert Timestamp", self)

        self.act_open = QAction("Open Data File…", self)
        self.act_saveas = QAction("Save As…", self)
        self.act_theme = QAction("Toggle Light/Dark", self)
        self.act_quit = QAction("Quit", self)

        for a in [self.act_new, self.act_dup, self.act_del, self.act_start, self.act_complete, self.act_timestamp]:
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_open)
        tb.addAction(self.act_saveas)
        tb.addSeparator()
        tb.addAction(self.act_theme)

        # Menubar (minimal)
        m_file = self.menuBar().addMenu("&File")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_saveas)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)
        m_view = self.menuBar().addMenu("&View")
        m_view.addAction(self.act_theme)

        # shortcuts
        self.act_new.setShortcut("Ctrl+N")
        self.act_quit.setShortcut("Ctrl+Q")

        # connect
        self.act_new.triggered.connect(self.on_new)
        self.act_dup.triggered.connect(self.on_duplicate)
        self.act_del.triggered.connect(self.on_delete)
        self.act_start.triggered.connect(self.on_start)
        self.act_complete.triggered.connect(self.on_complete)
        self.act_timestamp.triggered.connect(self.on_insert_timestamp)

        self.act_open.triggered.connect(self.on_open_file)
        self.act_saveas.triggered.connect(self.on_save_as)
        self.act_theme.triggered.connect(self.on_toggle_theme)
        self.act_quit.triggered.connect(self.close)

    def _build_ui(self):
        splitter = QSplitter(self)
        self.setCentralWidget(splitter)

        # Left panel
        left = QWidget()
        vl = QVBoxLayout(left)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search projects…")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)

        self.list_view = QListView()
        self.list_view.setModel(self.proxy)
        self.list_view.setItemDelegate(StatusDotDelegate(self.list_view))
        self.list_view.selectionModel().selectionChanged.connect(self._load_selected_into_form)

        self.kpis = KpiPanel()

        vl.addWidget(self.search)
        vl.addWidget(self.list_view, 1)
        vl.addWidget(self.kpis)

        # Right panel (form inside a scroll area)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right = QWidget()
        right_scroll.setWidget(right)
        form = QFormLayout(right)
        form.setLabelAlignment(Qt.AlignRight)

        self._loading = False  # guard to prevent feedback loops

        self.e_name = QLineEdit()
        self.c_status = QComboBox(); self.c_status.addItems([STATUS_LABEL[s] for s in STATUSES])
        self.c_priority = QComboBox(); self.c_priority.addItems([PRIORITY_LABEL[p] for p in PRIORITIES])

        self.d_assigned = QDateEdit(); self.d_assigned.setDisplayFormat(DATE_DISPLAY_FMT); self.d_assigned.setCalendarPopup(True)
        self.d_completed = QDateEdit(); self.d_completed.setDisplayFormat(DATE_DISPLAY_FMT); self.d_completed.setCalendarPopup(True)

        self.e_goals = LinedPlainTextEdit()
        self.e_notes = LinedPlainTextEdit()
        # highlighters
        self.h_goals = DateHighlighter(self.e_goals.document())
        self.h_notes = DateHighlighter(self.e_notes.document())

        # hook changes
        self.e_name.textEdited.connect(self._on_field_changed)
        self.c_status.currentIndexChanged.connect(self._on_status_changed)
        self.c_priority.currentIndexChanged.connect(self._on_field_changed)
        self.d_assigned.dateChanged.connect(self._on_field_changed)
        self.d_completed.dateChanged.connect(self._on_field_changed)
        self.e_goals.textChanged.connect(self._on_field_changed)
        self.e_notes.textChanged.connect(self._on_field_changed)

        form.addRow("Name", self.e_name)
        form.addRow("Status", self.c_status)
        form.addRow("Priority", self.c_priority)
        form.addRow("Date Assigned", self.d_assigned)
        form.addRow("Date Completed", self.d_completed)

        # spacing
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        form.addRow(sep)
        lbl_goals = QLabel("Goals"); lbl_goals.setStyleSheet("font-weight: 600;")
        lbl_notes = QLabel("Notes"); lbl_notes.setStyleSheet("font-weight: 600;")
        form.addRow(lbl_goals)
        form.addRow(self.e_goals)
        form.addRow(lbl_notes)
        form.addRow(self.e_notes)

        # Action buttons beneath editors
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("Save Now")
        self.btn_revert = QPushButton("Revert")
        self.btn_save.clicked.connect(lambda: self.store.save_atomic())
        self.btn_revert.clicked.connect(self._revert_current)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_revert)
        btn_row.addWidget(self.btn_save)
        form.addRow(btn_row)

        splitter.addWidget(left)
        splitter.addWidget(right_scroll)
        splitter.setSizes([320, 780])

    # ---------- Theme
    def apply_dark_palette(self):
        app = QApplication.instance()
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(53, 53, 53))
        pal.setColor(QPalette.WindowText, Qt.white)
        pal.setColor(QPalette.Base, QColor(35, 35, 35))
        pal.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        pal.setColor(QPalette.ToolTipBase, Qt.white)
        pal.setColor(QPalette.ToolTipText, Qt.white)
        pal.setColor(QPalette.Text, Qt.white)
        pal.setColor(QPalette.Button, QColor(53, 53, 53))
        pal.setColor(QPalette.ButtonText, Qt.white)
        pal.setColor(QPalette.BrightText, Qt.red)
        pal.setColor(QPalette.Highlight, QColor(64, 128, 255))
        pal.setColor(QPalette.HighlightedText, Qt.white)
        app.setPalette(pal)
        app.setStyle("Fusion")

    def apply_light_palette(self):
        app = QApplication.instance()
        app.setPalette(QPalette())
        app.setStyle("Fusion")

    def on_toggle_theme(self):
        # Toggle and save
        current = self.settings.value("theme", "light")
        if current == "light":
            self.apply_dark_palette()
            self.settings.setValue("theme", "dark")
        else:
            self.apply_light_palette()
            self.settings.setValue("theme", "light")

    # ---------- Actions
    def on_new(self):
        p = Project(
            id=str(uuid.uuid4()),
            name="Untitled Project",
            status="not_started",
            priority="medium",
            date_assigned=None,
            date_completed=None,
            goals="",
            notes="",
        )
        self.store.add_project(p)
        self._select_by_id(p.id)

    def on_duplicate(self):
        pid = self._current_id()
        if not pid:
            return
        orig = self.store.find_by_id(pid)
        if not orig:
            return
        p = Project(
            id=str(uuid.uuid4()),
            name=orig.name + " (Copy)",
            status=orig.status,
            priority=orig.priority,
            date_assigned=orig.date_assigned,
            date_completed=orig.date_completed,
            goals=orig.goals,
            notes=orig.notes,
        )
        self.store.add_project(p)
        self._select_by_id(p.id)

    def on_delete(self):
        pid = self._current_id()
        if not pid:
            return
        p = self.store.find_by_id(pid)
        if not p:
            return
        if QMessageBox.question(self, "Delete", f"Delete '{p.name}'? This cannot be undone.") == QMessageBox.Yes:
            self.store.delete_project(pid)

    def on_start(self):
        pid = self._current_id()
        p = self.store.find_by_id(pid) if pid else None
        if not p:
            return
        p.status = "in_progress"
        if not p.date_assigned:
            p.date_assigned = today_iso()
        self.store.set_dirty(True)
        self.store.dataChanged.emit()
        self._load_selected_into_form()

    def on_complete(self):
        pid = self._current_id()
        p = self.store.find_by_id(pid) if pid else None
        if not p:
            return
        p.status = "completed"
        if not p.date_completed:
            p.date_completed = today_iso()
        self.store.set_dirty(True)
        self.store.dataChanged.emit()
        self._load_selected_into_form()

    def on_insert_timestamp(self):
        ts = datetime.now().strftime("%m/%d/%Y %I:%M %p")
        cursor = self.e_notes.textCursor()
        cursor.movePosition(cursor.End)
        if self.e_notes.toPlainText():
            cursor.insertText("\n")
        cursor.insertText(ts + " — ")
        self.e_notes.setTextCursor(cursor)
        self.e_notes.setFocus()

    def on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Data File", os.path.dirname(self.current_path),
                                              "JSON Files (*.json)")
        if not path:
            return
        self.current_path = path
        self.settings.setValue("current_path", self.current_path)
        self.store.path = path
        self.store.load()
        if self.proxy.rowCount() > 0:
            self.list_view.setCurrentIndex(self.proxy.index(0, 0))
            self._load_selected_into_form()

    def on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save As", os.path.dirname(self.current_path),
                                              "JSON Files (*.json)")
        if not path:
            return
        self.current_path = path
        self.settings.setValue("current_path", self.current_path)
        self.store.path = path
        self.store.save_atomic()

    # ---------- Form/data binding
    def _current_id(self) -> Optional[str]:
        idx = self.list_view.currentIndex()
        if not idx.isValid():
            return None
        src = self.proxy.mapToSource(idx)
        return self.list_model.data(src, ProjectListModel.IdRole)

    def _select_by_id(self, pid: str):
        for row in range(self.list_model.rowCount()):
            idx = self.list_model.index(row, 0)
            if self.list_model.data(idx, ProjectListModel.IdRole) == pid:
                proxy_idx = self.proxy.mapFromSource(idx)
                self.list_view.setCurrentIndex(proxy_idx)
                break

    def _load_selected_into_form(self):
        pid = self._current_id()
        p = self.store.find_by_id(pid) if pid else None
        self._loading = True
        try:
            if not p:
                # clear
                self.e_name.setText("")
                self.c_status.setCurrentIndex(0)
                self.c_priority.setCurrentIndex(1)
                self.d_assigned.setDate(QtCore.QDate())
                self.d_completed.setDate(QtCore.QDate())
                self.e_goals.setPlainText("")
                self.e_notes.setPlainText("")
                return

            self.e_name.setText(p.name)
            self.c_status.setCurrentIndex(STATUSES.index(p.status))
            self.c_priority.setCurrentIndex(PRIORITIES.index(p.priority))
            self.d_assigned.setDate(iso_to_qdate(p.date_assigned))
            self.d_completed.setDate(iso_to_qdate(p.date_completed))
            self.e_goals.setPlainText(p.goals or "")
            self.e_notes.setPlainText(p.notes or "")

            # enable/disable date_completed by status
            self.d_completed.setEnabled(p.status == "completed")
        finally:
            self._loading = False

    def _revert_current(self):
        self._load_selected_into_form()

    def _on_status_changed(self):
        if self._loading:
            return
        pid = self._current_id()
        p = self.store.find_by_id(pid) if pid else None
        if not p:
            return
        p.status = STATUSES[self.c_status.currentIndex()]
        # auto-enable/disable completed date
        self.d_completed.setEnabled(p.status == "completed")
        if p.status == "completed" and not p.date_completed:
            p.date_completed = today_iso()
            self.d_completed.setDate(iso_to_qdate(p.date_completed))
        self.store.set_dirty(True)
        self.store.dataChanged.emit()

    def _on_field_changed(self):
        if self._loading:
            return
        pid = self._current_id()
        p = self.store.find_by_id(pid) if pid else None
        if not p:
            return

        p.name = self.e_name.text().strip() or "Untitled Project"
        p.priority = PRIORITIES[self.c_priority.currentIndex()]
        p.date_assigned = qdate_to_iso(self.d_assigned.date())
        p.date_completed = qdate_to_iso(self.d_completed.date()) if self.d_completed.isEnabled() else p.date_completed
        p.goals = self.e_goals.toPlainText()
        p.notes = self.e_notes.toPlainText()

        # sanity: date_completed cannot be < date_assigned
        try:
            if p.date_assigned and p.date_completed:
                da = datetime.strptime(p.date_assigned, ISO_FMT)
                dc = datetime.strptime(p.date_completed, ISO_FMT)
                if dc < da:
                    # reset completed date to assigned
                    p.date_completed = p.date_assigned
                    self.d_completed.setDate(iso_to_qdate(p.date_completed))
        except Exception:
            pass

        self.store.set_dirty(True)
        self.store.dataChanged.emit()

    # ---------- Store callbacks
    def on_dirty_changed(self, dirty: bool):
        mark = " •" if dirty else ""
        self.setWindowTitle(f"Project Trakcer{mark}")

    def on_store_changed(self):
        self.kpis.update_values(self.store)

    # ---------- Close/save
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # hard save
        if self.store.is_dirty():
            try:
                self.store.save_atomic()
            except Exception as e:
                if QMessageBox.question(self, "Save Error",
                                        f"Could not save:\n{e}\n\nQuit anyway?") != QMessageBox.Yes:
                    event.ignore()
                    return
        self.settings.setValue("current_path", self.current_path)
        super().closeEvent(event)


def main():
    QtCore.QCoreApplication.setOrganizationName(ORG_NAME)
    QtCore.QCoreApplication.setApplicationName(APP_NAME)

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
