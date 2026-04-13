from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal

from .job_session import JobSession
from .worker_run_dialog import WorkerRunDialog


class _WorkerCard(QWidget):
    """Collapsible card for a single worker (potentially multiple versions)."""

    run_requested = pyqtSignal(dict)

    def __init__(self, name: str, description: str, entries: list[dict], parent=None):
        super().__init__(parent)
        self.setObjectName("npWorkerCard")
        self._entries = entries
        self._expanded = len(entries) > 1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(0)

        # header row
        header = QHBoxLayout()
        header.setSpacing(8)

        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("npWorkerName")
        info.addWidget(name_lbl)
        desc_lbl = QLabel(description)
        desc_lbl.setObjectName("npWorkerDesc")
        info.addWidget(desc_lbl)
        header.addLayout(info, 1)

        self._chevron = QPushButton()
        self._chevron.setObjectName("npChevron")
        self._chevron.setFixedSize(28, 28)
        self._chevron.setCursor(Qt.PointingHandCursor)
        self._chevron.clicked.connect(self._toggle)
        header.addWidget(self._chevron, 0, Qt.AlignTop)

        outer.addLayout(header)

        # versions container
        self._versions_widget = QWidget()
        v_lay = QVBoxLayout(self._versions_widget)
        v_lay.setContentsMargins(0, 6, 0, 0)
        v_lay.setSpacing(0)

        sorted_entries = sorted(
            entries, key=lambda e: _version_sort_key(e.get("version", "?"))
        )
        for i, entry in enumerate(sorted_entries):
            if i > 0:
                sep = QFrame()
                sep.setObjectName("npVersionSep")
                sep.setFixedHeight(1)
                v_lay.addWidget(sep)
            ver_btn = QPushButton(entry.get("version", "?"))
            ver_btn.setObjectName("npVersionBtn")
            ver_btn.setCursor(Qt.PointingHandCursor)
            ver_btn.clicked.connect(
                lambda _=False, e=entry: self.run_requested.emit(e)
            )
            v_lay.addWidget(ver_btn)

        outer.addWidget(self._versions_widget)
        self._update_chevron()
        self._versions_widget.setVisible(self._expanded)

    def _toggle(self):
        self._expanded = not self._expanded
        self._versions_widget.setVisible(self._expanded)
        self._update_chevron()

    def _update_chevron(self):
        self._chevron.setText("\u2303" if self._expanded else "\u2304")


