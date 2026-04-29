from __future__ import annotations

import threading

from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.core import QgsMessageLog, Qgis, QgsApplication
from .cloud.auth import AuthManager, debug_log_keyring_backends
from .cloud.client import WorkerJobsClient
from .util.messages import PLUGIN_LOG_TAG
from .processing.provider import NikaPlanetProvider
from .ui.login_panel import LoginPanel


class NikaPlanetPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.toolbar_action = None
        self.login_panel = None
        self.auth = AuthManager()
        self.jobs_client = WorkerJobsClient(self.auth)
        self._user_info: dict | None = None

    def initGui(self):
        self.toolbar_action = QAction("NikaPlanet", self.iface.mainWindow())
        self.toolbar_action.triggered.connect(self._toggle_panel)
        self.iface.addToolBarIcon(self.toolbar_action)
        self.iface.addPluginToMenu("NikaPlanet", self.toolbar_action)

        self.login_panel = LoginPanel(self.iface.mainWindow())
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.login_panel)
        self.login_panel.hide()
        self.login_panel.sign_in_clicked.connect(self._on_sign_in)
        self.login_panel.refresh_workers_clicked.connect(self._on_refresh_workers)
        self.login_panel.logout_clicked.connect(self._on_logout)
        self.login_panel.workers_page.catalog_loaded.connect(
            self._on_workers_fetched
        )

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
        self.provider = NikaPlanetProvider(self.auth, self.jobs_client)
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        self.iface.removeToolBarIcon(self.toolbar_action)
        self.iface.removePluginMenu("NikaPlanet", self.toolbar_action)
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

        self.provider._tenant_public_id = (user.get("ownedTenant") or {}).get("publicId")
        self.provider._authenticated = True

        self.login_panel.show_capabilities(username)
        self.login_panel.workers_page.set_client(self.jobs_client)

        # Refresh algorithms (fetches workers for owned tenant) then
        # populate the workers page with the results + invited tenants.
        QTimer.singleShot(0, self._refresh_and_load_workers)

        # Fetch job history for the Sessions tab.
        self.login_panel.workers_page.load_job_history()

    def _on_login_failed(self, error):
        QgsMessageLog.logMessage(
            f"Login failed: {error}", PLUGIN_LOG_TAG, Qgis.Warning
        )
        QMessageBox.warning(
            self.iface.mainWindow(),
            "NikaPlanet",
            f"Login failed:\n{error}",
        )

    # ── workers ────────────────────────────────────────────────────

    def _refresh_and_load_workers(self):
        """Fetch workers off the main thread; finalize the UI on main thread."""
        threading.Thread(target=self._do_fetch_workers, daemon=True).start()

    def _do_fetch_workers(self):
        """Run on a worker thread: fetch owned + invited tenant workers."""
        workers_page = self.login_panel.workers_page
        try:
            user = self._user_info or {}
            owned = user.get("ownedTenant") or {}
            owned_id = owned.get("publicId")

            owned_workers: list[dict] = []
            if owned_id:
                owned_workers = self.provider.fetch_remote_tasks(
                    tenant_public_id=owned_id,
                )

            tenants_data: list[dict] = []
            if owned_id:
                tenants_data.append({
                    "name": owned.get("name", "My Team"),
                    "workers": list(owned_workers),
                })
            for inv in user.get("invitedTenants") or []:
                tid = inv.get("publicId")
                if not tid:
                    continue
                workers = self.provider.fetch_remote_tasks(tenant_public_id=tid)
                tenants_data.append({
                    "name": inv.get("name", "Team"),
                    "workers": workers,
                })

            workers_page.catalog_loaded.emit(owned_workers, tenants_data)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Failed to refresh workers: {exc}",
                PLUGIN_LOG_TAG, Qgis.Warning,
            )
            workers_page.catalog_fetch_failed.emit()

    def _on_workers_fetched(
        self, owned_workers: list, tenants_data: list,
    ):
        """Main thread: register algorithms and populate the workers page."""
        self.provider._preloaded_tasks = list(owned_workers)
        self.provider.refreshAlgorithms()
        user = self._user_info or {}
        tenants_with_ids: list[dict] = []
        owned = user.get("ownedTenant") or {}
        if owned.get("publicId"):
            tenants_with_ids.append({
                "id": owned["publicId"],
                "name": owned.get("name", "My Team"),
            })
        for inv in user.get("invitedTenants") or []:
            if inv.get("publicId"):
                tenants_with_ids.append({
                    "id": inv["publicId"],
                    "name": inv.get("name", "Team"),
                })
        self.login_panel.workers_page.set_tenants(tenants_with_ids)
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
        self.provider._tenant_public_id = None
        self.provider.last_fetched_tasks = []
        self.login_panel.workers_page.clear_sessions()
        self.login_panel.show_login()
        QgsMessageLog.logMessage("Logged out", PLUGIN_LOG_TAG, Qgis.Info)
