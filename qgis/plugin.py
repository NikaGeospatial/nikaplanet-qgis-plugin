from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsMessageLog, Qgis, QgsApplication
from .cloud.auth import AuthManager
from .processing.provider import GeoEngineCloudProvider


class GeoEngineCloudPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.login_action = None
        self.auth = AuthManager()

    def initGui(self):
        self.login_action = QAction("GeoEngine Cloud: Login", self.iface.mainWindow())
        self.login_action.triggered.connect(self.login)
        self.iface.addToolBarIcon(self.login_action)
        self.iface.addPluginToMenu("GeoEngine Cloud", self.login_action)

        self.auth.login_succeeded.connect(self._on_login_success)
        self.auth.login_failed.connect(self._on_login_failed)

        self.initProcessing()

    def initProcessing(self):
        self.provider = GeoEngineCloudProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        self.iface.removeToolBarIcon(self.login_action)
        self.iface.removePluginMenu("GeoEngine Cloud", self.login_action)

    def login(self):
        QgsMessageLog.logMessage(
            "Starting GeoEngine login…", "GeoEngine", Qgis.Info
        )
        self.auth.login()

    def _on_login_success(self, user):
        username = user.get("username", "Unknown")
        email = user.get("email", "")
        QgsMessageLog.logMessage(
            f"Logged in as {username}", "GeoEngine", Qgis.Info
        )
        QMessageBox.information(
            self.iface.mainWindow(),
            "GeoEngine Cloud",
            f"Logged in as {username} ({email})",
        )

    def _on_login_failed(self, error):
        QgsMessageLog.logMessage(
            f"Login failed: {error}", "GeoEngine", Qgis.Warning
        )
        QMessageBox.warning(
            self.iface.mainWindow(),
            "GeoEngine Cloud",
            f"Login failed:\n{error}",
        )
