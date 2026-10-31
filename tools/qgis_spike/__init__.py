from typing import Any


def classFactory(iface: Any) -> Any:  # noqa: ANN401
    from .plugin import GeoQCSpike

    return GeoQCSpike(iface)
