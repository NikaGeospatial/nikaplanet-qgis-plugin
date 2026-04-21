from __future__ import annotations

import threading

from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
)
from qgis.PyQt.QtCore import (
    Qt,
    QRectF,
    QVariantAnimation,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QPainter

from qgis.core import QgsMessageLog, Qgis

from .job_session import JobSession, TERMINAL_STATUSES
from .worker_run_dialog import WorkerRunDialog
from ..util.messages import PLUGIN_LOG_TAG


# Cached lowercase search text per job_id: "worker_name vversion job_id".
# Rebuilding this on every keystroke for hundreds of jobs would be wasteful,
# and since the tuple (name, version, job_id) is immutable once the job
# exists on the server, caching by job_id is safe.
_JOB_TEXT_CACHE: dict[str, str] = {}


def _relative_time(dt) -> str:
    from datetime import datetime
    total = int((datetime.now() - dt).total_seconds())
    if total < 60:
        return "just now"
    if total < 3600:
        m = total // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if total < 86400:
        h = total // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = total // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _session_search_text(session: JobSession) -> str:
    jid = session.job_id or ""
    if jid and jid in _JOB_TEXT_CACHE:
        return _JOB_TEXT_CACHE[jid]
    parts = [
        session.worker_name or "",
        f"v{session.version}" if session.version else "",
        jid or session.session_id or "",
    ]
    text = " ".join(p for p in parts if p).lower()
    if jid:
        _JOB_TEXT_CACHE[jid] = text
    return text


class _SpinningRefreshButton(QPushButton):
    """Refresh button whose glyph rotates while a refresh is in flight."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._angle = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setDuration(900)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._set_angle)

    def _set_angle(self, value):
        self._angle = float(value)
        self.update()

    def start_spin(self):
        if self._anim.state() != QVariantAnimation.State.Running:
            self._anim.start()

    def stop_spin(self):
        self._anim.stop()
        self._angle = 0.0
        self.update()

    def paintEvent(self, a0):
        super().paintEvent(a0)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setPen(self.palette().buttonText().color())
        p.setFont(self.font())
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.rotate(self._angle)
        rect = QRectF(
            -self.width() / 2.0, -self.height() / 2.0,
            float(self.width()), float(self.height()),
        )
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "\u21BB")


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

        self._chevron = QPushButton()
        self._chevron.setObjectName("npChevron")
        self._chevron.setFixedSize(28, 28)
        self._chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron.clicked.connect(self._toggle)
        header.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("npWorkerName")
        info.addWidget(name_lbl)
        desc_lbl = QLabel(description)
        desc_lbl.setObjectName("npWorkerDesc")
        info.addWidget(desc_lbl)
        header.addLayout(info, 1)

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

        sid_row = QHBoxLayout()
        sid_row.setContentsMargins(0, 0, 0, 0)
        sid_row.setSpacing(6)
        self._sid_lbl = QLabel(session.session_id)
        self._sid_lbl.setObjectName("npWorkerDesc")
        sid_row.addWidget(self._sid_lbl)
        ts_lbl = QLabel(f"\u00B7 {_relative_time(session.created_at)}")
        ts_lbl.setObjectName("npWorkerDesc")
        sid_row.addWidget(ts_lbl)
        sid_row.addStretch()
        info.addLayout(sid_row)

        lay.addLayout(info, 1)

        self._status_lbl = QLabel(session.status)
        self._status_lbl.setObjectName("npStatusBadge")
        lay.addWidget(self._status_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        session.status_changed.connect(self._on_status_changed)
        session.session_id_changed.connect(self._on_session_id_changed)

    def _on_status_changed(self, status: str):
        self._status_lbl.setText(status)

    def _on_session_id_changed(self, session_id: str):
        self._sid_lbl.setText(session_id)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class WorkersPage(QWidget):
    """Worker catalog and sessions dashboard."""

    refresh_clicked = pyqtSignal()
    back_clicked = pyqtSignal()

    # Emitted by the plugin's background catalog fetch with
    # (owned_workers, tenants_data).
    catalog_loaded = pyqtSignal(list, list)
    # Emitted by the plugin's background catalog fetch on failure.
    catalog_fetch_failed = pyqtSignal()

    # Internal: background thread finished fetching history.
    _history_loaded = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: list[JobSession] = []
        self._client = None

        self._history_loaded.connect(self._on_history_loaded)
        self.catalog_fetch_failed.connect(self._stop_refresh_spin)

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

        self._submitted_tab_btn = QPushButton("JOB HISTORY")
        self._submitted_tab_btn.setObjectName("npTabBtn")
        self._submitted_tab_btn.setCheckable(True)
        self._submitted_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submitted_tab_btn.clicked.connect(lambda: self._switch_tab(1))
        tab_row.addWidget(self._submitted_tab_btn)

        tab_row.addStretch()

        # Refresh button — refreshes workers catalog or sessions depending
        # on which tab is active.
        self._refresh_btn = _SpinningRefreshButton()
        self._refresh_btn.setObjectName("npRefreshBtn")
        self._refresh_btn.setToolTip("Refresh")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setFixedSize(30, 30)
        self._refresh_btn.clicked.connect(self._on_refresh)
        tab_row.addWidget(self._refresh_btn)

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

        # index 1: submitted tab (filter bar + scroll)
        submitted_tab = QWidget()
        st_lay = QVBoxLayout(submitted_tab)
        st_lay.setContentsMargins(0, 0, 0, 0)
        st_lay.setSpacing(6)
        self._build_session_filters(st_lay)

        self._submitted_scroll = QScrollArea()
        self._submitted_scroll.setWidgetResizable(True)
        self._submitted_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        st_lay.addWidget(self._submitted_scroll, 1)

        self._content_stack.addWidget(submitted_tab)
        self._rebuild_submitted_list()

        root.addWidget(self._content_stack)

    # ── tabs ──────────────────────────────────────────────────────

    # ── session filters ──────────────────────────────────────────

    _STATUS_CHOICES = [
        "PREPARING", "SUBMITTED", "RUNNING", "SUCCESS",
        "CANCELLED", "EXPIRED", "JOB_FAILED",
        "UPLOAD_FAILED", "SUBMIT_FAILED",
    ]
    _DATE_CHOICES = [
        ("All time", 0),
        ("Last 24 hours", 1),
        ("Last 7 days", 7),
        ("Last 30 days", 30),
    ]
    _SORT_CHOICES = [
        ("Newest first", "newest"),
        ("Oldest first", "oldest"),
        ("Status", "status"),
    ]

    def _build_session_filters(self, parent_lay: QVBoxLayout):
        # Top row: search + filters toggle
        top = QHBoxLayout()
        top.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("npRunInput")
        self._search_input.setPlaceholderText(
            "Search by worker, version, or job id\u2026"
        )
        self._search_input.setClearButtonEnabled(True)
        top.addWidget(self._search_input, 1)

        self._filters_toggle = QPushButton("\u25B8 Filters")
        self._filters_toggle.setObjectName("npFiltersToggle")
        self._filters_toggle.setCheckable(True)
        self._filters_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        top.addWidget(self._filters_toggle)

        parent_lay.addLayout(top)

        # Collapsible filter container
        self._filters_container = QWidget()
        fc_lay = QVBoxLayout(self._filters_container)
        fc_lay.setContentsMargins(0, 0, 0, 0)
        fc_lay.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self._status_filter = QComboBox()
        self._status_filter.setObjectName("npRunCombo")
        self._status_filter.addItem("All statuses", "")
        for s in self._STATUS_CHOICES:
            self._status_filter.addItem(s, s)
        row1.addWidget(self._status_filter, 1)

        self._date_filter = QComboBox()
        self._date_filter.setObjectName("npRunCombo")
        for label, days in self._DATE_CHOICES:
            self._date_filter.addItem(label, days)
        row1.addWidget(self._date_filter, 1)

        self._sort_filter = QComboBox()
        self._sort_filter.setObjectName("npRunCombo")
        for label, mode in self._SORT_CHOICES:
            self._sort_filter.addItem(label, mode)
        row1.addWidget(self._sort_filter, 1)

        fc_lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self._tenant_filter = QComboBox()
        self._tenant_filter.setObjectName("npRunCombo")
        self._tenant_filter.addItem("All teams", "")
        row2.addWidget(self._tenant_filter, 1)

        self._all_teams_cb = QCheckBox("Include teammates' jobs")
        self._all_teams_cb.setToolTip(
            "When checked, include jobs created by other members of "
            "accessible tenants (allTeams=true)."
        )
        row2.addWidget(self._all_teams_cb)

        row2.addStretch()
        fc_lay.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(6)

        self._worker_filter = QComboBox()
        self._worker_filter.setObjectName("npRunCombo")
        self._worker_filter.addItem("All workers", "")
        row3.addWidget(self._worker_filter, 1)

        self._version_filter = QComboBox()
        self._version_filter.setObjectName("npRunCombo")
        self._version_filter.addItem("All versions", "")
        self._version_filter.setEnabled(False)
        row3.addWidget(self._version_filter, 1)

        fc_lay.addLayout(row3)

        row4 = QHBoxLayout()
        row4.setSpacing(6)
        row4.addStretch()
        self._reset_filters_btn = QPushButton("Reset filters")
        self._reset_filters_btn.setObjectName("npResetFiltersBtn")
        self._reset_filters_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row4.addWidget(self._reset_filters_btn)
        fc_lay.addLayout(row4)

        self._filters_container.setVisible(False)
        parent_lay.addWidget(self._filters_container)

        # allTeams is a scope change — it widens the set of jobs the server
        # returns, so it needs a re-fetch. Everything else is a local
        # predicate on the jobs we already have.
        self._all_teams_cb.toggled.connect(self._on_scope_changed)
        self._status_filter.currentIndexChanged.connect(
            self._rebuild_submitted_list
        )
        self._date_filter.currentIndexChanged.connect(
            self._rebuild_submitted_list
        )
        self._tenant_filter.currentIndexChanged.connect(
            self._on_tenant_filter_changed
        )
        self._sort_filter.currentIndexChanged.connect(
            self._rebuild_submitted_list
        )
        self._worker_filter.currentIndexChanged.connect(
            self._on_worker_filter_changed
        )
        self._version_filter.currentIndexChanged.connect(
            self._rebuild_submitted_list
        )
        self._search_input.textChanged.connect(self._rebuild_submitted_list)
        self._filters_toggle.toggled.connect(self._on_filters_toggled)
        self._reset_filters_btn.clicked.connect(self._on_reset_filters)

    def _on_filters_toggled(self, checked: bool):
        self._filters_container.setVisible(checked)
        self._filters_toggle.setText(
            "\u25BE Filters" if checked else "\u25B8 Filters"
        )

    def _on_scope_changed(self, *_):
        self.load_job_history()

    def _on_worker_filter_changed(self, *_):
        self._refresh_version_filter()
        self._rebuild_submitted_list()

    def _on_tenant_filter_changed(self, *_):
        # Tenant scope narrows the workers list — rebuild it first.
        self._refresh_worker_filter()
        self._rebuild_submitted_list()

    def _on_reset_filters(self):
        # Block signals so intermediate rebuilds don't fire repeatedly.
        widgets = [
            self._status_filter, self._date_filter, self._sort_filter,
            self._tenant_filter, self._worker_filter, self._version_filter,
            self._all_teams_cb,
        ]
        for w in widgets:
            w.blockSignals(True)
        self._status_filter.setCurrentIndex(0)
        self._date_filter.setCurrentIndex(0)
        self._sort_filter.setCurrentIndex(0)
        self._tenant_filter.setCurrentIndex(0)
        self._worker_filter.setCurrentIndex(0)
        self._version_filter.setCurrentIndex(0)
        was_all_teams = self._all_teams_cb.isChecked()
        self._all_teams_cb.setChecked(False)
        for w in widgets:
            w.blockSignals(False)

        self._refresh_worker_filter()
        # allTeams is a server-side scope — if it was on, re-fetch.
        if was_all_teams:
            self.load_job_history()
        else:
            self._rebuild_submitted_list()

    def _refresh_worker_filter(self):
        """Populate the Worker dropdown from sessions in the active tenant
        scope, disambiguating duplicate names with a (team) suffix."""
        current = self._worker_filter.currentData()
        tenant_id = self._tenant_filter.currentData()
        self._worker_filter.blockSignals(True)
        self._worker_filter.clear()
        self._worker_filter.addItem("All workers", "")

        # worker_id -> (display_name, tenant_name)
        workers: dict[str, tuple[str, str]] = {}
        for s in self._sessions:
            if not s.worker_id:
                continue
            if tenant_id and s.tenant_id != tenant_id:
                continue
            if s.worker_id not in workers:
                workers[s.worker_id] = (
                    s.worker_name or s.worker_id,
                    s.tenant_name or "",
                )

        # Count occurrences of each display name to detect collisions.
        name_counts: dict[str, int] = {}
        for _wid, (name, _tn) in workers.items():
            name_counts[name] = name_counts.get(name, 0) + 1

        for wid, (name, tenant_name) in sorted(
            workers.items(), key=lambda x: x[1][0].lower()
        ):
            label = name
            if name_counts.get(name, 0) > 1 and tenant_name:
                label = f"{name} ({tenant_name})"
            self._worker_filter.addItem(label, wid)

        if current:
            idx = self._worker_filter.findData(current)
            if idx >= 0:
                self._worker_filter.setCurrentIndex(idx)
        self._worker_filter.blockSignals(False)
        self._refresh_version_filter()

    def _refresh_version_filter(self):
        """Populate the Version dropdown for the currently-selected worker."""
        worker_id = self._worker_filter.currentData()
        current = self._version_filter.currentData()
        self._version_filter.blockSignals(True)
        self._version_filter.clear()
        self._version_filter.addItem("All versions", "")
        if not worker_id:
            self._version_filter.setEnabled(False)
        else:
            self._version_filter.setEnabled(True)
            versions = sorted({
                s.version for s in self._sessions
                if s.worker_id == worker_id and s.version
            })
            for v in versions:
                self._version_filter.addItem(f"v{v}", v)
            if current:
                idx = self._version_filter.findData(current)
                if idx >= 0:
                    self._version_filter.setCurrentIndex(idx)
        self._version_filter.blockSignals(False)

    def set_tenants(self, tenants_data: list[dict]):
        """Populate the tenant filter dropdown from the catalog fetch."""
        current = self._tenant_filter.currentData()
        self._tenant_filter.blockSignals(True)
        self._tenant_filter.clear()
        self._tenant_filter.addItem("All teams", "")
        for tenant in tenants_data:
            tid = tenant.get("id") or tenant.get("tenantId")
            if not tid:
                continue
            self._tenant_filter.addItem(tenant.get("name", "Team"), tid)
        # Restore prior selection if still present.
        if current:
            idx = self._tenant_filter.findData(current)
            if idx >= 0:
                self._tenant_filter.setCurrentIndex(idx)
        self._tenant_filter.blockSignals(False)

    def _switch_tab(self, index: int):
        self._content_stack.setCurrentIndex(index)
        self._workers_tab_btn.setChecked(index == 0)
        self._submitted_tab_btn.setChecked(index == 1)

    def _on_refresh(self):
        self._refresh_btn.start_spin()
        if self._content_stack.currentIndex() == 0:
            self.refresh_clicked.emit()
        else:
            self.load_job_history()

    def _stop_refresh_spin(self):
        self._refresh_btn.stop_spin()

    # ── public API ────────────────────────────────────────────────

    def set_client(self, client) -> None:
        self._client = client

    def load_job_history(self):
        """Fetch all jobs from GET /api/workers/jobs in a background thread."""
        if not self._client:
            return
        self._refresh_btn.start_spin()
        params = self._collect_filter_params()
        threading.Thread(
            target=self._fetch_history, args=(params,), daemon=True,
        ).start()

    def _collect_filter_params(self) -> dict:
        # Only allTeams is server-side — the rest filter locally.
        return {"all_teams": self._all_teams_cb.isChecked()}

    def _fetch_history(self, params: dict):
        try:
            jobs = self._client.list_jobs(**params)
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
                    "jobSubmittedAt": j.jobSubmittedAt,
                    "jobCancelledAt": j.jobCancelledAt,
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
        self._refresh_worker_filter()
        self._rebuild_submitted_list()
        self._stop_refresh_spin()

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
        self._stop_refresh_spin()

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

    def _rebuild_submitted_list(self, *_):
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)

        sessions = self._sorted_sessions()

        if not sessions:
            empty = QLabel("No submitted sessions yet.")
            empty.setObjectName("npEmptyLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(empty)
        else:
            for session in sessions:
                card = _SubmittedJobCard(session, content)
                card.clicked.connect(
                    lambda s=session: self._open_session_dialog(s)
                )
                lay.addWidget(card)

        lay.addStretch(1)
        self._submitted_scroll.setWidget(content)

    def _sorted_sessions(self) -> list[JobSession]:
        from datetime import datetime, timedelta
        sessions = list(self._sessions)

        if hasattr(self, "_search_input"):
            query = self._search_input.text().strip().lower()
            if query:
                sessions = [
                    s for s in sessions
                    if query in _session_search_text(s)
                ]

        if hasattr(self, "_status_filter"):
            status = self._status_filter.currentData()
            if status:
                sessions = [s for s in sessions if s.status == status]

            tenant_id = self._tenant_filter.currentData()
            if tenant_id:
                sessions = [s for s in sessions if s.tenant_id == tenant_id]

            worker_id = self._worker_filter.currentData()
            if worker_id:
                sessions = [s for s in sessions if s.worker_id == worker_id]
                version = self._version_filter.currentData()
                if version:
                    sessions = [s for s in sessions if s.version == version]

            days = self._date_filter.currentData()
            if isinstance(days, int) and days > 0:
                cutoff = datetime.now() - timedelta(days=days)
                sessions = [s for s in sessions if s.created_at >= cutoff]

        mode = self._sort_filter.currentData() if hasattr(
            self, "_sort_filter"
        ) else "newest"
        if mode == "oldest":
            sessions.sort(key=lambda s: s.created_at)
        elif mode == "status":
            sessions.sort(
                key=lambda s: (s.status, -s.created_at.timestamp())
            )
        else:
            sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions


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
