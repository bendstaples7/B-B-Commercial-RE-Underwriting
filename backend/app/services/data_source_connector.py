"""Data Source Connector service for external lead enrichment.

Provides a plugin-based registry for external data sources (county records,
skip tracing services, MLS data, etc.).  Each plugin implements the
``DataSourcePlugin`` interface.  The ``DataSourceConnector`` orchestrates
lookups, creates ``EnrichmentRecord`` entries, and updates lead fields on
successful enrichment.

Long-running bulk enrichment is offloaded to the Celery task queue.
"""
import abc
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from flask import has_app_context

from app import db
from app.models.enrichment import DataSource, EnrichmentRecord
from app.models.lead import Lead, LeadAuditTrail

logger = logging.getLogger(__name__)

# Batch size for bulk enrichment Celery task
BULK_ENRICH_BATCH_SIZE = 100

# Lead fields that can be updated by enrichment data
ENRICHABLE_FIELDS = [
    "property_type", "bedrooms", "bathrooms", "square_footage",
    "lot_size", "year_built", "ownership_type", "acquisition_date",
    "assessed_value", "most_recent_sale_price",
    "phone_1", "phone_2", "phone_3", "email_1", "email_2",
    "mailing_address", "mailing_city", "mailing_state", "mailing_zip",
    "owner_first_name", "owner_last_name",
    # Enrichment-specific JSON data fields
    "violation_data", "permit_data", "tax_distress_data",
]

