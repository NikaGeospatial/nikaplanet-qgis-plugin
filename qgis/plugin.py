from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.core import QgsMessageLog, Qgis, QgsApplication
from .cloud.auth import AuthManager, debug_log_keyring_backends
from .util.messages import PLUGIN_LOG_TAG
from .processing.provider import GeoEngineCloudProvider
from .ui.login_panel import LoginPanel


class GeoEngineCloudPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.toolbar_action = None
        self.login_panel = None
        self.auth = AuthManager()

    def initGui(self):
        self.toolbar_action = QAction("GeoEngine Cloud", self.iface.mainWindow())
        self.toolbar_action.triggered.connect(self._toggle_panel)
        self.iface.addToolBarIcon(self.toolbar_action)
        self.iface.addPluginToMenu("GeoEngine Cloud", self.toolbar_action)

        self.login_panel = LoginPanel(self.iface.mainWindow())
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.login_panel)
        self.login_panel.hide()
        self.login_panel.sign_in_clicked.connect(self._on_sign_in)

        self.auth.login_succeeded.connect(
            self._on_login_success, Qt.ConnectionType.QueuedConnection
        )
        self.auth.login_failed.connect(
            self._on_login_failed, Qt.ConnectionType.QueuedConnection
        )

        self.initProcessing()
        debug_log_keyring_backends()

    def initProcessing(self):
        self.provider = GeoEngineCloudProvider(self.auth)
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        self.iface.removeToolBarIcon(self.toolbar_action)
        self.iface.removePluginMenu("GeoEngine Cloud", self.toolbar_action)
        if self.login_panel:
            self.iface.removeDockWidget(self.login_panel)
            self.login_panel.deleteLater()
            self.login_panel = None

    def _toggle_panel(self):
        if self.login_panel.isVisible():
            self.login_panel.hide()
        else:
            self.login_panel.show()

    def _on_sign_in(self):
        QgsMessageLog.logMessage(
            "Starting GeoEngine login…", PLUGIN_LOG_TAG, Qgis.Info
        )
        self.auth.login()

    def _on_login_success(self, user):
        user = user or {}
        username = user.get("username", "Unknown")
        email = user.get("email", "")
        QgsMessageLog.logMessage(
            f"Logged in as {username}", PLUGIN_LOG_TAG, Qgis.Info
        )
        QMessageBox.information(
            self.iface.mainWindow(),
            "GeoEngine Cloud",
            f"Logged in as {username} ({email})",
        )
        self.provider._authenticated = True
        QgsMessageLog.logMessage(
            "Scheduling provider refresh on main thread", PLUGIN_LOG_TAG, Qgis.Info
        )
        QTimer.singleShot(0, self.provider.refreshAlgorithms)

    def _on_login_failed(self, error):
        QgsMessageLog.logMessage(
            f"Login failed: {error}", PLUGIN_LOG_TAG, Qgis.Warning
        )
        QMessageBox.warning(
            self.iface.mainWindow(),
            "GeoEngine Cloud",
            f"Login failed:\n{error}",
        )
