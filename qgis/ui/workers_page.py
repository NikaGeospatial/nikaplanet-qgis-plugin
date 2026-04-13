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
)
from qgis.PyQt.QtCore import Qt, pyqtSignal


class _WorkerCard(QWidget):
    """Collapsible card for a single worker (potentially multiple versions)."""

    def __init__(
        self,
        name: str,
        description: str,
        versions: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("npWorkerCard")
        self._expanded = len(versions) > 1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(0)

        # header row: name + description | chevron
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

        for i, ver in enumerate(versions):
            if i > 0:
                sep = QFrame()
                sep.setObjectName("npVersionSep")
                sep.setFixedHeight(1)
                v_lay.addWidget(sep)
            lbl = QLabel(ver)
            lbl.setObjectName("npVersionLabel")
            v_lay.addWidget(lbl)

        outer.addWidget(self._versions_widget)
        self._update_chevron()
        self._versions_widget.setVisible(self._expanded)

    def _toggle(self):
        self._expanded = not self._expanded
        self._versions_widget.setVisible(self._expanded)
        self._update_chevron()

    def _update_chevron(self):
        self._chevron.setText("\u2303" if self._expanded else "\u2304")


class WorkersPage(QWidget):
    """Team Worker Version Management Dashboard."""

    refresh_clicked = pyqtSignal()
    logout_clicked = pyqtSignal()
    back_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

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

        # scrollable content area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self._scroll)

        # placeholder
        self._empty = QLabel("No workers loaded yet.")
        self._empty.setObjectName("npEmptyLabel")
        self._empty.setAlignment(Qt.AlignCenter)
        self._scroll.setWidget(self._empty)

    # ── public API ─────────────────────────────────────────────────

    def set_workers_data(self, tenants: list[dict]) -> None:
        """Populate the dashboard.

        *tenants* is a list of dicts, each with keys:
            name  – team / tenant display name
            workers – list of worker dicts from the API
        """
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
                versions = sorted(
                    [e.get("version", "?") for e in entries],
                    key=_version_sort_key,
                )
                card = _WorkerCard(worker_name, desc, versions, content)
                lay.addWidget(card)

            lay.addSpacerItem(
                QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed)
            )

        if not any_workers:
            empty = QLabel("No workers found for any team.")
            empty.setObjectName("npEmptyLabel")
            empty.setAlignment(Qt.AlignCenter)
            lay.addWidget(empty)

        lay.addStretch(1)
        self._scroll.setWidget(content)


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
