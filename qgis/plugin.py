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
        self._user_info: dict | None = None

    def initGui(self):
        self.toolbar_action = QAction("GeoEngine Cloud", self.iface.mainWindow())
        self.toolbar_action.triggered.connect(self._toggle_panel)
        self.iface.addToolBarIcon(self.toolbar_action)
        self.iface.addPluginToMenu("GeoEngine Cloud", self.toolbar_action)

        self.login_panel = LoginPanel(self.iface.mainWindow())
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.login_panel)
        self.login_panel.hide()
        self.login_panel.sign_in_clicked.connect(self._on_sign_in)
        self.login_panel.refresh_workers_clicked.connect(self._on_refresh_workers)
        self.login_panel.logout_clicked.connect(self._on_logout)

        self.auth.login_succeeded.connect(
            self._on_login_success, Qt.ConnectionType.QueuedConnection
        )
        self.auth.login_failed.connect(
            self._on_login_failed, Qt.ConnectionType.QueuedConnection
        )

        self.initProcessing()
        debug_log_keyring_backends()

        # Auto-restore session if tokens are already in keyring
        QTimer.singleShot(0, self._try_auto_login)

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

    # ── auto-login ─────────────────────────────────────────────────

    def _try_auto_login(self):
        """Check keyring for existing tokens and skip to capabilities if valid."""
        user = self.auth.try_restore_session()
        if user:
            self._on_login_success(user)

    # ── auth callbacks ─────────────────────────────────────────────

    def _on_sign_in(self):
        self.login_panel.set_sign_in_loading(True)
        QTimer.singleShot(0, self._sign_in_check)

    def _sign_in_check(self):
        # If the GeoEngine CLI (or a previous session) left tokens in the
        # keyring, skip the browser flow and go straight to capabilities.
        user = self.auth.try_restore_session()
        if user:
            self._on_login_success(user)
            return
        self.login_panel.set_sign_in_loading(False)
        QgsMessageLog.logMessage(
            "Starting GeoEngine login\u2026", PLUGIN_LOG_TAG, Qgis.Info
        )
        self.auth.login()

    def _on_login_success(self, user):
        user = user or {}
        self._user_info = user
        username = user.get("username", "Unknown")

        QgsMessageLog.logMessage(
            f"Logged in as {username}", PLUGIN_LOG_TAG, Qgis.Info
        )

        self.provider._tenant_id = (user.get("ownedTenant") or {}).get("id")
        self.provider._authenticated = True

        self.login_panel.show_capabilities(username)

        # Refresh algorithms (fetches workers for owned tenant) then
        # populate the workers page with the results + invited tenants.
        QTimer.singleShot(0, self._refresh_and_load_workers)

    def _on_login_failed(self, error):
        QgsMessageLog.logMessage(
            f"Login failed: {error}", PLUGIN_LOG_TAG, Qgis.Warning
        )
        QMessageBox.warning(
            self.iface.mainWindow(),
            "GeoEngine Cloud",
            f"Login failed:\n{error}",
        )

    # ── workers ────────────────────────────────────────────────────

    def _refresh_and_load_workers(self):
        """Refresh processing algorithms, then populate the workers page."""
        self.provider.refreshAlgorithms()
        self._populate_workers_page()

    def _populate_workers_page(self):
        """Build tenants-data from the provider's fetch results + invited tenants."""
        user = self._user_info or {}
        tenants_data: list[dict] = []

        # Owned tenant: reuse the tasks the provider just fetched
        owned = user.get("ownedTenant") or {}
        if owned.get("id"):
            tenants_data.append({
                "name": owned.get("name", "My Team"),
                "workers": list(self.provider.last_fetched_tasks),
            })

        # Invited tenants: fetch using the same (working) mechanism
        for inv in user.get("invitedTenants") or []:
            tid = inv.get("id")
            if not tid:
                continue
            workers = self.provider.fetch_remote_tasks(tenant_id=tid)
            tenants_data.append({
                "name": inv.get("name", "Team"),
                "workers": workers,
            })

        self.login_panel.workers_page.set_workers_data(tenants_data)
        total = sum(len(t["workers"]) for t in tenants_data)
        QgsMessageLog.logMessage(
            f"Workers page loaded: {total} worker(s) across {len(tenants_data)} tenant(s)",
            PLUGIN_LOG_TAG,
            Qgis.Info,
        )

    def _on_refresh_workers(self):
        QgsMessageLog.logMessage(
            "Refreshing workers\u2026", PLUGIN_LOG_TAG, Qgis.Info
        )
        self._refresh_and_load_workers()

    def _on_logout(self):
        self.auth.logout()
        self._user_info = None
        self.provider._authenticated = False
        self.provider._tenant_id = None
        self.provider.last_fetched_tasks = []
        self.login_panel.workers_page.clear_sessions()
        self.login_panel.show_login()
        QgsMessageLog.logMessage("Logged out", PLUGIN_LOG_TAG, Qgis.Info)
