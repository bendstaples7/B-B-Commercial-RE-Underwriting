from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class GISParcel:
    """Represents parcel data returned from a GIS lookup."""

    county_assessor_pin: Optional[str]
    property_type: Optional[str]
    year_built: Optional[int]
    square_footage: Optional[int]
    bedrooms: Optional[int]
    bathrooms: Optional[float]
    lot_size: Optional[int]
    owner_first_name: Optional[str]
    owner_last_name: Optional[str]
    mailing_address: Optional[str]
    mailing_city: Optional[str]
    mailing_state: Optional[str]
    mailing_zip: Optional[str]
    # Property situs (filled when the connector can resolve parcel address)
    property_city: Optional[str] = None
    property_state: Optional[str] = None
    property_zip: Optional[str] = None


class GISConnector(ABC):
    """Interface all GIS connectors must implement."""

    @abstractmethod
    def lookup_by_address(self, address: str) -> Optional[GISParcel]:
        """Lookup parcel by property address. Returns None if not found."""
        ...

    @abstractmethod
    def lookup_by_pin(self, pin: str) -> Optional[GISParcel]:
        """Lookup parcel by PIN. Returns None if not found."""
        ...

    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Machine-readable connector identifier, e.g. 'dupage_gis'."""
        ...

    @property
    @abstractmethod
    def market(self) -> str:
        """Market identifier this connector serves, e.g. 'dupage_il'."""
        ...


# Registry mapping market identifier → GISConnector instance
# e.g. {"dupage_il": DuPageGISConnector()}
GISConnectorRegistry: dict[str, "GISConnector"] = {}