class _SubmittedJobCard(QWidget):
    """Clickable card for a submitted job in the Submitted tab."""

    clicked = pyqtSignal()

    def __init__(self, session: JobSession, parent=None):
        super().__init__(parent)
        self._session = session
        self.setObjectName("npWorkerCard")
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)

        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(f"{session.worker_name}  v{session.version}")
        name_lbl.setObjectName("npWorkerName")
        info.addWidget(name_lbl)
        sid_lbl = QLabel(session.session_id)
        sid_lbl.setObjectName("npWorkerDesc")
        info.addWidget(sid_lbl)
        lay.addLayout(info, 1)

        self._status_lbl = QLabel(session.status)
        self._status_lbl.setObjectName("npStatusBadge")
        lay.addWidget(self._status_lbl, 0, Qt.AlignVCenter)

        session.status_changed.connect(self._on_status_changed)

    def _on_status_changed(self, status: str):
        self._status_lbl.setText(status)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class WorkersPage(QWidget):
    """Team Worker Version Management Dashboard with Workers and Submitted tabs."""

    refresh_clicked = pyqtSignal()
    logout_clicked = pyqtSignal()
    back_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: list[JobSession] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 16)
        root.setSpacing(12)

        # back button
        back_btn = QPushButton("\u2190  Back")
        back_btn.setObjectName("npBackBtn")
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setFixedHeight(24)
        back_btn.clicked.connect(self.back_clicked.emit)
        root.addWidget(back_btn, 0, Qt.AlignLeft)

        # title row
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel("Team Worker Version\nManagement Dashboard")
        title.setObjectName("npWorkersTitle")
        title.setWordWrap(True)
        title_row.addWidget(title, 1)

        refresh = QPushButton("Refresh")
        refresh.setObjectName("npRefreshBtn")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setFixedHeight(30)
        refresh.clicked.connect(self.refresh_clicked.emit)
        title_row.addWidget(refresh, 0, Qt.AlignTop)

        logout = QPushButton("Logout")
        logout.setObjectName("npLogoutBtn")
        logout.setCursor(Qt.PointingHandCursor)
        logout.setFixedHeight(30)
        logout.clicked.connect(self.logout_clicked.emit)
        title_row.addWidget(logout, 0, Qt.AlignTop)

        root.addLayout(title_row)

        # divider
        div = QFrame()
        div.setObjectName("npVersionSep")
        div.setFixedHeight(1)
        root.addWidget(div)

        # tab bar
        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)

        self._workers_tab_btn = QPushButton("Workers")
        self._workers_tab_btn.setObjectName("npTabBtn")
        self._workers_tab_btn.setCheckable(True)
        self._workers_tab_btn.setChecked(True)
        self._workers_tab_btn.setCursor(Qt.PointingHandCursor)
        self._workers_tab_btn.clicked.connect(lambda: self._switch_tab(0))
        tab_row.addWidget(self._workers_tab_btn)

        self._submitted_tab_btn = QPushButton("Submitted")
        self._submitted_tab_btn.setObjectName("npTabBtn")
        self._submitted_tab_btn.setCheckable(True)
        self._submitted_tab_btn.setCursor(Qt.PointingHandCursor)
        self._submitted_tab_btn.clicked.connect(lambda: self._switch_tab(1))
        tab_row.addWidget(self._submitted_tab_btn)

        tab_row.addStretch()
        root.addLayout(tab_row)

        # stacked content
        self._content_stack = QStackedWidget()

        # index 0: workers scroll
        self._workers_scroll = QScrollArea()
        self._workers_scroll.setWidgetResizable(True)
        self._workers_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        empty = QLabel("No workers loaded yet.")
        empty.setObjectName("npEmptyLabel")
        empty.setAlignment(Qt.AlignCenter)
        self._workers_scroll.setWidget(empty)
        self._content_stack.addWidget(self._workers_scroll)

        # index 1: submitted scroll
        self._submitted_scroll = QScrollArea()
        self._submitted_scroll.setWidgetResizable(True)
        self._submitted_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._content_stack.addWidget(self._submitted_scroll)
        self._rebuild_submitted_list()

        root.addWidget(self._content_stack)

    # ── tabs ──────────────────────────────────────────────────────

    def _switch_tab(self, index: int):
        self._content_stack.setCurrentIndex(index)
        self._workers_tab_btn.setChecked(index == 0)
        self._submitted_tab_btn.setChecked(index == 1)

    # ── public API ────────────────────────────────────────────────

    def set_workers_data(self, tenants: list[dict]) -> None:
        """Populate the Workers tab."""
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        any_workers = False

        for tenant in tenants:
            team_name = tenant.get("name", "Unknown Team")
            workers_raw: list[dict] = tenant.get("workers", [])
            if not workers_raw:
                continue
            any_workers = True

            heading = QLabel(team_name)
            heading.setObjectName("npTeamHeading")
            lay.addWidget(heading)

            grouped = _group_workers(workers_raw)
            for worker_name, entries in grouped.items():
                desc = entries[0].get("description", "")
                card = _WorkerCard(worker_name, desc, entries, content)
                card.run_requested.connect(self._open_run_dialog)
                lay.addWidget(card)

            lay.addSpacerItem(
                QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed)
            )

        if not any_workers:
            empty_lbl = QLabel("No workers found for any team.")
            empty_lbl.setObjectName("npEmptyLabel")
            empty_lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(empty_lbl)

        lay.addStretch(1)
        self._workers_scroll.setWidget(content)

    # ── run dialog ────────────────────────────────────────────────

    def _get_current_stylesheet(self) -> str:
        """Walk up the parent chain to find the active NikaPlanet stylesheet."""
        w = self.parentWidget()
        while w:
            ss = w.styleSheet()
            if ss:
                return ss
            w = w.parentWidget()
        from .styles import DARK_STYLESHEET
        return DARK_STYLESHEET

    def _open_run_dialog(self, worker_entry: dict):
        dlg = WorkerRunDialog(
            worker_entry,
            stylesheet=self._get_current_stylesheet(),
            parent=self.window(),
        )
        dlg.job_submitted.connect(self._on_job_submitted)
        dlg.exec()

    def _open_session_dialog(self, session: JobSession):
        worker = {
            "name": session.worker_name,
            "version": session.version,
            "tenantId": session.tenant_id,
        }
        dlg = WorkerRunDialog(
            worker,
            session=session,
            stylesheet=self._get_current_stylesheet(),
            parent=self.window(),
        )
        dlg.exec()

    # ── session tracking ──────────────────────────────────────────

    def clear_sessions(self):
        """Stop all running sessions and clear the list. Called on logout."""
        for session in self._sessions:
            if session.status == "RUNNING":
                session.cancel()
        self._sessions.clear()
        self._rebuild_submitted_list()

    def _on_job_submitted(self, session: JobSession):
        session.setParent(self)
        self._sessions.append(session)
        self._rebuild_submitted_list()

    def _rebuild_submitted_list(self):
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        if not self._sessions:
            empty = QLabel("No submitted jobs yet.")
            empty.setObjectName("npEmptyLabel")
            empty.setAlignment(Qt.AlignCenter)
            lay.addWidget(empty)
        else:
            for session in reversed(self._sessions):
                card = _SubmittedJobCard(session, content)
                card.clicked.connect(
                    lambda s=session: self._open_session_dialog(s)
                )
                lay.addWidget(card)

        lay.addStretch(1)
        self._submitted_scroll.setWidget(content)


# ── helpers ────────────────────────────────────────────────────────

def _group_workers(workers: list[dict]) -> dict[str, list[dict]]:
    """Group a flat worker list by name, preserving insertion order."""
    groups: dict[str, list[dict]] = {}
    for w in workers:
        groups.setdefault(w.get("name", "unknown"), []).append(w)
    return groups


def _version_sort_key(v: str):
    """Sort version strings numerically (best-effort)."""
    parts = []
    for seg in v.lstrip("v").split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(seg)
    return parts
