"""Deduplication engine for platform-wide lead ingestion deduplication.

Applies to all ingestion sources — not DuPage County specific.
Provides address normalization and lead lookup by normalized address + PIN.
"""
import re
from dataclasses import dataclass
from typing import Literal, Optional

# Pre-compiled regex patterns for performance
NORMALIZATION_PATTERN = re.compile(r'[^\w\s]')  # strip punctuation
WHITESPACE_PATTERN = re.compile(r'\s+')          # collapse whitespace


@dataclass
class DeduplicationResult:
    """Result of a deduplication operation.

    Attributes:
        outcome: One of 'created', 'updated', or 'conflict'.
        lead: The Lead (Property) record that was created or updated.
        conflict_detail: Field-level conflict info logged to ImportJob error_log,
                         or None when no conflict occurred.
    """
    outcome: Literal["created", "updated", "conflict"]
    lead: object  # Property / Lead instance — avoid circular import at module level
    conflict_detail: Optional[dict]


class DeduplicationEngine:
    """Platform-wide deduplication for all ingestion sources.

    Requirements 7.1–7.8:
    - Normalize addresses (uppercase, strip punctuation, collapse whitespace)
    - Check for existing lead by normalized address first, then PIN as fallback
    - Merge non-null incoming fields; preserve existing non-null values
    - Log field-level conflicts to the ImportJob error_log
    """

    # ------------------------------------------------------------------ #
    # Address normalization                                                #
    # ------------------------------------------------------------------ #

    def normalize_address(self, address: str) -> str:
        """Return a normalized address string.

        Transforms the input by:
        1. Converting to uppercase
        2. Stripping punctuation characters (anything that is not a word char or whitespace)
        3. Collapsing runs of whitespace to a single space and stripping leading/trailing space

        Args:
            address: Raw address string (e.g. "123 Main St., Apt. #4")

        Returns:
            Normalized address (e.g. "123 MAIN ST APT 4")
        """
        addr = address.upper()
        addr = NORMALIZATION_PATTERN.sub('', addr)
        addr = WHITESPACE_PATTERN.sub(' ', addr).strip()
        return addr

    # ------------------------------------------------------------------ #
    # Lead lookup                                                          #
    # ------------------------------------------------------------------ #

    def find_existing_lead(
        self,
        property_street: str,
        pin: Optional[str] = None,
    ) -> Optional[object]:
        """Look up an existing Lead by normalized address, with PIN as secondary key.

        Strategy (cross-database compatible — works on both SQLite and PostgreSQL):
        1. Fetch all leads whose uppercased property_street begins with the same
           first token as the incoming address (narrows the candidate set cheaply).
        2. Apply full Python-side normalization to each candidate and compare.
        3. If no address match is found and a PIN is provided, query by PIN directly.

        This avoids database-side regexp_replace (not available in SQLite) while
        remaining efficient enough for typical batch ingestion workloads.

        Args:
            property_street: Incoming property street address.
            pin: Optional county assessor PIN for secondary lookup.

        Returns:
            Matching Property/Lead instance, or None if no match found.
        """
        from app.models.lead import Property
        from app import db

        normalized_incoming = self.normalize_address(property_street)

        # ---- Primary key: normalized address ----
        # Strategy: fetch all candidates with a non-null property_street, then apply
        # full Python-side normalization to each and compare against normalized_incoming.
        #
        # A SQL LIKE pre-filter was previously used to narrow the candidate set before
        # the Python comparison. However, that filter is unreliable for arbitrary inputs
        # because:
        #   1. SQL upper() does not expand Unicode characters the same way Python's
        #      str.upper() does (e.g. 'ß'.upper() == 'SS' in Python but not in SQLite).
        #   2. The normalized prefix has punctuation stripped, so a stored raw address
        #      like '0:AAa' (upper='0:AAA') won't contain the normalized prefix '0AAA'.
        #   3. LIKE wildcard characters (% _) in the address itself break the filter
        #      even with manual escaping when no ESCAPE clause is set.
        #
        # The Python-side normalization comparison is the authoritative deduplication
        # check. For production workloads with large tables, a separate pre-computed
        # normalized_address column with an index is the correct optimization path.
        candidates = (
            db.session.query(Property)
            .filter(Property.property_street.isnot(None))
            .all()
        )

        for candidate in candidates:
            if candidate.property_street and \
               self.normalize_address(candidate.property_street) == normalized_incoming:
                return candidate

        # ---- Secondary key: PIN ----
        if pin:
            lead = (
                db.session.query(Property)
                .filter(Property.county_assessor_pin == pin)
                .first()
            )
            return lead

        return None

    # ------------------------------------------------------------------ #
    # Field merge                                                          #
    # ------------------------------------------------------------------ #

    def merge_lead(
        self,
        existing,  # Property/Lead instance
        incoming: dict,
        import_job_id: int,
    ) -> DeduplicationResult:
        """Apply non-null incoming fields to an existing lead.

        Rules (Requirements 7.3, 7.5):
        - If incoming value is None or empty string → skip (don't overwrite).
        - If existing field is None/empty and incoming is non-null → update.
        - If both existing and incoming are non-null and differ → preserve existing,
          log a conflict entry.

        Args:
            existing: The existing Property/Lead ORM instance.
            incoming: Dict of field names → incoming values.
            import_job_id: ID of the current ImportJob (for conflict logging).

        Returns:
            DeduplicationResult with outcome='updated' or 'conflict'.
        """
        from app import db

        conflicts = []
        updated = False

        # Fields that must never be overwritten (internal metadata)
        PROTECTED_FIELDS = {'id', 'created_at', 'last_import_job_id'}

        for field, incoming_value in incoming.items():
            if field in PROTECTED_FIELDS:
                continue

            # Skip null/empty incoming values — never overwrite with nothing
            if incoming_value is None or incoming_value == '':
                continue

            existing_value = getattr(existing, field, None)

            if existing_value is None or existing_value == '':
                # Existing field is empty → safe to populate
                setattr(existing, field, incoming_value)
                updated = True
            elif existing_value != incoming_value:
                # Both non-null and different → preserve existing, log conflict
                conflicts.append({
                    'field': field,
                    'existing_value': str(existing_value),
                    'rejected_incoming_value': str(incoming_value),
                    'import_job_id': import_job_id,
                })

        # Always update the import job foreign key
        existing.last_import_job_id = import_job_id

        db.session.add(existing)

        conflict_detail = {'field_conflicts': conflicts} if conflicts else None
        outcome: Literal["updated", "conflict"] = 'conflict' if conflicts else 'updated'

        return DeduplicationResult(
            outcome=outcome,
            lead=existing,
            conflict_detail=conflict_detail,
        )

    # ------------------------------------------------------------------ #
    # Full deduplication flow                                              #
    # ------------------------------------------------------------------ #

    def process_record(
        self,
        record: dict,
        import_job_id: int,
    ) -> DeduplicationResult:
        """Full deduplication flow: find existing lead → merge or create.

        Steps (Requirements 7.1–7.8):
        1. Extract property_street and county_assessor_pin from record.
        2. Look up existing lead via find_existing_lead().
        3a. If found → merge_lead() and return outcome 'updated' or 'conflict'.
        3b. If not found → create new Property record, return outcome 'created'.

        PIN mismatch handling (Requirement 7.6):
        If the address matches an existing lead but the incoming PIN differs from
        the existing PIN, the existing lead is preserved unchanged and a conflict
        entry is logged.

        Args:
            record: Dict of lead fields for this ingestion record.
            import_job_id: ID of the current ImportJob.

        Returns:
            DeduplicationResult with outcome in {'created', 'updated', 'conflict'}.
        """
        from app.models.lead import Property
        from app import db

        property_street = record.get('property_street', '') or ''
        incoming_pin = record.get('county_assessor_pin')

        existing = self.find_existing_lead(property_street, incoming_pin)

        if existing is None:
            # No match — create a new lead
            new_lead = Property()
            for field, value in record.items():
                if hasattr(new_lead, field) and value is not None and value != '':
                    setattr(new_lead, field, value)
            new_lead.last_import_job_id = import_job_id
            db.session.add(new_lead)
            db.session.flush()  # populate new_lead.id without committing the transaction

            return DeduplicationResult(
                outcome='created',
                lead=new_lead,
                conflict_detail=None,
            )

        # ---- PIN mismatch check (Requirement 7.6) ----
        if incoming_pin and existing.county_assessor_pin and \
           existing.county_assessor_pin != incoming_pin:
            conflict_detail = {
                'type': 'pin_mismatch',
                'existing_lead_id': existing.id,
                'existing_pin': existing.county_assessor_pin,
                'incoming_pin': incoming_pin,
                'import_job_id': import_job_id,
            }
            return DeduplicationResult(
                outcome='conflict',
                lead=existing,
                conflict_detail=conflict_detail,
            )

        # ---- Merge ----
        return self.merge_lead(existing, record, import_job_id)
