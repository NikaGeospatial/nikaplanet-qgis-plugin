from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QFrame,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal

from .styles import DARK_STYLESHEET, LIGHT_STYLESHEET
from .capabilities_page import CapabilitiesPage
from .workers_page import WorkersPage

PAGE_LOGIN = 0
PAGE_CAPABILITIES = 1
PAGE_WORKERS = 2


class LoginPanel(QDockWidget):
    """Dock widget housing login, capabilities, and workers pages."""

    sign_in_clicked = pyqtSignal()
    refresh_workers_clicked = pyqtSignal()
    logout_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("NikaPlanet", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )

        self._dark_mode = True
        self._username: str | None = None

        # ── outer container ────────────────────────────────────────
        self._container = QWidget()
        self._container.setObjectName("npRoot")

        root_lay = QVBoxLayout(self._container)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # ── persistent header ──────────────────────────────────────
        self._header = self._build_header()
        root_lay.addWidget(self._header)

        # ── stacked pages ──────────────────────────────────────────
        self._stack = QStackedWidget()

        self._login_page = self._build_login_page()
        self._stack.addWidget(self._login_page)       # index 0

        self._cap_page = CapabilitiesPage()
        self._cap_page.card_clicked.connect(self._on_card_clicked)
        self._stack.addWidget(self._cap_page)          # index 1

        self._workers_page = WorkersPage()
        self._workers_page.refresh_clicked.connect(self.refresh_workers_clicked.emit)
        self._workers_page.back_clicked.connect(
            lambda: self._stack.setCurrentIndex(PAGE_CAPABILITIES)
        )
        self._stack.addWidget(self._workers_page)      # index 2

        root_lay.addWidget(self._stack, 1)

        self.setWidget(self._container)
        self.setMinimumWidth(320)
        self._apply_theme()

    # ── public API ─────────────────────────────────────────────────

    def show_login(self):
        self._username = None
        self._user_chip.hide()
        self.set_sign_in_loading(False)
        self._stack.setCurrentIndex(PAGE_LOGIN)

    def set_sign_in_loading(self, loading: bool):
        self._sign_in_btn.setEnabled(not loading)
        self._sign_in_btn.setText(
            "CHECKING\u2026" if loading else "\u2192   SIGN IN WITH NIKAPLANET"
        )

    def show_capabilities(self, username: str | None = None):
        if username:
            self._username = username
            self._user_chip.setText(username[0].upper())
            self._user_chip.show()
        self._stack.setCurrentIndex(PAGE_CAPABILITIES)

    def show_workers(self, tenants_data: list[dict]):
        self._workers_page.set_workers_data(tenants_data)
        self._stack.setCurrentIndex(PAGE_WORKERS)

    @property
    def workers_page(self) -> WorkersPage:
        return self._workers_page

    # ── header ─────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("npHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 10, 16, 6)
        h.setSpacing(8)

        title = QLabel("NIKAPLANET")
        title.setObjectName("npHeaderTitle")
        h.addWidget(title)

        h.addStretch(1)

        self._theme_btn = QPushButton()
        self._theme_btn.setObjectName("npThemeToggle")
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        h.addWidget(self._theme_btn)

        self._user_chip = QPushButton()
        self._user_chip.setObjectName("npUserChip")
        self._user_chip.setFixedSize(28, 28)
        self._user_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._user_chip.hide()

        self._user_menu = QMenu(self._user_chip)
        self._user_menu.setObjectName("npUserMenu")
        self._user_menu.addAction("Logout", self.logout_clicked.emit)
        self._user_chip.setMenu(self._user_menu)

        h.addWidget(self._user_chip)

        return header

    # ── login page ─────────────────────────────────────────────────

    def _build_login_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(0)

        lay.addSpacerItem(
            QSpacerItem(0, 30, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        # logo
        logo = QLabel("\U0001f6f0\ufe0f  NikaPlanet")
        logo.setObjectName("npLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)
        lay.addSpacing(16)

        # accent divider
        divider = QFrame()
        divider.setObjectName("npLogoDivider")
        divider.setFixedSize(40, 2)
        lay.addWidget(divider, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(20)

        # heading
        heading = QLabel("Sign in to access your\ngeospatial workspace.")
        heading.setObjectName("npHeading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setWordWrap(True)
        lay.addWidget(heading)
        lay.addSpacing(12)

        # subtitle
        subtitle = QLabel(
            "Precision telemetry and cartography\n"
            "tools for the modern explorer."
        )
        subtitle.setObjectName("npSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        lay.addWidget(subtitle)
        lay.addSpacing(32)

        # sign-in button
        self._sign_in_btn = QPushButton("\u2192   SIGN IN WITH NIKAPLANET")
        self._sign_in_btn.setObjectName("npSignIn")
        self._sign_in_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sign_in_btn.setFixedHeight(48)
        self._sign_in_btn.setMinimumWidth(240)
        self._sign_in_btn.clicked.connect(self.sign_in_clicked.emit)
        lay.addWidget(self._sign_in_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        lay.addSpacerItem(
            QSpacerItem(0, 30, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        # footer
        lay.addWidget(self._build_footer())

        return page

    @staticmethod
    def _build_footer() -> QWidget:
        footer = QWidget()
        v = QVBoxLayout(footer)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        links = QLabel("LEGAL     PRIVACY")
        links.setObjectName("npFooterLinks")
        links.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(links)

        version = QLabel("VERSION 4.2.0-ALPHA")
        version.setObjectName("npFooterVersion")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(version)

        return footer

    # ── theme toggle ───────────────────────────────────────────────

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self._apply_theme()

    def _apply_theme(self):
        sheet = DARK_STYLESHEET if self._dark_mode else LIGHT_STYLESHEET
        self._container.setStyleSheet(sheet)
        self._theme_btn.setText("\u2600" if self._dark_mode else "\u263D")

    # ── navigation ─────────────────────────────────────────────────

    def _on_card_clicked(self, key: str):
        if key == "workers":
            self._stack.setCurrentIndex(PAGE_WORKERS)
