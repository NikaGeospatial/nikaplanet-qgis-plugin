from __future__ import annotations

# QgsProcessingProvider
import json
import urllib.request

from qgis.core import QgsProcessingProvider, QgsMessageLog, Qgis
from qgis.PyQt.QtGui import QIcon

from .sample_algorithm import ExampleProcessingAlgorithm
from .remote_algorithm import RemoteAlgorithm
from ..cloud.auth import AuthManager
from ..cloud.client import WorkerJobsClient
from ..util.http import safe_urlopen
from ..util.messages import PLUGIN_LOG_TAG
from ..util.settings import get_control_server_url


class NikaPlanetProvider(QgsProcessingProvider):
    """A container for processing algorithms we will fetch from the cloud API."""

    def __init__(
        self,
        auth: AuthManager | None = None,
        client: WorkerJobsClient | None = None,
    ):
        super().__init__()
        self._auth = auth
        self._client = client
        self._authenticated = False
        self._tenant_id: str | None = None
        self.last_fetched_tasks: list[dict] = []
        self._preloaded_tasks: list[dict] | None = None

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

        if self._preloaded_tasks is not None:
            self.last_fetched_tasks = self._preloaded_tasks
            self._preloaded_tasks = None
        else:
            self.last_fetched_tasks = self.fetch_remote_tasks()
        for task_def in self.last_fetched_tasks:
            try:
                self.addAlgorithm(RemoteAlgorithm(task_def, self._client))
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
            with safe_urlopen(req, timeout=10) as resp:
                status = resp.status
                raw = resp.read()
                QgsMessageLog.logMessage(f"Response status={status}, body length={len(raw)}", PLUGIN_LOG_TAG, Qgis.Info)
                tasks = json.loads(raw)
                QgsMessageLog.logMessage(f"Parsed {len(tasks)} remote task(s)", PLUGIN_LOG_TAG, Qgis.Info)
                for i, t in enumerate(tasks):
                    QgsMessageLog.logMessage(
                        f"  worker[{i}]: {json.dumps(t, default=str)}",
                        PLUGIN_LOG_TAG, Qgis.Info,
                    )
                return self._flatten_workers(tasks)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not fetch remote tasks from {url}: {exc}",
                PLUGIN_LOG_TAG, Qgis.Warning,
            )
            return []

    @staticmethod
    def _flatten_workers(tasks: list[dict]) -> list[dict]:
        """Flatten nested API response into one entry per version."""
        flat = []
        for worker in tasks:
            versions = worker.get("versions", [])
            for ver in versions:
                schema = ver.get("input_schema") or {}
                flat.append({
                    "id": worker.get("id"),
                    "name": worker.get("name"),
                    "description": ver.get("description") or worker.get("description", ""),
                    "version": ver.get("version_tag"),
                    "tenantId": worker.get("tenant_id"),
                    "tenantName": worker.get("tenant_name"),
                    "planFeatures": worker.get("plan_features"),
                    "visibility": worker.get("visibility"),
                    "owner": worker.get("owner"),
                    "versionId": ver.get("id"),
                    "program": ver.get("program"),
                    "script": ver.get("script"),
                    "inputs": schema.get("inputs", []),
                    "dirMounts": ver.get("dir_mounts"),
                    "imageDigest": ver.get("image_digest"),
                })
        return flat

    def id(self):
        """Return unique provider id."""
        return "nikaplanet"

    def name(self):
        """Return unique provider name."""
        return self.tr("NikaPlanet")

    def icon(self) -> QIcon:
        """Return the provider icon."""
        return QgsProcessingProvider.icon(self)
