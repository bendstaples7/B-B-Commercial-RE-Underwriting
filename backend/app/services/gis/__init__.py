# GIS connector interface and implementations
from .base import GISParcel, GISConnector, GISConnectorRegistry
from .dupage_gis_connector import DuPageGISConnector  # noqa: F401 — also triggers registry

__all__ = ["GISParcel", "GISConnector", "GISConnectorRegistry", "DuPageGISConnector"]
