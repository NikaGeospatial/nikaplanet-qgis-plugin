def classFactory(iface):
    from .plugin import NikaPlanetPlugin
    return NikaPlanetPlugin(iface)