JSON_MERGE_FIELDS = frozenset({
    "tax_distress_data",
    "violation_data",
    "permit_data",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EnrichmentData:
    """Container for data returned by a data source plugin lookup."""

    fields: dict = field(default_factory=dict)
    """Mapping of lead field names to enriched values."""


@dataclass
class DataSourceInfo:
    """Read-only summary of a registered data source."""

    id: int
    name: str
    is_active: bool


# ---------------------------------------------------------------------------
# Plugin base class
# ---------------------------------------------------------------------------

class DataSourcePlugin(abc.ABC):
    """Base class for external data source plugins.

    Subclass this and implement :meth:`lookup` to integrate a new external
    data source.  Register instances with
    :meth:`DataSourceConnector.register_source`.
    """

    name: str = ""
    """Human-readable name for this data source (must be unique)."""

    @abc.abstractmethod
    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        """Query the external source for enrichment data.

        Parameters
        ----------
        address : str
            Property address to look up.
        owner_name : str
            Owner name to look up.

        Returns
        -------
        EnrichmentData or None
            Enrichment payload, or ``None`` if no results found.
        """


# ---------------------------------------------------------------------------
# Connector service
# ---------------------------------------------------------------------------

class DataSourceConnector:
    """Plugin registry and orchestrator for external data source enrichment.

    Usage::

        connector = DataSourceConnector()
        connector.register_source(MyPlugin())
        record = connector.enrich_lead(lead_id=42, source_name="my_plugin")
    """

    def __init__(self) -> None:
        self._plugins: dict[str, DataSourcePlugin] = {}
        _register_default_plugins(self)
        if has_app_context():
            self.ensure_registered_data_sources()

    # ------------------------------------------------------------------
    # Plugin management
    # ------------------------------------------------------------------

    def register_source(self, plugin: DataSourcePlugin) -> None:
        """Register an external data source plugin.

        If a ``DataSource`` row does not yet exist for this plugin name,
        one is created automatically.

        Parameters
        ----------
        plugin : DataSourcePlugin
            An instance of a ``DataSourcePlugin`` subclass.

        Raises
        ------
        ValueError
            If a plugin with the same name is already registered.
        """
        if not plugin.name:
            raise ValueError("Plugin must have a non-empty 'name' attribute")

        if plugin.name in self._plugins:
            raise ValueError(
                f"A plugin named '{plugin.name}' is already registered"
            )

        self._plugins[plugin.name] = plugin

        if has_app_context():
            self._ensure_data_source_row(plugin.name)
            logger.info("Registered data source plugin '%s'", plugin.name)
        else:
            logger.info(
                "Registered data source plugin '%s' in memory (DB sync deferred)",
                plugin.name,
            )

    def _ensure_data_source_row(self, name: str) -> DataSource:
        """Create the DataSource DB row for a plugin if it does not exist."""
        ds = DataSource.query.filter_by(name=name).first()
        if not ds:
            ds = DataSource(name=name, is_active=True)
            db.session.add(ds)
            db.session.commit()
            logger.info("Registered new data source: %s (id=%d)", ds.name, ds.id)
        return ds

    def ensure_registered_data_sources(self) -> list[DataSource]:
        """Ensure every built-in plugin has an active DataSource catalog row."""
        rows: list[DataSource] = []
        for name in sorted(self._plugins):
            rows.append(self._ensure_data_source_row(name))
        return rows

    def _register_plugin_in_memory(self, plugin: DataSourcePlugin) -> None:
        """Attach a plugin to the in-memory registry without touching the DB."""
        if not plugin.name:
            raise ValueError("Plugin must have a non-empty 'name' attribute")
        if plugin.name not in self._plugins:
            self._plugins[plugin.name] = plugin

    def list_sources(self) -> list[DataSourceInfo]:
        """Return a summary of all registered in-memory plugins.

        Returns
        -------
        list[DataSourceInfo]
        """
        infos: list[DataSourceInfo] = []
        for name in sorted(self._plugins):
            if has_app_context():
                data_source = self._ensure_data_source_row(name)
            else:
                data_source = DataSource.query.filter_by(name=name).first()
                if data_source is None:
                    continue
            infos.append(
                DataSourceInfo(
                    id=data_source.id,
                    name=data_source.name,
                    is_active=data_source.is_active,
                )
            )
        return infos

    # ------------------------------------------------------------------
    # Single-lead enrichment
    # ------------------------------------------------------------------

    def enrich_lead(
        self,
        lead_id: int,
        source_name: str,
        *,
        refresh_scoring: bool = True,
    ) -> EnrichmentRecord:
        """Enrich a single lead from the specified data source.

        Creates an ``EnrichmentRecord`` regardless of outcome:
        - ``"success"`` – data was found and lead fields updated.
        - ``"no_results"`` – the source returned no data.
        - ``"failed"`` – an exception occurred during lookup.

        Parameters
        ----------
        lead_id : int
            ID of the lead to enrich.
        source_name : str
            Name of the registered data source plugin.
        refresh_scoring : bool, optional
            When True (default), recompute lead score after a successful enrich.
            Orchestrated multi-plugin runs should pass False and rescore once at
            the end.

        Returns
        -------
        EnrichmentRecord
            The created enrichment record.

        Raises
        ------
        ValueError
            If the lead or data source is not found, or the plugin is
            not registered.
        """
        # Resolve lead
        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        # Resolve data source row + plugin
        plugin, data_source = self._resolve_plugin(source_name)

        # Attempt lookup
        record = EnrichmentRecord(
            lead_id=lead.id,
            data_source_id=data_source.id,
            status="pending",
        )
        db.session.add(record)
        db.session.flush()  # get record.id for logging

        try:
            result = self._lookup_plugin(plugin, lead)
        except Exception as exc:
            record.status = "failed"
            record.error_reason = str(exc)
            db.session.commit()
            logger.error(
                "Enrichment failed for lead %d from source '%s': %s",
                lead_id, source_name, exc,
            )
            return record

        if result is None or not result.fields:
            record.status = "no_results"
            db.session.commit()
            logger.info(
                "No enrichment results for lead %d from source '%s'",
                lead_id, source_name,
            )
            return record

        # Apply enrichment data to lead fields
        self._apply_enrichment(lead, result, source_name)

        record.status = "success"
        record.retrieved_data = self._json_safe(result.fields)
        db.session.commit()

        logger.info(
            "Enriched lead %d from source '%s': %d fields updated",
            lead_id, source_name, len(result.fields),
        )

        # Enrichment may have written new phone/email/property fields, which
        # change the data-completeness and owner-situation sub-scores. Refresh
        # lead_score + recommended_action (error-isolated) so the score does not
        # go stale until the nightly bulk rescore.
        if refresh_scoring:
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(lead.id)

        return record

    # ------------------------------------------------------------------
    # Bulk enrichment (Celery task entry point)
    # ------------------------------------------------------------------

    def bulk_enrich(
        self,
        lead_ids: list[int],
        source_name: str,
    ) -> list[EnrichmentRecord]:
        """Enrich multiple leads from the specified data source.

        Processes leads in batches of ``BULK_ENRICH_BATCH_SIZE``.  This
        method is intended to be called from a Celery task wrapper.

        Parameters
        ----------
        lead_ids : list[int]
            IDs of leads to enrich.
        source_name : str
            Name of the registered data source plugin.

        Returns
        -------
        list[EnrichmentRecord]
            All created enrichment records.

        Raises
        ------
        ValueError
            If the data source is not found or the plugin is not
            registered.
        """
        # Validate source exists before starting
        self._resolve_plugin(source_name)

        records: list[EnrichmentRecord] = []

        for i in range(0, len(lead_ids), BULK_ENRICH_BATCH_SIZE):
            batch_ids = lead_ids[i: i + BULK_ENRICH_BATCH_SIZE]
            for lid in batch_ids:
                try:
                    record = self.enrich_lead(lid, source_name)
                    records.append(record)
                except ValueError as exc:
                    # Lead not found — skip but log
                    logger.warning("Skipping lead %d during bulk enrich: %s", lid, exc)
                except Exception as exc:
                    logger.error(
                        "Unexpected error enriching lead %d: %s", lid, exc,
                    )

            logger.info(
                "Bulk enrich batch %d-%d complete (%d records so far)",
                i, i + len(batch_ids), len(records),
            )

        logger.info(
            "Bulk enrichment complete: %d/%d leads processed for source '%s'",
            len(records), len(lead_ids), source_name,
        )
        return records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lookup_plugin(plugin: DataSourcePlugin, lead: Lead) -> Optional[EnrichmentData]:
        """Resolve enrichment data, preferring county_assessor_pin when available."""
        lookup_for_lead = getattr(plugin, "lookup_for_lead", None)
        if callable(lookup_for_lead):
            return lookup_for_lead(lead)

        owner_name = (
            f"{lead.owner_first_name or ''} {lead.owner_last_name or ''}"
        ).strip()
        pin = getattr(lead, "county_assessor_pin", None)
        if pin and str(pin).strip():
            lookup_by_pin = getattr(plugin, "lookup_by_pin", None)
            if callable(lookup_by_pin):
                return lookup_by_pin(str(pin).strip())

        address = lead.property_street or ""
        return plugin.lookup(address, owner_name)

    @staticmethod
    def _merge_json_field(existing, incoming):
        """Merge enrichment JSON payloads from multiple plugins."""
        def merge_records(left, right):
            merged = []
            for item in left + right:
                if item not in merged:
                    merged.append(item)
            return merged

        if existing is None:
            return incoming
        if isinstance(existing, dict) and isinstance(incoming, dict):
            merged = dict(existing)
            for key, value in incoming.items():
                if key not in merged:
                    merged[key] = value
                elif isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = merge_records(merged[key], value)
                elif isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
            return merged
        if isinstance(existing, list) and isinstance(incoming, dict):
            merged = dict(incoming)
            incoming_records = merged.get("records")
            merged["records"] = merge_records(
                existing,
                incoming_records if isinstance(incoming_records, list) else [],
            )
            return merged
        if isinstance(existing, dict) and isinstance(incoming, list):
            merged = dict(existing)
            records = merged.get("records")
            if isinstance(records, list):
                merged["records"] = merge_records(records, incoming)
            else:
                merged["records"] = incoming
            return merged
        if isinstance(existing, list) and isinstance(incoming, list):
            return merge_records(existing, incoming)
        return incoming

    @staticmethod
    def _json_safe(value):
        """Return a JSON-serializable copy of plugin data."""
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                str(key): DataSourceConnector._json_safe(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [DataSourceConnector._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [DataSourceConnector._json_safe(item) for item in value]
        return value

    def _resolve_plugin(
        self, source_name: str
    ) -> tuple[DataSourcePlugin, DataSource]:
        """Look up both the in-memory plugin and the database DataSource row.

        Parameters
        ----------
        source_name : str

        Returns
        -------
        tuple[DataSourcePlugin, DataSource]

        Raises
        ------
        ValueError
            If the plugin is not registered or the DataSource row is
            missing / inactive.
        """
        plugin = self._plugins.get(source_name)
        if plugin is None:
            raise ValueError(f"No plugin registered with name '{source_name}'")

        if has_app_context():
            data_source = self._ensure_data_source_row(source_name)
        else:
            data_source = DataSource.query.filter_by(name=source_name).first()
            if data_source is None:
                raise ValueError(f"DataSource '{source_name}' not found in database")

        if not data_source.is_active:
            raise ValueError(f"DataSource '{source_name}' is inactive")

        return plugin, data_source

    def _apply_enrichment(
        self,
        lead: Lead,
        enrichment_data: EnrichmentData,
        source_name: str,
    ) -> None:
        """Apply enrichment data to lead fields and record audit trail.

        Only fields listed in ``ENRICHABLE_FIELDS`` are updated.  An
        audit trail entry is created for each changed field.

        Parameters
        ----------
        lead : Lead
        enrichment_data : EnrichmentData
        source_name : str
            Used for the ``changed_by`` audit trail value.
        """
        for field_name, new_value in enrichment_data.fields.items():
            if field_name not in ENRICHABLE_FIELDS:
                logger.debug(
                    "Skipping non-enrichable field '%s' from source '%s'",
                    field_name, source_name,
                )
                continue

            old_value = getattr(lead, field_name, None)
            if field_name in JSON_MERGE_FIELDS:
                new_value = DataSourceConnector._merge_json_field(old_value, new_value)

            # Convert to comparable string representations
            old_str = str(old_value) if old_value is not None else None
            new_str = str(new_value) if new_value is not None else None

            if old_str != new_str:
                # Record audit trail
                audit = LeadAuditTrail(
                    lead_id=lead.id,
                    field_name=field_name,
                    old_value=old_str,
                    new_value=new_str,
                    changed_by=f"enrichment:{source_name}",
                )
                db.session.add(audit)

                # Update lead field
                setattr(lead, field_name, new_value)

        lead.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Auto-registration: ensure all known plugins can be discovered and
# registered by default when a DataSourceConnector is used.
# ---------------------------------------------------------------------------

# Lazy imports to avoid circular imports at module load time
def _register_default_plugins(connector: "DataSourceConnector") -> None:
    """Register all built-in data source plugins on *connector*.

    This is called automatically by the app factory to ensure every
    plugin is available without manual registration.
    """
    from app.services.plugins.cook_county_assessor import CookCountyAssessorPlugin
    from app.services.plugins.cook_county_permits import CookCountyPermitsPlugin
    from app.services.plugins.cook_county_tax_sales import CookCountyTaxSalesPlugin
    from app.services.plugins.cook_county_commercial_valuation import (
        CookCountyCommercialValuationPlugin,
    )
    from app.services.plugins.cook_county_appeals import CookCountyAppealsPlugin
    from app.services.plugins.cook_county_tax_exempt import CookCountyTaxExemptPlugin
    from app.services.plugins.cook_county_scavenger_tax_sale import (
        CookCountyScavengerTaxSalePlugin,
    )
    from app.services.plugins.chicago_building_violations import (
        ChicagoBuildingViolationsPlugin,
    )
    from app.services.plugins.chicago_scofflaw import ChicagoScofflawPlugin
    from app.services.plugins.chicago_vacant_buildings import ChicagoVacantBuildingsPlugin
    from app.services.plugins.chicago_311_complaints import Chicago311ComplaintsPlugin
    from app.services.plugins.cook_county_owner_lookup import CookCountyOwnerLookupPlugin

    for plugin_cls in (
        CookCountyAssessorPlugin,
        CookCountyPermitsPlugin,
        CookCountyTaxSalesPlugin,
        CookCountyCommercialValuationPlugin,
        CookCountyAppealsPlugin,
        CookCountyTaxExemptPlugin,
        CookCountyScavengerTaxSalePlugin,
        ChicagoBuildingViolationsPlugin,
        ChicagoScofflawPlugin,
        ChicagoVacantBuildingsPlugin,
        Chicago311ComplaintsPlugin,
        CookCountyOwnerLookupPlugin,
    ):
        try:
            connector._register_plugin_in_memory(plugin_cls())
        except ValueError:
            pass
