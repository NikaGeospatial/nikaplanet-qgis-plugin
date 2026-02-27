# QgsProcessingProvider
from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsMessageLog, Qgis
from .sample_algorithm import ExampleProcessingAlgorithm
class GeoEngineCloudProvider(QgsProcessingProvider):
    """A container for processing algorithms we will fetch from the cloud API."""
    def loadAlgorithms(self):
        try:
            self.addAlgorithm(ExampleProcessingAlgorithm())
        except Exception as e:
            QgsMessageLog.logMessage(f"Error loading algorithms: {e}", "GeoEngine Cloud", Qgis.Error)

    def id(self):
        """Return unique provider id."""
        return "geoengine-cloud"

    def name(self):
        """Return unique provider name."""
        return self.tr("GeoEngine Cloud")

    def icon(self) -> QIcon:
        """Return the provider icon."""
        return QgsProcessingProvider.icon(self)