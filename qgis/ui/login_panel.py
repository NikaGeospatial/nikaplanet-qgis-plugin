from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
    QSpacerItem,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal


class LoginPanel(QDockWidget):
    """Dock widget displaying the NikaPlanet login screen."""

    sign_in_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("NikaPlanet", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
        )

        container = QWidget()
        container.setObjectName("npLoginRoot")
        container.setStyleSheet(_STYLESHEET)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(0)

        lay.addSpacerItem(
            QSpacerItem(0, 30, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        # ── logo ──────────────────────────────────────────────────────
        logo = QLabel()
        logo.setObjectName("npLogo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setTextFormat(Qt.RichText)
        logo.setText(
            '<span style="font-size:22pt; font-weight:600; color:#4ecdc4;">'
            "\U0001f6f0\ufe0f  NikaPlanet</span>"
        )
        lay.addWidget(logo)

        lay.addSpacing(16)

        # ── teal divider ──────────────────────────────────────────────
        divider = QFrame()
        divider.setFixedSize(40, 2)
        divider.setStyleSheet("background-color: #4ecdc4;")
        lay.addWidget(divider, alignment=Qt.AlignCenter)

        lay.addSpacing(20)

        # ── heading ───────────────────────────────────────────────────
        heading = QLabel("Sign in to access your\ngeospatial workspace.")
        heading.setObjectName("npHeading")
        heading.setAlignment(Qt.AlignCenter)
        heading.setWordWrap(True)
        lay.addWidget(heading)

        lay.addSpacing(12)

        # ── subtitle ─────────────────────────────────────────────────
        subtitle = QLabel(
            "Precision telemetry and cartography\n"
            "tools for the modern explorer."
        )
        subtitle.setObjectName("npSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        lay.addWidget(subtitle)

        lay.addSpacing(32)

        # ── sign-in button ────────────────────────────────────────────
        btn = QPushButton("\u2192)   SIGN IN WITH NIKAPLANET")
        btn.setObjectName("npSignIn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(48)
        btn.setMinimumWidth(240)
        btn.clicked.connect(self.sign_in_clicked.emit)
        lay.addWidget(btn, alignment=Qt.AlignCenter)

        lay.addSpacerItem(
            QSpacerItem(0, 30, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        # ── footer ────────────────────────────────────────────────────
        lay.addWidget(self._build_footer())

        self.setWidget(container)
        self.setMinimumWidth(320)

    # ── private builders ──────────────────────────────────────────────

    @staticmethod
    def _build_footer():
        footer = QWidget()
        v = QVBoxLayout(footer)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        links = QLabel("LEGAL     PRIVACY")
        links.setObjectName("npFooterLinks")
        links.setAlignment(Qt.AlignCenter)
        v.addWidget(links)

        version = QLabel("VERSION 4.2.0-ALPHA")
        version.setObjectName("npFooterVersion")
        version.setAlignment(Qt.AlignCenter)
        v.addWidget(version)

        return footer


# ── stylesheet (scoped to #npLoginRoot) ──────────────────────────────

_STYLESHEET = """
#npLoginRoot {
    background-color: #0c1220;
}

/* heading + subtitle */
#npHeading {
    color: #e8ecf2;
    font-size: 16pt;
    font-weight: bold;
}
#npSubtitle {
    color: #6a7a90;
    font-size: 10pt;
}

/* sign-in button */
#npSignIn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #3dbcb2, stop:1 #6de0d4);
    color: #0c1220;
    border: none;
    border-radius: 8px;
    font-size: 10pt;
    font-weight: bold;
    padding: 0 24px;
}
#npSignIn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4ecdc4, stop:1 #7eeee6);
}
#npSignIn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #35aca3, stop:1 #5fcfc6);
}

/* footer */
#npFooterLinks, #npFooterVersion {
    color: #4a5568;
    font-size: 9pt;
}
"""
