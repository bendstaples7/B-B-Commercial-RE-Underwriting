"""Google Sheets Importer service for importing lead data from Google Sheets."""
import os
import logging
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app import db
from app.models.lead import Lead, LeadAuditTrail
from app.models.import_job import ImportJob, FieldMapping, OAuthToken
from app.services.helpers.deal_source import (
    infer_deal_source_from_lead_fields,
)

logger = logging.getLogger(__name__)


def _fill_deal_source_from_import_source(lead: Lead) -> bool:
    """Fill blank ``deal_source`` from free-text ``source`` / description when mappable.

    Returns True when the lead was updated.
    """
    if (lead.deal_source or '').strip():
        return False
    mapped = infer_deal_source_from_lead_fields(
        source=getattr(lead, 'source', None),
        deal_description=getattr(lead, 'deal_description', None),
    )
    if not mapped:
        return False
    lead.deal_source = mapped
    return True


def _split_owner_name(first: Optional[str], last: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Normalize owner name fields to ensure first and last are separate.

    Handles the common import pattern where a full name ("John Smith") is
    placed entirely in the first_name column with last_name left empty.

    Rules:
    - If last is already populated, return as-is (no change needed).
    - If first contains a space and last is absent, split on the last space:
        "John Smith"      → first="John",       last="Smith"
        "Mary Ann Jones"  → first="Mary Ann",   last="Jones"
        "Manuel Medellin" → first="Manuel",     last="Medellin"
    - If first has no space and last is absent, move first to last (surname only).
    - Comma-separated "Last, First" format is also handled:
        "Smith, John"     → first="John",       last="Smith"
    """
    if not first:
        return first, last
    first = first.strip()
    if not first:
        return None, last

    # If last is already populated, nothing to do
    if last and last.strip():
        return first, last.strip()

    # Comma format: "Smith, John A" → last="Smith", first="John A"
    if ',' in first:
        parts = [p.strip() for p in first.split(',', 1)]
        return (parts[1] if parts[1] else None), (parts[0] if parts[0] else None)

    # Space-separated: split on last space
    if ' ' in first:
        idx = first.rfind(' ')
        return first[:idx].strip() or None, first[idx:].strip() or None

    # Single token with no last — leave as-is (could be a first name only)
    return first, last


# ---------------------------------------------------------------------------
# Data classes used as lightweight return types
# ---------------------------------------------------------------------------

@dataclass
class AuthResult:
    """Result of an OAuth2 authentication attempt."""
    success: bool
    error: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class SheetInfo:
    """Metadata about a single sheet inside a spreadsheet."""
    sheet_id: int
    title: str
    row_count: int
    column_count: int


@dataclass
class ValidationResult:
    """Result of validating a single import row."""
    valid: bool
    errors: list = field(default_factory=list)
    cleaned_data: dict = field(default_factory=dict)


@dataclass
class ImportResult:
    """Summary returned after an import job finishes."""
    job_id: int
    total_rows: int
    rows_imported: int
    rows_skipped: int
    status: str
    error_log: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Field-mapping synonyms – maps common header variations to DB column names
# ---------------------------------------------------------------------------

FIELD_SYNONYMS: dict[str, list[str]] = {
    "property_street": [
        "property street", "property_street", "street", "street address",
        "address", "property address", "prop address", "property addr",
        "prop_address",
    ],
    "property_city": [
        "property city", "property_city", "prop city",
    ],
    "property_state": [
        "property state", "property_state", "prop state",
    ],
    "property_zip": [
        "property zip", "property_zip", "prop zip", "property zipcode",
        "property zip code",
    ],
    "property_type": [
        "property type", "property_type", "prop type", "type",
        "property category",
    ],
    "bedrooms": [
        "bedrooms", "beds", "bed", "br", "num bedrooms", "bedroom count",
    ],
    "bathrooms": [
        "bathrooms", "baths", "bath", "ba", "num bathrooms", "bathroom count",
    ],
    "square_footage": [
        "square footage", "square_footage", "sqft", "sq ft", "square feet",
        "living area", "sq footage", "squarefootage",
    ],
    "lot_size": [
        "lot size", "lot_size", "lot area", "land size", "lot sq ft",
        "lot sqft",
    ],
    "year_built": [
        "year built", "year_built", "yr built", "built year", "yearbuilt",
    ],
    "owner_first_name": [
        "owner first name", "owner_first_name", "first name", "first",
        "owner first", "firstname",
    ],
    "owner_last_name": [
        "owner last name", "owner_last_name", "last name", "last",
        "owner last", "lastname", "surname",
    ],
    "ownership_type": [
        "ownership type", "ownership_type", "ownership", "owner type",
    ],
    "acquisition_date": [
        "acquisition date", "acquisition_date", "purchase date",
        "date acquired", "date of acquisition",
    ],
    "phone_1": [
        "phone 1", "phone_1", "phone", "primary phone", "phone1",
        "phone number",
    ],
    "phone_2": [
        "phone 2", "phone_2", "secondary phone", "phone2", "alt phone",
    ],
    "phone_3": [
        "phone 3", "phone_3", "phone3", "other phone",
    ],
    "email_1": [
        "email 1", "email_1", "email", "primary email", "email1",
        "email address",
    ],
    "email_2": [
        "email 2", "email_2", "secondary email", "email2", "alt email",
    ],
    "mailing_address": [
        "mailing address", "mailing_address", "mail address",
        "mailing street",
    ],
    "mailing_city": [
        "mailing city", "mailing_city", "mail city", "city",
    ],
    "mailing_state": [
        "mailing state", "mailing_state", "mail state", "state",
    ],
    "mailing_zip": [
        "mailing zip", "mailing_zip", "mail zip", "zip", "zip code",
        "zipcode", "postal code",
    ],
    "source": ["source", "lead source", "property source", "found from", "where found"],
    "date_identified": ["date identified", "date_identified", "identified date", "found date", "date found"],
    "notes": ["notes", "note", "comments", "comment"],
    "needs_skip_trace": ["needs skip trace", "needs_skip_trace", "next to skip", "skip trace needed"],
    "skip_tracer": ["skip tracer", "skip_tracer", "tracer", "traced by"],
    "date_skip_traced": ["date skip traced", "date_skip_traced", "skip trace date", "traced date"],
    "date_added_to_hubspot": ["date added to hubspot", "date_added_to_hubspot", "hubspot date", "crm date"],
    "units": ["units", "unit count", "num units", "number of units"],
    "units_allowed": ["units allowed", "units_allowed", "allowed units", "zoning units"],
    "zoning": ["zoning", "zone", "zoning code", "zoning type"],
    "county_assessor_pin": ["county assessor pin", "county_assessor_pin", "assessor pin", "pin", "tax pin", "parcel number"],
    "tax_bill_2021": ["2021 tax bill", "tax_bill_2021", "tax bill", "taxes 2021", "annual taxes"],
    "most_recent_sale": ["most recent sale", "most_recent_sale", "last sale", "recent sale", "sale date"],
    "owner_2_first_name": ["owner 2 first name", "owner_2_first_name", "second owner first", "owner2 first"],
    "owner_2_last_name": ["owner 2 last name", "owner_2_last_name", "second owner last", "owner2 last"],
    "address_2": ["address 2", "address_2", "secondary address", "unit number", "apt"],
    "returned_addresses": ["returned addresses", "returned_addresses", "bounced", "returned mail", "bad address"],
    "phone_4": ["phone 4", "phone_4", "phone4"],
    "phone_5": ["phone 5", "phone_5", "phone5"],
    "phone_6": ["phone 6", "phone_6", "phone6"],
    "phone_7": ["phone 7", "phone_7", "phone7"],
    "email_3": ["email 3", "email_3", "email3"],
    "email_4": ["email 4", "email_4", "email4"],
    "email_5": ["email 5", "email_5", "email5"],
    "socials": ["socials", "social media", "linkedin", "facebook", "social links"],
    "up_next_to_mail": ["up next to mail", "up_next_to_mail", "next to mail", "mail target"],  # legacy; prefer mail_ready + MailQueueItem
    "mailer_history": ["mailer history", "mailer_history", "mailers", "mailer"],
    "lead_category": [
        "lead category", "lead_category", "category", "lead type",
        "residential or commercial", "res/comm", "asset class",
    ],
}

# Reverse lookup: normalised synonym → db field
_SYNONYM_INDEX: dict[str, str] = {}
for _db_field, _synonyms in FIELD_SYNONYMS.items():
    for _syn in _synonyms:
        _SYNONYM_INDEX[_syn.strip().lower()] = _db_field

# Required fields that must be present in every imported row
REQUIRED_FIELDS: set[str] = set()  # No required fields — import everything possible

# Maximum lengths mirroring the SQLAlchemy / DDL column definitions
FIELD_MAX_LENGTHS: dict[str, int] = {
    "property_street": 500,
    "property_city": 100,
    "property_state": 50,
    "property_zip": 20,
    "property_type": 50,
    "owner_first_name": 128,
    "owner_last_name": 128,
    "ownership_type": 100,
    "phone_1": 30,
    "phone_2": 30,
    "phone_3": 30,
    "email_1": 255,
    "email_2": 255,
    "mailing_address": 500,
    "mailing_city": 100,
    "mailing_state": 50,
    "mailing_zip": 20,
    "data_source": 100,
    "source": 100,
    "skip_tracer": 100,
    "zoning": 100,
    "county_assessor_pin": 50,
    "most_recent_sale": 255,
    "owner_2_first_name": 128,
    "owner_2_last_name": 128,
    "address_2": 500,
    "phone_4": 30,
    "phone_5": 30,
    "phone_6": 30,
    "phone_7": 30,
    "email_3": 255,
    "email_4": 255,
    "email_5": 255,
    "lead_category": 50,
}

# Fields expected to hold integer values
INTEGER_FIELDS = {"bedrooms", "square_footage", "lot_size", "year_built", "units", "units_allowed"}

# Fields expected to hold float / decimal values
FLOAT_FIELDS = {"bathrooms", "tax_bill_2021"}

# Fields expected to hold date values (YYYY-MM-DD or similar)
DATE_FIELDS = {"acquisition_date", "date_identified", "date_skip_traced", "date_added_to_hubspot"}

# Fields expected to hold boolean values
BOOLEAN_FIELDS = {"needs_skip_trace", "up_next_to_mail"}

# Google Sheets API scopes
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


# ---------------------------------------------------------------------------
# Encryption helpers for OAuth refresh tokens
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    """Return a Fernet instance using the configured encryption key."""
    key = os.getenv("OAUTH_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("OAUTH_ENCRYPTION_KEY environment variable is not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt_token(token: str) -> bytes:
    return _get_fernet().encrypt(token.encode())


def _decrypt_token(encrypted: bytes) -> str:
    return _get_fernet().decrypt(encrypted).decode()


# ---------------------------------------------------------------------------
# GoogleSheetsImporter
# ---------------------------------------------------------------------------

class GoogleSheetsImporter:
    """Service for importing lead data from Google Sheets.

    Handles OAuth2 authentication, sheet discovery, header reading,
    automatic field mapping, row validation, and upsert-based import
    with audit trail recording.
    """

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, credentials: dict) -> AuthResult:
        """Authenticate with Google using OAuth2 credentials.

        Parameters
        ----------
        credentials : dict
            Must contain either:
            - ``refresh_token`` and ``client_id`` / ``client_secret`` for
              server-side token refresh, **or**
            - ``auth_code`` and ``redirect_uri`` for the initial OAuth2
              code-exchange flow.

        Returns
        -------
        AuthResult
            Indicates success/failure.  On success the refresh token is
            persisted (encrypted) in the ``oauth_tokens`` table.
        """
        try:
            user_id = credentials.get("user_id", "default")

            if "refresh_token" in credentials:
                creds = Credentials(
                    token=None,
                    refresh_token=credentials["refresh_token"],
                    client_id=credentials.get("client_id", os.getenv("GOOGLE_CLIENT_ID", "")),
                    client_secret=credentials.get("client_secret", os.getenv("GOOGLE_CLIENT_SECRET", "")),
                    token_uri="https://oauth2.googleapis.com/token",
                    scopes=SCOPES,
                )
                # Validate the token by refreshing it
                from google.auth.transport.requests import Request as AuthRequest
                creds.refresh(AuthRequest())
            elif "auth_code" in credentials:
                flow = Flow.from_client_config(
                    {
                        "web": {
                            "client_id": credentials.get("client_id", os.getenv("GOOGLE_CLIENT_ID", "")),
                            "client_secret": credentials.get("client_secret", os.getenv("GOOGLE_CLIENT_SECRET", "")),
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    },
                    scopes=SCOPES,
                    redirect_uri=credentials.get("redirect_uri", ""),
                )
                flow.fetch_token(code=credentials["auth_code"])
                creds = flow.credentials
            else:
                return AuthResult(success=False, error="Missing refresh_token or auth_code in credentials")

            # Persist encrypted refresh token
            encrypted = _encrypt_token(creds.refresh_token or credentials.get("refresh_token", ""))
            token_record = OAuthToken.query.filter_by(user_id=user_id).first()
            if token_record:
                token_record.encrypted_refresh_token = encrypted
                token_record.token_expiry = creds.expiry
                token_record.updated_at = datetime.utcnow()
            else:
                token_record = OAuthToken(
                    user_id=user_id,
                    encrypted_refresh_token=encrypted,
                    token_expiry=creds.expiry,
                )
                db.session.add(token_record)
            db.session.commit()

            logger.info("Google OAuth2 authentication succeeded for user %s", user_id)
            return AuthResult(success=True, user_id=user_id)

        except Exception as exc:
            logger.error("Google OAuth2 authentication failed: %s", exc)
            db.session.rollback()
            return AuthResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Sheet discovery
    # ------------------------------------------------------------------

    def _build_sheets_service(self, token: OAuthToken):
        """Build a Google Sheets API service from a stored OAuthToken."""
        refresh_token = _decrypt_token(token.encrypted_refresh_token)
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        return build("sheets", "v4", credentials=creds)

    def list_sheets(self, spreadsheet_id: str, token: OAuthToken) -> list[SheetInfo]:
        """Return metadata for every sheet in the given spreadsheet.

        Parameters
        ----------
        spreadsheet_id : str
            The Google Sheets spreadsheet ID.
        token : OAuthToken
            Stored OAuth token for the requesting user.

        Returns
        -------
        list[SheetInfo]
        """
        service = self._build_sheets_service(token)
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets: list[SheetInfo] = []
        for sheet in spreadsheet.get("sheets", []):
            props = sheet.get("properties", {})
            grid = props.get("gridProperties", {})
            sheets.append(
                SheetInfo(
                    sheet_id=props.get("sheetId", 0),
                    title=props.get("title", ""),
                    row_count=grid.get("rowCount", 0),
                    column_count=grid.get("columnCount", 0),
                )
            )
        return sheets

    def read_headers(self, spreadsheet_id: str, sheet_name: str, token: OAuthToken) -> list[str]:
        """Read the first (header) row of the specified sheet.

        Parameters
        ----------
        spreadsheet_id : str
        sheet_name : str
        token : OAuthToken

        Returns
        -------
        list[str]
            Column header strings.
        """
        service = self._build_sheets_service(token)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!1:1")
            .execute()
        )
        values = result.get("values", [[]])
        return values[0] if values else []

    # ------------------------------------------------------------------
    # Field mapping
    # ------------------------------------------------------------------

    def auto_map_fields(self, headers: list[str]) -> dict[str, str]:
        """Automatically map sheet column headers to Lead DB fields.

        Uses synonym matching: each header is normalised (lowered, stripped)
        and looked up in ``_SYNONYM_INDEX``.  Headers that do not match any
        known synonym are omitted from the returned mapping.

        Parameters
        ----------
        headers : list[str]
            Raw column header strings from the Google Sheet.

        Returns
        -------
        dict[str, str]
            ``{sheet_column_header: db_field_name}`` for every header that
            matched a known synonym.
        """
        mapping: dict[str, str] = {}
        mapped_fields: set[str] = set()

        for header in headers:
            normalised = header.strip().lower()
            db_field = _SYNONYM_INDEX.get(normalised)
            if db_field and db_field not in mapped_fields:
                mapping[header] = db_field
                mapped_fields.add(db_field)

        return mapping

    @staticmethod
    def validate_mapping(mapping: dict[str, str]) -> tuple[bool, list[str]]:
        """Check that all required DB fields are covered by the mapping.

        Parameters
        ----------
        mapping : dict[str, str]
            ``{sheet_column: db_field}``

        Returns
        -------
        tuple[bool, list[str]]
            ``(is_valid, list_of_missing_required_fields)``
        """
        mapped_db_fields = set(mapping.values())
        missing = REQUIRED_FIELDS - mapped_db_fields
        return (len(missing) == 0, sorted(missing))

    # ------------------------------------------------------------------
    # Row validation
    # ------------------------------------------------------------------

    def validate_row(self, row: dict, field_mapping: dict[str, str]) -> ValidationResult:
        """Validate and clean a single row of imported data.

        Uses lenient validation: bad values in individual fields are set
        to None instead of rejecting the entire row.  A row is only
        skipped if it has no usable data at all.

        Parameters
        ----------
        row : dict
            ``{sheet_column_header: cell_value}``
        field_mapping : dict[str, str]
            ``{sheet_column_header: db_field_name}``

        Returns
        -------
        ValidationResult
        """
        warnings: list[str] = []
        cleaned: dict[str, object] = {}

        # Translate sheet columns → db fields
        for sheet_col, db_field in field_mapping.items():
            raw_value = row.get(sheet_col)
            # Treat None and empty-string as missing
            if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
                raw_value = None
            elif isinstance(raw_value, str):
                raw_value = raw_value.strip()
            cleaned[db_field] = raw_value

        # Check if the row has any data at all — skip completely empty rows
        has_any_data = any(v is not None for v in cleaned.values())
        if not has_any_data:
            return ValidationResult(valid=False, errors=["Row is completely empty"])

        # Length constraints — truncate instead of rejecting
        for field_name, max_len in FIELD_MAX_LENGTHS.items():
            value = cleaned.get(field_name)
            if value is not None and isinstance(value, str) and len(value) > max_len:
                # For phone fields, just store as-is
                if field_name.startswith("phone_"):
                    pass
                else:
                    cleaned[field_name] = value[:max_len]
                    warnings.append(f"Field '{field_name}' truncated to {max_len} chars")

        # Integer fields — set to None if unparseable
        for field_name in INTEGER_FIELDS:
            value = cleaned.get(field_name)
            if value is not None:
                try:
                    cleaned[field_name] = int(float(str(value).replace(',', '')))
                except (ValueError, TypeError):
                    cleaned[field_name] = None
                    warnings.append(f"Field '{field_name}' not a number, skipped (got '{value}')")

        # Float fields — set to None if unparseable
        for field_name in FLOAT_FIELDS:
            value = cleaned.get(field_name)
            if value is not None:
                try:
                    cleaned[field_name] = float(str(value).replace(',', ''))
                except (ValueError, TypeError):
                    cleaned[field_name] = None
                    warnings.append(f"Field '{field_name}' not a number, skipped (got '{value}')")

        # Date fields — set to None if unparseable
        for field_name in DATE_FIELDS:
            value = cleaned.get(field_name)
            if value is not None:
                if isinstance(value, date):
                    cleaned[field_name] = value
                else:
                    str_value = str(value).strip()
                    if str_value.lower() in ("n/a", "na", "none", "-", ""):
                        cleaned[field_name] = None
                    else:
                        if ',' in str_value:
                            str_value = str_value.split(',')[0].strip()
                        parsed = self._parse_date(str_value)
                        if parsed is None:
                            cleaned[field_name] = None
                            warnings.append(f"Field '{field_name}' not a valid date, skipped (got '{value}')")
                        else:
                            cleaned[field_name] = parsed

        # Boolean fields
        for field_name in BOOLEAN_FIELDS:
            value = cleaned.get(field_name)
            if value is not None:
                if isinstance(value, bool):
                    cleaned[field_name] = value
                else:
                    str_val = str(value).strip().lower()
                    if str_val in ("y", "yes", "true", "1"):
                        cleaned[field_name] = True
                    else:
                        cleaned[field_name] = False
            else:
                cleaned[field_name] = False

        # Normalize owner name fields — split full name in first_name into first + last
        # when last_name is absent (common import pattern from HubSpot/spreadsheet exports)
        self._normalize_name_fields(cleaned)

        pin = cleaned.get('county_assessor_pin')
        if pin:
            from app.services.plugins.pin_utils import format_pin_for_storage
            cleaned['county_assessor_pin'] = format_pin_for_storage(str(pin))

        return ValidationResult(valid=True, cleaned_data=cleaned, errors=warnings)

    @staticmethod
    def _normalize_name_fields(cleaned: dict) -> None:
        """Split owner_first_name into first + last when owner_last_name is absent.

        Mutates cleaned in-place. Also applies the same logic for owner_2 names.
        """
        # Primary owner
        first, last = _split_owner_name(
            cleaned.get('owner_first_name'),
            cleaned.get('owner_last_name'),
        )
        cleaned['owner_first_name'] = first
        cleaned['owner_last_name'] = last

        # Second owner
        first2, last2 = _split_owner_name(
            cleaned.get('owner_2_first_name'),
            cleaned.get('owner_2_last_name'),
        )
        cleaned['owner_2_first_name'] = first2
        cleaned['owner_2_last_name'] = last2

    @staticmethod
    def _parse_date(value: str) -> Optional[date]:
        """Try several common date formats and return a ``date`` or ``None``."""
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%m/%d/%y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------
    # Deduplication helpers
    # ------------------------------------------------------------------

    # Unit designators that appear after a street number+name and indicate
    # a specific unit within a multi-unit building.
    _UNIT_PATTERNS = (
        r'\s+(apt|apartment|unit|ste|suite|#|fl|floor|no\.?)\s*\S+$',
        r'\s+\d+[a-z]?$',   # trailing bare number or number+letter, e.g. "2553 N Drake Ave 1"
    )

    @classmethod
    def _strip_unit(cls, street: Optional[str]) -> Optional[str]:
        """Return the street address with any trailing unit designator removed.

        Examples
        --------
        "2553 N Drake Ave 1"          → "2553 N Drake Ave"
        "470 N Kenilworth Ave # 30"   → "470 N Kenilworth Ave"
        "1501 Jefferson Ave # 101"    → "1501 Jefferson Ave"
        "2553 N Drake Ave"            → "2553 N Drake Ave"  (unchanged)
        """
        import re
        if not street:
            return street
        s = street.strip()
        for pattern in cls._UNIT_PATTERNS:
            s = re.sub(pattern, '', s, flags=re.IGNORECASE).strip()
        return s or street.strip()

    @classmethod
    def _find_duplicate(
        cls,
        validated_data: dict,
        owner_user_id: Optional[str] = None,
    ) -> Optional[Lead]:
        """Look for an existing Lead that represents the same property+owner.

        Dedup priority (checked in order):
        1. ``county_assessor_pin`` — unambiguous parcel identifier.
        2. Exact ``property_street`` match (current behaviour).
        2a. Normalized street for same ``owner_user_id`` (no owner names needed) —
            catches Places full addresses vs abbreviated DB streets.
        2b. Normalized ``property_street`` for same owner name (e.g. Schiller vs Schiller St).
        3. Same owner name + same *base* street (strip unit suffix from both
           sides) — catches "2553 N Drake Ave" vs "2553 N Drake Ave 1".

        The ``owner_user_id`` scope is applied when provided, so two
        different users importing the same address create separate records.
        """
        from sqlalchemy import func as sa_func
        from app.services.lead_dedup_service import find_lead_by_identity
        from app.services.lead_merge_utils import (
            cities_compatible,
            dedup_street_key,
            street_line_from_address,
            streets_match_normalized,
        )

        # 1. PIN + owner/street identity (PIN, exact street, normalized street)
        pin = validated_data.get("county_assessor_pin")
        street = validated_data.get("property_street")
        first = validated_data.get("owner_first_name")
        last = validated_data.get("owner_last_name")
        incoming_city = (validated_data.get("property_city") or "").strip() or None
        if not incoming_city and street:
            from app.services.gis.routing import parse_city_state_zip_from_address

            parsed_city, _parsed_state, _parsed_zip = parse_city_state_zip_from_address(street)
            incoming_city = (parsed_city or "").strip() or None

        hit = find_lead_by_identity(
            owner_user_id=owner_user_id,
            owner_first_name=first,
            owner_last_name=last,
            property_street=street,
            county_assessor_pin=pin,
        )
        if hit:
            if pin or cities_compatible(incoming_city, hit.property_city):
                return hit

        # 2. Exact street match (legacy path when owner names missing)
        if street:
            q = Lead.query.filter(Lead.property_street == street)
            if owner_user_id:
                q = q.filter(Lead.owner_user_id == owner_user_id)
            for candidate in q.limit(20).all():
                if cities_compatible(incoming_city, candidate.property_city):
                    return candidate

        # 2a. Owner-scoped normalized street (Quick Add / ownerless imports)
        if street and owner_user_id:
            street_line = street_line_from_address(street) or street.strip()
            street_key = dedup_street_key(street_line)
            if street_key:
                for candidate in (
                    Lead.query
                    .filter(Lead.owner_user_id == owner_user_id)
                    .filter(Lead.normalized_street == street_key)
                    .limit(20)
                    .all()
                ):
                    if cities_compatible(incoming_city, candidate.property_city):
                        return candidate
            tokens = street_line.split()
            house = tokens[0] if tokens else ''
            if house and house[0].isdigit() and len(tokens) >= 2:
                escaped_house = (
                    house.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                )
                candidates = (
                    Lead.query
                    .filter(Lead.owner_user_id == owner_user_id)
                    .filter(Lead.property_street.isnot(None))
                    .filter(Lead.property_street.ilike(f"{escaped_house} %", escape='\\'))
                    .limit(40)
                    .all()
                )
                for candidate in candidates:
                    if not cities_compatible(incoming_city, candidate.property_city):
                        continue
                    if streets_match_normalized(street_line, candidate.property_street):
                        return candidate

        # 2b. Normalized street match (e.g. "Schiller" vs "Schiller St")
        if street and first and last:
            street_line = street_line_from_address(street) or street.strip()
            q = (
                Lead.query
                .filter(Lead.owner_first_name.ilike(first))
                .filter(Lead.owner_last_name.ilike(last))
                .filter(Lead.property_street.isnot(None))
            )
            if owner_user_id:
                q = q.filter(Lead.owner_user_id == owner_user_id)
            for candidate in q:
                if not cities_compatible(incoming_city, candidate.property_city):
                    continue
                if streets_match_normalized(street_line, candidate.property_street):
                    return candidate

        # 3. Same owner + same base street (unit-stripped), bidirectional.
        #
        # Covers both import orders:
        #   a) Incoming has unit suffix → strip it, look for bare or unit records
        #   b) Incoming is bare → look for existing unit-address records for same owner
        #
        # The DB-side match is constrained to known unit suffix patterns via a
        # regex (rather than a broad ILIKE prefix) to avoid false merges on
        # streets that share a common prefix (e.g. "123 Main St" vs "123 Main Street").
        base_street = cls._strip_unit(street)
        first = validated_data.get("owner_first_name")
        last = validated_data.get("owner_last_name")
        if base_street and first and last:
            incoming_has_unit = base_street.lower() != (street or '').strip().lower()
            incoming_is_bare = not incoming_has_unit

            # Run if incoming has a unit suffix (original case) OR incoming is bare
            # and could match an existing unit-address record (reverse case).
            if incoming_has_unit or incoming_is_bare:
                import re as _re
                # Only match DB records whose street is either the exact base
                # or the base followed by a recognised unit designator pattern.
                # This prevents "123 Oak St" from matching "123 Oak Street # 1".
                unit_pattern = (
                    r'(?i)^'
                    + _re.escape(base_street)
                    + r'(\s+(apt|apartment|unit|ste|suite|#|fl|floor|no\.?)\s*\S+|\s+\d+[a-z]?)$'
                )
                q = (
                    Lead.query
                    .filter(Lead.owner_first_name.ilike(first))
                    .filter(Lead.owner_last_name.ilike(last))
                )
                if owner_user_id:
                    q = q.filter(Lead.owner_user_id == owner_user_id)
                bind = db.session.get_bind()
                if bind is not None and bind.dialect.name == 'postgresql':
                    hit = q.filter(
                        db.or_(
                            Lead.property_street == base_street,
                            Lead.property_street.op('~*')(unit_pattern),
                        )
                    ).first()
                    if hit and cities_compatible(incoming_city, hit.property_city):
                        return hit
                else:
                    for candidate in q.filter(Lead.property_street.isnot(None)).limit(50).all():
                        if not cities_compatible(incoming_city, candidate.property_city):
                            continue
                        if candidate.property_street == base_street or streets_match_normalized(
                            base_street,
                            candidate.property_street,
                        ):
                            return candidate

        return None

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert_lead(
        self,
        validated_data: dict,
        import_job_id: Optional[int] = None,
        data_source: str = "google_sheets",
        owner_user_id: Optional[str] = None,
    ) -> Lead:
        """Insert a new Lead or update an existing one.

        Deduplication is performed in priority order:
        1. ``county_assessor_pin`` — parcel identifier, most authoritative.
        2. Exact ``property_street`` match.
        2b. Normalized ``property_street`` for same owner (abbreviation variants).
        3. Same owner name + same base street (unit suffix stripped) —
           prevents phantom duplicates when a bare building address is
           imported alongside a specific unit address for the same owner.

        When updating, changed fields are recorded in the audit trail.

        Parameters
        ----------
        validated_data : dict
            Cleaned field values keyed by DB column name.
        import_job_id : int, optional
            The current ImportJob id (used for metadata and audit trail).
        data_source : str
            Identifier written to ``Lead.data_source``.
        owner_user_id : str, optional
            Scopes the duplicate search to a specific user's leads.

        Returns
        -------
        Lead
            The created or updated Lead instance.
        """
        existing = self._find_duplicate(validated_data, owner_user_id=owner_user_id)

        if existing:
            # Update existing lead and record audit trail
            changed_by = f"import_job:{import_job_id}" if import_job_id else "manual"
            self._update_lead_fields(existing, validated_data, changed_by)
            existing.data_source = data_source
            if import_job_id:
                existing.last_import_job_id = import_job_id
            existing.updated_at = datetime.utcnow()
            _fill_deal_source_from_import_source(existing)
            return existing
        else:
            # Create new lead
            from sqlalchemy.exc import IntegrityError
            from app.services.lead_dedup_service import find_lead_by_identity

            lead = Lead(
                data_source=data_source,
                last_import_job_id=import_job_id,
            )
            if owner_user_id:
                lead.owner_user_id = owner_user_id
            self._set_lead_fields(lead, validated_data)
            _fill_deal_source_from_import_source(lead)
            db.session.add(lead)
            try:
                with db.session.begin_nested():
                    db.session.flush()
            except IntegrityError:
                existing = find_lead_by_identity(
                    owner_user_id=owner_user_id,
                    owner_first_name=validated_data.get("owner_first_name"),
                    owner_last_name=validated_data.get("owner_last_name"),
                    property_street=validated_data.get("property_street"),
                    county_assessor_pin=validated_data.get("county_assessor_pin"),
                )
                if not existing:
                    raise
                changed_by = f"import_job:{import_job_id}" if import_job_id else "manual"
                self._update_lead_fields(existing, validated_data, changed_by)
                existing.data_source = data_source
                if import_job_id:
                    existing.last_import_job_id = import_job_id
                existing.updated_at = datetime.utcnow()
                _fill_deal_source_from_import_source(existing)
                return existing
            try:
                from app.services.contact_service import ContactService
                with db.session.begin_nested():
                    ContactService().upsert_owners_from_lead(lead, commit=False)
            except Exception as exc:
                logger.warning(
                    "Contact upsert after sheets create failed for lead_id=%s: %s",
                    getattr(lead, 'id', None), exc,
                )
            return lead

    # ------------------------------------------------------------------
    # Audit trail helpers
    # ------------------------------------------------------------------

    AUDITABLE_FIELDS = {
        "property_street", "property_city", "property_state", "property_zip",
        "property_type", "bedrooms", "bathrooms",
        "square_footage", "lot_size", "year_built", "owner_first_name",
        "owner_last_name", "ownership_type", "acquisition_date",
        "phone_1", "phone_2", "phone_3", "email_1", "email_2",
        "mailing_address", "mailing_city", "mailing_state", "mailing_zip",
        "source", "date_identified", "notes",
        "needs_skip_trace", "skip_tracer", "date_skip_traced",
        "date_added_to_hubspot",
        "units", "units_allowed", "zoning", "county_assessor_pin",
        "tax_bill_2021", "most_recent_sale",
        "owner_2_first_name", "owner_2_last_name",
        "address_2", "returned_addresses",
        "phone_4", "phone_5", "phone_6", "phone_7",
        "email_3", "email_4", "email_5",
        "socials",
        "up_next_to_mail", "mailer_history",
        "lead_category",
    }

    def _update_lead_fields(self, lead: Lead, data: dict, changed_by: str) -> None:
        """Update lead fields and create audit trail entries for changes."""
        for field_name in self.AUDITABLE_FIELDS:
            if field_name not in data:
                continue
            new_value = data[field_name]
            old_value = getattr(lead, field_name, None)

            # Normalise for comparison
            old_str = str(old_value) if old_value is not None else None
            new_str = str(new_value) if new_value is not None else None

            if old_str != new_str:
                audit = LeadAuditTrail(
                    lead_id=lead.id,
                    field_name=field_name,
                    old_value=old_str,
                    new_value=new_str,
                    changed_by=changed_by,
                )
                db.session.add(audit)
                setattr(lead, field_name, new_value)

        # Infer property_type from units when the sheet didn't supply it
        # and the lead still has no property_type after the update.
        if not lead.property_type and lead.units:
            inferred = self._infer_property_type_from_units(lead.units)
            if inferred:
                # Read the actual current value before overwriting it so the
                # audit trail is accurate (old_value=None only if it was truly
                # NULL, not if a prior field in this loop already set it).
                current_property_type = lead.property_type  # still falsy here
                audit = LeadAuditTrail(
                    lead_id=lead.id,
                    field_name='property_type',
                    old_value=str(current_property_type) if current_property_type else None,
                    new_value=inferred,
                    changed_by=changed_by,
                )
                db.session.add(audit)
                lead.property_type = inferred

        # Keep relational contacts in sync with flat owner / phone / email fields.
        try:
            from app.services.contact_service import ContactService
            with db.session.begin_nested():
                ContactService().upsert_owners_from_lead(lead, commit=False)
        except Exception as exc:
            logger.warning(
                "Contact upsert after sheets update failed for lead_id=%s: %s",
                getattr(lead, 'id', None), exc,
            )

    @staticmethod
    def _infer_property_type_from_units(units: Optional[int]) -> Optional[str]:
        """Return a property_type string inferred from unit count.

        Used to back-fill property_type when it is absent from the import
        but units is known.  Returns None when units is None or zero.

        Mapping:
            1 unit  → 'single_family'
            2 units → 'duplex'
            3 units → 'triplex'
            4 units → 'fourplex'
            5+      → 'multi_family'
        """
        if units is None or units < 1:
            return None
        return {1: 'single_family', 2: 'duplex', 3: 'triplex', 4: 'fourplex'}.get(units, 'multi_family')

    @staticmethod
    def _set_lead_fields(lead: Lead, data: dict) -> None:
        """Set fields on a brand-new Lead from validated data."""
        for key, value in data.items():
            if hasattr(lead, key):
                setattr(lead, key, value)
        # Infer property_type from units when the sheet didn't supply it
        if not lead.property_type and lead.units:
            lead.property_type = GoogleSheetsImporter._infer_property_type_from_units(lead.units)

    # ------------------------------------------------------------------
    # Import orchestration
    # ------------------------------------------------------------------

    def process_import(self, job_id: int, lead_category: str = 'residential') -> ImportResult:
        """Execute an import job: read rows from Google Sheets, validate,
        and upsert into the database.

        This method is the Celery task entry point.  It expects the
        ``ImportJob`` to already exist with status ``in_progress``.

        Parameters
        ----------
        job_id : int
            Primary key of the ``ImportJob`` to process.

        Returns
        -------
        ImportResult
        """
        job = ImportJob.query.get(job_id)
        if not job:
            logger.error("ImportJob %s not found", job_id)
            return ImportResult(
                job_id=job_id, total_rows=0, rows_imported=0,
                rows_skipped=0, status="failed",
                error_log=[{"error": f"ImportJob {job_id} not found"}],
            )

        try:
            job.status = "in_progress"
            job.started_at = datetime.utcnow()
            db.session.commit()

            # Resolve token and field mapping
            token = OAuthToken.query.filter_by(user_id=job.user_id).first()
            if not token:
                raise RuntimeError(f"No OAuth token found for user {job.user_id}")

            field_mapping_record = job.field_mapping
            if not field_mapping_record:
                raise RuntimeError(f"No field mapping associated with ImportJob {job_id}")
            mapping = field_mapping_record.mapping  # dict[str, str]

            # Read all data rows (skip header)
            rows = self._read_all_rows(job.spreadsheet_id, job.sheet_name, token)
            headers = rows[0] if rows else []
            data_rows = rows[1:] if len(rows) > 1 else []

            job.total_rows = len(data_rows)
            db.session.commit()

            error_log: list[dict] = []
            rows_imported = 0
            rows_skipped = 0

            for idx, raw_row in enumerate(data_rows, start=2):  # row 2 in sheet
                # Build dict from positional values
                row_dict = {}
                for col_idx, header in enumerate(headers):
                    row_dict[header] = raw_row[col_idx] if col_idx < len(raw_row) else None

                result = self.validate_row(row_dict, mapping)

                if not result.valid:
                    rows_skipped += 1
                    error_log.append({"row": idx, "errors": result.errors})
                    logger.debug("Row %d skipped: %s", idx, result.errors)
                else:
                    try:
                        # Inject lead_category into the cleaned data if not already set
                        if 'lead_category' not in result.cleaned_data or not result.cleaned_data['lead_category']:
                            result.cleaned_data['lead_category'] = lead_category
                        # Use a savepoint so a single row failure doesn't rollback prior rows
                        with db.session.begin_nested():
                            self.upsert_lead(
                                result.cleaned_data,
                                import_job_id=job_id,
                                data_source="google_sheets",
                                owner_user_id=job.user_id,
                            )
                        rows_imported += 1
                    except Exception as row_exc:
                        rows_skipped += 1
                        error_log.append({"row": idx, "errors": [str(row_exc)]})
                        logger.warning("Row %d upsert failed: %s", idx, row_exc)

                # Update progress periodically (every 50 rows)
                if (idx - 1) % 50 == 0:
                    job.rows_processed = rows_imported + rows_skipped
                    job.rows_imported = rows_imported
                    job.rows_skipped = rows_skipped
                    db.session.commit()

            # Finalise
            job.status = "completed"
            job.rows_processed = rows_imported + rows_skipped
            job.rows_imported = rows_imported
            job.rows_skipped = rows_skipped
            job.error_log = error_log
            job.completed_at = datetime.utcnow()
            db.session.commit()

            logger.info(
                "ImportJob %s completed: %d imported, %d skipped out of %d",
                job_id, rows_imported, rows_skipped, job.total_rows,
            )

            # ------------------------------------------------------------------
            # Fix A: GIS enrichment for Sheets-imported leads
            #
            # Google Sheets imports land with has_property_match=False because
            # upsert_lead() never calls the GIS connector.  Run enrichment now
            # on every lead touched by this job that still lacks a confirmed
            # parcel match.  Connector is selected per-lead based on county/city
            # so both DuPage and Cook County leads are handled correctly.
            # ------------------------------------------------------------------
            try:
                from app.services.gis.routing import connector_for_lead
                from app.services.deduplication_engine import DeduplicationEngine
                from app.services.gis.base import GISConnectorRegistry
                from app.services.lead_ingestion_service import LeadIngestionService

                ingestion_svc = LeadIngestionService(
                    dedup_engine=DeduplicationEngine(),
                    gis_registry=GISConnectorRegistry,
                )
                # Query leads that were created/updated by this job and
                # still need a parcel match resolved.
                unmatched = (
                    Lead.query
                    .filter(
                        Lead.last_import_job_id == job_id,
                        Lead.has_property_match == False,  # noqa: E712
                        Lead.property_street != None,       # noqa: E711
                        Lead.property_street != '',
                    )
                    .all()
                )
                gis_matched = 0
                gis_errors = 0
                gis_no_connector = 0
                matched_lead_ids = []
                for lead in unmatched:
                    connector = connector_for_lead(lead)
                    if not connector:
                        gis_no_connector += 1
                        continue
                    outcome = ingestion_svc._enrich_with_gis(lead, connector, job_id)
                    if outcome.get('error'):
                        gis_errors += 1
                    elif outcome.get('match_found'):
                        gis_matched += 1
                        matched_lead_ids.append(lead.id)
                if unmatched:
                    db.session.commit()
                    logger.info(
                        "ImportJob %s GIS enrichment: %d/%d matched, %d errors, "
                        "%d no-connector",
                        job_id, gis_matched, len(unmatched), gis_errors,
                        gis_no_connector,
                    )
                    # Bug 8: GIS enrichment just changed scoring inputs
                    # (has_property_match / county_assessor_pin) for the matched
                    # leads. Refresh lead_score + recommended_action now so they
                    # reflect the enrichment instead of going stale until the
                    # nightly bulk rescore. refresh_lead_scoring is per-lead and
                    # error-isolated (never raises into this best-effort block).
                    if matched_lead_ids:
                        from app.services.lead_refresh import refresh_lead_scoring
                        for matched_lead_id in matched_lead_ids:
                            refresh_lead_scoring(matched_lead_id)
                        logger.info(
                            "ImportJob %s GIS enrichment: refreshed scoring for %d lead(s)",
                            job_id, len(matched_lead_ids),
                        )
            except Exception as gis_exc:
                # GIS enrichment is best-effort — never fail a completed import.
                # The import data was already committed above, so roll back only
                # the (uncommitted) GIS sub-step. A failed enrichment or its
                # commit leaves the session in a "needs rollback" state; without
                # this the next caller to reuse the session hits a poisoned
                # transaction. This cannot undo the already-committed import
                # rows, and the post-commit refresh_lead_scoring loop commits
                # per-lead internally, so it is unaffected.
                db.session.rollback()
                logger.error(
                    "ImportJob %s: post-import GIS enrichment failed: %s",
                    job_id, gis_exc,
                )

            return ImportResult(
                job_id=job_id,
                total_rows=job.total_rows,
                rows_imported=rows_imported,
                rows_skipped=rows_skipped,
                status="completed",
                error_log=error_log,
            )

        except Exception as exc:
            logger.error("ImportJob %s failed: %s", job_id, exc)
            db.session.rollback()
            job = ImportJob.query.get(job_id)
            if job:
                job.status = "failed"
                job.error_log = [{"error": str(exc)}]
                job.completed_at = datetime.utcnow()
                db.session.commit()
            return ImportResult(
                job_id=job_id, total_rows=0, rows_imported=0,
                rows_skipped=0, status="failed",
                error_log=[{"error": str(exc)}],
            )

    def _read_all_rows(
        self, spreadsheet_id: str, sheet_name: str, token: OAuthToken
    ) -> list[list[str]]:
        """Read all rows (including header) from the specified sheet."""
        service = self._build_sheets_service(token)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_name)
            .execute()
        )
        return result.get("values", [])
