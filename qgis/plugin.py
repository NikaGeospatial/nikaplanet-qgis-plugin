from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsMessageLog, Qgis
from .processing.provider import GeoEngineCloudProvider
from qgis.core import QgsApplication


class GeoEngineCloudPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        self.action = QAction("GeoEngine Cloud: Hello", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("GeoEngine Cloud", self.action)
        self.initProcessing()

    def initProcessing(self):
        self.provider = GeoEngineCloudProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("GeoEngine Cloud", self.action)

    def run(self):
        QgsMessageLog.logMessage(
            "GeoEngine Cloud plugin is alive!", "GeoEngine", Qgis.Info
        )
        QMessageBox.information(
            self.iface.mainWindow(),
            "GeoEngine Cloud",
            "Hello from GeoEngine Cloud plugin!\n\n"
            "The plugin loaded successfully.",
        )
