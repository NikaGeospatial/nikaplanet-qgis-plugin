# QgsProcessingProvider
import json
import urllib.request

from qgis.core import QgsProcessingProvider, QgsMessageLog, Qgis
from qgis.PyQt.QtGui import QIcon

from .sample_algorithm import ExampleProcessingAlgorithm
from .remote_algorithm import RemoteAlgorithm
from ..util.settings import get_control_server_url


def _fetch_remote_tasks() -> list[dict]:
    """GET /list from the control server; returns [] on failure."""
    url = f"{get_control_server_url()}/list"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        QgsMessageLog.logMessage(
            f"Could not fetch remote tasks from {url}: {exc}",
            "GeoEngine Cloud", Qgis.Warning,
        )
        return []


class GeoEngineCloudProvider(QgsProcessingProvider):
    """A container for processing algorithms we will fetch from the cloud API."""

    def loadAlgorithms(self):
        try:
            self.addAlgorithm(ExampleProcessingAlgorithm())
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading sample algorithm: {e}",
                "GeoEngine Cloud", Qgis.Warning,
            )

        for task_def in _fetch_remote_tasks():
            try:
                self.addAlgorithm(RemoteAlgorithm(task_def))
                QgsMessageLog.logMessage(
                    f"Loaded remote task: {task_def.get('name')}",
                    "GeoEngine Cloud", Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Error loading remote task {task_def.get('name')}: {e}",
                    "GeoEngine Cloud", Qgis.Warning,
                )

    def id(self):
        """Return unique provider id."""
        return "geoengine-cloud"

    def name(self):
        """Return unique provider name."""
        return self.tr("GeoEngine Cloud")

    def icon(self) -> QIcon:
        """Return the provider icon."""
        return QgsProcessingProvider.icon(self)
