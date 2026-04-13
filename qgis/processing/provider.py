# QgsProcessingProvider
import json
import urllib.request

from qgis.core import QgsProcessingProvider, QgsMessageLog, Qgis
from qgis.PyQt.QtGui import QIcon

from .sample_algorithm import ExampleProcessingAlgorithm
from .remote_algorithm import RemoteAlgorithm
from ..cloud.auth import AuthManager
from ..util.messages import PLUGIN_LOG_TAG
from ..util.settings import get_control_server_url


class GeoEngineCloudProvider(QgsProcessingProvider):
    """A container for processing algorithms we will fetch from the cloud API."""

    def __init__(self, auth: AuthManager | None = None):
        super().__init__()
        self._auth = auth
        self._authenticated = False
        self._tenant_id: str | None = None
        self.last_fetched_tasks: list[dict] = []

    def loadAlgorithms(self):
        QgsMessageLog.logMessage(
            f"loadAlgorithms called, authenticated={self._authenticated}",
            PLUGIN_LOG_TAG, Qgis.Info,
        )
        try:
            self.addAlgorithm(ExampleProcessingAlgorithm())
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading sample algorithm: {e}",
                PLUGIN_LOG_TAG, Qgis.Warning,
            )

        if not self._authenticated:
            QgsMessageLog.logMessage(
                "Skipping remote task fetch — not authenticated yet",
                PLUGIN_LOG_TAG, Qgis.Info,
            )
            return

        self.last_fetched_tasks = self.fetch_remote_tasks()
        for task_def in self.last_fetched_tasks:
            try:
                self.addAlgorithm(RemoteAlgorithm(task_def, self._auth))
                QgsMessageLog.logMessage(
                    f"Loaded remote task: {task_def.get('name')}",
                    PLUGIN_LOG_TAG, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Error loading remote task {task_def.get('name')}: {e}",
                    PLUGIN_LOG_TAG, Qgis.Warning,
                )

    def fetch_remote_tasks(self, tenant_id: str | None = None) -> list[dict]:
        """GET /api/workers?tenantId=… from the control server."""
        tid = tenant_id or self._tenant_id
        if not tid:
            QgsMessageLog.logMessage("No tenantId available — skipping remote fetch", PLUGIN_LOG_TAG, Qgis.Warning)
            return []
        url = f"{get_control_server_url()}/api/workers?tenantId={tid}"
        QgsMessageLog.logMessage(f"Fetching remote tasks from {url}", PLUGIN_LOG_TAG, Qgis.Info)
        req = urllib.request.Request(url, method = "GET")
        if self._auth:
            token = self._auth.ensure_valid_token()
            if token:
                req.add_header("Authorization", f"Bearer {token}")
                QgsMessageLog.logMessage(f"Auth token attached (len={len(token)})", PLUGIN_LOG_TAG, Qgis.Info)
            else:
                QgsMessageLog.logMessage("No valid auth token available", PLUGIN_LOG_TAG, Qgis.Warning)
        else:
            QgsMessageLog.logMessage("No AuthManager configured", PLUGIN_LOG_TAG, Qgis.Warning)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                raw = resp.read()
                QgsMessageLog.logMessage(f"Response status={status}, body length={len(raw)}", PLUGIN_LOG_TAG, Qgis.Info)
                tasks = json.loads(raw)
                QgsMessageLog.logMessage(f"Parsed {len(tasks)} remote task(s)", PLUGIN_LOG_TAG, Qgis.Info)
                return tasks
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not fetch remote tasks from {url}: {exc}",
                PLUGIN_LOG_TAG, Qgis.Warning,
            )
            return []

    def id(self):
        """Return unique provider id."""
        return "geoengine-cloud"

    def name(self):
        """Return unique provider name."""
        return self.tr("GeoEngine Cloud")

    def icon(self) -> QIcon:
        """Return the provider icon."""
        return QgsProcessingProvider.icon(self)
