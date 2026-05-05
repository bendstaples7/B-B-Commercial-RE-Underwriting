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
from datetime import datetime
from typing import Optional

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
    "phone_1", "phone_2", "phone_3", "email_1", "email_2",
    "mailing_address", "mailing_city", "mailing_state", "mailing_zip",
]


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

        # Ensure a DataSource row exists in the database
        ds = DataSource.query.filter_by(name=plugin.name).first()
        if not ds:
            ds = DataSource(name=plugin.name, is_active=True)
            db.session.add(ds)
            db.session.commit()
            logger.info("Registered new data source: %s (id=%d)", ds.name, ds.id)
        else:
            logger.info("Plugin '%s' attached to existing DataSource id=%d", plugin.name, ds.id)

    def list_sources(self) -> list[DataSourceInfo]:
        """Return a summary of all registered data sources.

        Returns
        -------
        list[DataSourceInfo]
        """
        sources = DataSource.query.order_by(DataSource.name).all()
        return [
            DataSourceInfo(id=s.id, name=s.name, is_active=s.is_active)
            for s in sources
        ]

    # ------------------------------------------------------------------
    # Single-lead enrichment
    # ------------------------------------------------------------------

    def enrich_lead(self, lead_id: int, source_name: str) -> EnrichmentRecord:
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
            result = plugin.lookup(lead.property_street, f"{lead.owner_first_name} {lead.owner_last_name}")
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
        record.retrieved_data = result.fields
        db.session.commit()

        logger.info(
            "Enriched lead %d from source '%s': %d fields updated",
            lead_id, source_name, len(result.fields),
        )
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
