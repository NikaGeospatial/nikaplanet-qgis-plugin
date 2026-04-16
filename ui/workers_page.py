from __future__ import annotations

import threading

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

from qgis.core import QgsMessageLog, Qgis

from .job_session import JobSession, TERMINAL_STATUSES
from .worker_run_dialog import WorkerRunDialog
from ..util.messages import PLUGIN_LOG_TAG


class _WorkerCard(QWidget):
    """Collapsible card for a single worker (potentially multiple versions)."""

    run_requested = pyqtSignal(dict)

    def __init__(self, name: str, description: str, entries: list[dict], parent=None):
        super().__init__(parent)
        self.setObjectName("npWorkerCard")
        self._expanded = len(entries) > 1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(0)

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
        self._chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron.clicked.connect(self._toggle)
        header.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignTop)

        outer.addLayout(header)

        self._versions_widget = QWidget()
        v_lay = QVBoxLayout(self._versions_widget)
        v_lay.setContentsMargins(0, 8, 0, 0)
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

            row = QHBoxLayout()
            row.setContentsMargins(0, 6, 0, 6)
            row.setSpacing(10)

            badge = QLabel(f"v{entry.get('version', '?')}")
            badge.setObjectName("npVerBadge")
            row.addWidget(badge)

            select_btn = QPushButton("Select this version")
            select_btn.setObjectName("npVersionBtn")
            select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            select_btn.clicked.connect(
                lambda _=False, e=entry: self.run_requested.emit(e)
            )
            row.addWidget(select_btn)
            row.addStretch()

            v_lay.addLayout(row)

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
    """Clickable card for a submitted job in the Sessions tab."""

    clicked = pyqtSignal()

    def __init__(self, session: JobSession, parent=None):
        super().__init__(parent)
        self._session = session
        self.setObjectName("npWorkerCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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
        lay.addWidget(self._status_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        session.status_changed.connect(self._on_status_changed)

    def _on_status_changed(self, status: str):
        self._status_lbl.setText(status)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class WorkersPage(QWidget):
    """Worker catalog and sessions dashboard."""

    refresh_clicked = pyqtSignal()
    back_clicked = pyqtSignal()

    # Internal: background thread finished fetching history.
    _history_loaded = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: list[JobSession] = []
        self._client = None

        self._history_loaded.connect(self._on_history_loaded)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 16)
        root.setSpacing(8)

        # back button
        back_btn = QPushButton("\u2190  Back")
        back_btn.setObjectName("npBackBtn")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setFixedHeight(24)
        back_btn.clicked.connect(self.back_clicked.emit)
        root.addWidget(back_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # tab bar
        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)

        self._workers_tab_btn = QPushButton("CATALOG")
        self._workers_tab_btn.setObjectName("npTabBtn")
        self._workers_tab_btn.setCheckable(True)
        self._workers_tab_btn.setChecked(True)
        self._workers_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._workers_tab_btn.clicked.connect(lambda: self._switch_tab(0))
        tab_row.addWidget(self._workers_tab_btn)

        self._submitted_tab_btn = QPushButton("SESSIONS")
        self._submitted_tab_btn.setObjectName("npTabBtn")
        self._submitted_tab_btn.setCheckable(True)
        self._submitted_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submitted_tab_btn.clicked.connect(lambda: self._switch_tab(1))
        tab_row.addWidget(self._submitted_tab_btn)

        tab_row.addStretch()

        # Refresh button — refreshes workers catalog or sessions depending
        # on which tab is active.
        refresh = QPushButton("\u21BB")
        refresh.setObjectName("npRefreshBtn")
        refresh.setToolTip("Refresh")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.setFixedSize(30, 30)
        refresh.clicked.connect(self._on_refresh)
        tab_row.addWidget(refresh)

        root.addLayout(tab_row)

        # stacked content
        self._content_stack = QStackedWidget()

        # index 0: workers scroll
        self._workers_scroll = QScrollArea()
        self._workers_scroll.setWidgetResizable(True)
        self._workers_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        empty = QLabel("No workers loaded yet.")
        empty.setObjectName("npEmptyLabel")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._workers_scroll.setWidget(empty)
        self._content_stack.addWidget(self._workers_scroll)

        # index 1: submitted scroll
        self._submitted_scroll = QScrollArea()
        self._submitted_scroll.setWidgetResizable(True)
        self._submitted_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content_stack.addWidget(self._submitted_scroll)
        self._rebuild_submitted_list()

        root.addWidget(self._content_stack)

    # ── tabs ──────────────────────────────────────────────────────

    def _switch_tab(self, index: int):
        self._content_stack.setCurrentIndex(index)
        self._workers_tab_btn.setChecked(index == 0)
        self._submitted_tab_btn.setChecked(index == 1)

    def _on_refresh(self):
        if self._content_stack.currentIndex() == 0:
            self.refresh_clicked.emit()
        else:
            self.load_job_history()

    # ── public API ────────────────────────────────────────────────

    def set_client(self, client) -> None:
        self._client = client

    def load_job_history(self):
        """Fetch all jobs from GET /api/workers/jobs in a background thread."""
        if not self._client:
            return
        threading.Thread(target=self._fetch_history, daemon=True).start()

    def _fetch_history(self):
        try:
            jobs = self._client.list_jobs()
            # Send raw dicts to main thread (WorkerJob dataclasses aren't
            # needed — from_history works with dicts).
            self._history_loaded.emit([
                {
                    "jobId": j.jobId,
                    "workerId": j.workerId,
                    "workerName": j.workerName,
                    "workerVersionId": j.workerVersionId,
                    "versionTag": j.versionTag,
                    "createdBy": j.createdBy,
                    "createdByUserName": j.createdByUserName,
                    "tenantId": j.tenantId,
                    "tenantName": j.tenantName,
                    "status": j.status,
                    "machineType": j.machineType,
                    "inputParams": j.inputParams,
                    "logPreview": j.logPreview,
                    "hasOutputFiles": j.hasOutputFiles,
                    "jobStartedAt": j.jobStartedAt,
                    "jobEndedAt": j.jobEndedAt,
                    "createdAt": j.createdAt,
                }
                for j in jobs
            ])
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Failed to fetch job history: {exc}",
                PLUGIN_LOG_TAG, Qgis.Warning,
            )

    def _on_history_loaded(self, job_dicts: list):
        """Main thread: merge fetched history into sessions list."""
        # Keep any active (non-terminal, locally-tracked) sessions.
        active = [s for s in self._sessions if s.status not in TERMINAL_STATUSES]
        active_ids = {s.job_id for s in active if s.job_id}

        # Build sessions from history, skipping any already tracked locally.
        historical = []
        for jd in job_dicts:
            if jd["jobId"] in active_ids:
                continue
            s = JobSession.from_history(jd, client=self._client, parent=self)
            historical.append(s)

        self._sessions = active + historical
        self._rebuild_submitted_list()

    def set_workers_data(self, tenants: list[dict]) -> None:
        """Populate the Catalog tab."""
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(12)

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
                QSpacerItem(0, 4, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            )

        if not any_workers:
            empty_lbl = QLabel("No workers found for any team.")
            empty_lbl.setObjectName("npEmptyLabel")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(empty_lbl)

        lay.addStretch(1)
        self._workers_scroll.setWidget(content)

    # ── run dialog ────────────────────────────────────────────────

    def _get_current_stylesheet(self) -> str:
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
            client=self._client,
            parent=self.window(),
        )
        dlg.job_submitted.connect(self._on_job_submitted)
        dlg.exec()

    def _open_session_dialog(self, session: JobSession):
        worker = {
            "id": session.worker_id,
            "name": session.worker_name,
            "version": session.version,
            "tenantId": session.tenant_id,
        }
        dlg = WorkerRunDialog(
            worker,
            session=session,
            stylesheet=self._get_current_stylesheet(),
            client=self._client,
            parent=self.window(),
        )
        dlg.exec()

    # ── session tracking ──────────────────────────────────────────

    def clear_sessions(self):
        for session in self._sessions:
            if session.status == "RUNNING":
                session.cancel()
        self._sessions.clear()
        self._rebuild_submitted_list()

    def _on_job_submitted(self, session: JobSession):
        session.setParent(self)
        self._sessions.insert(0, session)
        self._rebuild_submitted_list()

    def _rebuild_submitted_list(self):
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)

        if not self._sessions:
            empty = QLabel("No submitted sessions yet.")
            empty.setObjectName("npEmptyLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(empty)
        else:
            for session in self._sessions:
                card = _SubmittedJobCard(session, content)
                card.clicked.connect(
                    lambda s=session: self._open_session_dialog(s)
                )
                lay.addWidget(card)

        lay.addStretch(1)
        self._submitted_scroll.setWidget(content)


# ── helpers ────────────────────────────────────────────────────────

def _group_workers(workers: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for w in workers:
        groups.setdefault(w.get("name", "unknown"), []).append(w)
    return groups


def _version_sort_key(v: str):
    parts = []
    for seg in v.lstrip("v").split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(seg)
    return parts
