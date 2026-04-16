def classFactory(iface):
    from .plugin import GeoEngineCloudPlugin
    return GeoEngineCloudPlugin(iface)
