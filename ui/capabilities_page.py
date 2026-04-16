from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QSizePolicy,
    QSpacerItem,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal


_CARDS = [
    {
        "icon": "\U0001f310",  # globe
        "title": "Data Migration",
        "desc": (
            "Seamlessly transition massive geospatial datasets "
            "across distributed cloud regions with zero telemetry loss."
        ),
        "key": "migration",
    },
    {
        "icon": "\u2B83",  # arrows
        "title": "Data Conversion",
        "desc": (
            "Real-time coordinate system remapping and format "
            "transcoding for disparate satellite sensor inputs."
        ),
        "key": "conversion",
    },
    {
        "icon": "\u25B6\uFE0F",  # play
        "title": "GeoEngine Workers",
        "desc": (
            "Deploy bespoke algorithms directly to the edge. "
            "Our nodes handle complex telemetry analysis with "
            "sub-millisecond precision."
        ),
        "key": "workers",
    },
]


class _CardWidget(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, icon: str, title: str, desc: str, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self.setObjectName("npCapCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(6)

        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("npCapIcon")
        lay.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("npCapTitle")
        lay.addWidget(title_lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setObjectName("npCapDesc")
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl)

    def mousePressEvent(self, event):
        self.clicked.emit(self._key)
        super().mousePressEvent(event)


class CapabilitiesPage(QWidget):
    """Three-card capabilities screen shown after login."""

    card_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 16)
        lay.setSpacing(12)

        lay.addSpacerItem(
            QSpacerItem(0, 8, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        )

        for info in _CARDS:
            card = _CardWidget(
                info["icon"], info["title"], info["desc"], info["key"], self
            )
            card.clicked.connect(self.card_clicked.emit)
            lay.addWidget(card)

        lay.addStretch(1)
