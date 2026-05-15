from __future__ import annotations

# QgsProcessingProvider
import json

from qgis.core import QgsProcessingProvider, QgsMessageLog, Qgis
from qgis.PyQt.QtGui import QIcon

from .sample_algorithm import ExampleProcessingAlgorithm
from .remote_algorithm import RemoteAlgorithm
from ..cloud.auth import AuthManager
from ..cloud.client import WorkerJobsClient
from ..util.messages import PLUGIN_LOG_TAG


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
        self._tenant_public_id: str | None = None
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

    def fetch_remote_tasks(self, tenant_public_id: str | None = None) -> list[dict]:
        """Fetch the worker catalog for a tenant via ``WorkerJobsClient``."""
        tid = tenant_public_id or self._tenant_public_id
        if not tid:
            QgsMessageLog.logMessage("No tenantPublicId available — skipping remote fetch", PLUGIN_LOG_TAG, Qgis.Warning)
            return []
        if not self._client:
            QgsMessageLog.logMessage("No WorkerJobsClient configured", PLUGIN_LOG_TAG, Qgis.Warning)
            return []
        try:
            tasks = self._client.list_workers_for_tenant(tid)
            QgsMessageLog.logMessage(f"Fetched {len(tasks)} worker(s) for tenant {tid}", PLUGIN_LOG_TAG, Qgis.Info)
            for i, t in enumerate(tasks):
                QgsMessageLog.logMessage(
                    f"  worker[{i}]: {json.dumps(t, default=str)}",
                    PLUGIN_LOG_TAG, Qgis.Info,
                )
            return self._flatten_workers(tasks)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not fetch workers for tenant {tid}: {exc}",
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
                schema = ver.get("inputSchema") or {}
                flat.append({
                    "id": worker.get("id"),
                    "name": worker.get("name"),
                    "description": ver.get("description") or worker.get("description", ""),
                    "version": ver.get("versionTag"),
                    "tenantPublicId": worker.get("tenantPublicId"),
                    "tenantName": worker.get("tenantName"),
                    "planFeatures": worker.get("planFeatures"),
                    "visibility": worker.get("visibility"),
                    "owner": worker.get("owner"),
                    "versionId": ver.get("id"),
                    "program": ver.get("program"),
                    "script": ver.get("script"),
                    "inputs": schema.get("inputs", []),
                    "dirMounts": ver.get("dirMounts"),
                    "imageDigest": ver.get("imageDigest"),
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
