"""Property-based tests for HubSpotSignalExtractorService — Properties 14 and 15.

Properties verified:
  14. Signal extraction keyword match is case-insensitive — for any engagement body
      containing a keyword from the signal dictionary (in any case variation), the
      extractor must include a HubSpotSignal of the expected type.
  15. Suppression flag set for DO_NOT_CONTACT and WRONG_NUMBER signals — after
      apply_suppression() is called, the associated Lead's suppression_flag is True.

Both properties require a Flask app context because the signal extractor reads the
HubSpotSignalDictionary table and writes HubSpotSignal / Lead rows to the database.
The ``app`` fixture from conftest.py provides an in-memory SQLite database with all
tables created.
"""
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.lead import Lead
from app.models.hubspot_engagement import HubSpotEngagement
from app.models.hubspot_signal import HubSpotSignal
from app.models.hubspot_signal_dictionary import HubSpotSignalDictionary
from app.services.hubspot_signal_extractor_service import HubSpotSignalExtractorService

# ---------------------------------------------------------------------------
# Hardcoded keyword dictionary (mirrors the seed data in the Alembic migration)
# Used to generate test inputs without hitting the DB for the strategy phase.
# ---------------------------------------------------------------------------

_SIGNAL_KEYWORDS = {
    "PRIOR_WARM_CONVERSATION": [
        "interested", "wants to sell", "open to offers",
        "let's talk", "call me back", "warm lead",
    ],
    "APPOINTMENT_OCCURRED": [
        "appointment", "meeting", "showed up",
        "walked the property", "met with",
    ],
    "OFFER_PREVIOUSLY_SENT": [
        "offer sent", "sent offer", "submitted offer",
        "offer submitted", "offer letter",
    ],
    "SELLER_SAID_MAYBE_LATER": [
        "maybe later", "not right now", "call back in",
        "follow up in", "check back", "not yet",
    ],
    "SELLER_NOT_INTERESTED": [
        "not interested", "no thanks", "don't call",
        "remove me", "not selling",
    ],
    "WRONG_NUMBER": [
        "wrong number", "wrong person", "not the owner", "disconnected",
    ],
    "DO_NOT_CONTACT": [
        "do not contact", "dnc", "cease and desist",
        "stop calling", "harassment",
    ],
    "ASKING_PRICE_GIVEN": [
        "asking", "wants", "price is", "listed at", "they want",
    ],
    "PRIOR_INTERACTION_EXISTS": [
        "called", "spoke with", "left voicemail",
        "emailed", "texted", "mailed",
    ],
    "PRIOR_RESPONSE_EXISTS": [
        "responded", "replied", "called back",
        "returned call", "answered",
    ],
    "PRIOR_LEAD_SOURCE_KNOWN": [
        "from list", "from mailer", "from driving",
        "from zillow", "from mls",
    ],
}

# Signal types that trigger suppression
_SUPPRESSION_SIGNAL_TYPES = ["DO_NOT_CONTACT", "WRONG_NUMBER"]

# All signal types that use keyword matching (FOLLOW_UP_OVERDUE is excluded —
# it is determined by overdue task detection, not keyword matching)
_KEYWORD_SIGNAL_TYPES = list(_SIGNAL_KEYWORDS.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_dictionary(session) -> None:
    """Insert the default signal keyword dictionary into the test DB."""
    for signal_type, keywords in _SIGNAL_KEYWORDS.items():
        existing = HubSpotSignalDictionary.query.filter_by(
            signal_type=signal_type
        ).first()
        if existing is None:
            entry = HubSpotSignalDictionary(
                signal_type=signal_type,
                keywords=keywords,
            )
            session.add(entry)
    session.flush()


def _make_engagement(hubspot_id: str, body: str) -> HubSpotEngagement:
    """Return an unsaved HubSpotEngagement with the given body in raw_payload."""
    return HubSpotEngagement(
        hubspot_id=hubspot_id,
        engagement_type="NOTE",
        raw_payload={"metadata": {"body": body}},
    )


def _make_lead(session, street: str = None) -> Lead:
    """Create and flush a minimal Lead record, returning it.

    property_street is left None by default to avoid UNIQUE constraint
    violations across Hypothesis examples (NULL != NULL in SQL).
    """
    lead = Lead(property_street=street)
    session.add(lead)
    session.flush()
    return lead


def _apply_case_variation(keyword: str, variation: str) -> str:
    """Apply a case variation to a keyword string.

    variation must be one of: 'upper', 'lower', 'title', 'mixed'
    """
    if variation == "upper":
        return keyword.upper()
    elif variation == "lower":
        return keyword.lower()
    elif variation == "title":
        return keyword.title()
    else:  # mixed: alternate upper/lower per character
        result = []
        for i, ch in enumerate(keyword):
            result.append(ch.upper() if i % 2 == 0 else ch.lower())
        return "".join(result)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy: pick a signal type and one of its keywords
@st.composite
def signal_type_and_keyword(draw):
    """Draw a (signal_type, keyword) pair from the hardcoded dictionary."""
    signal_type = draw(st.sampled_from(_KEYWORD_SIGNAL_TYPES))
    keyword = draw(st.sampled_from(_SIGNAL_KEYWORDS[signal_type]))
    return signal_type, keyword


# Strategy: generate a case variation name
_case_variation_st = st.sampled_from(["upper", "lower", "title", "mixed"])

# Strategy: generate surrounding text (ASCII printable, no newlines)
_surrounding_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Zs"),
        whitelist_characters=" .,!?-",
    ),
    min_size=0,
    max_size=50,
)

# Strategy: generate a suppression signal type
_suppression_signal_type_st = st.sampled_from(_SUPPRESSION_SIGNAL_TYPES)


# ---------------------------------------------------------------------------
# Property 14: Signal extraction keyword match is case-insensitive
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 14: Signal extraction keyword match is case-insensitive


class TestProperty14CaseInsensitiveKeywordMatch:
    """**Validates: Requirements 16.1, 16.2**

    For any engagement body text that contains a keyword from the signal
    dictionary (in any case variation), HubSpotSignalExtractorService.extract_signals()
    must include a HubSpotSignal of the expected signal type in its output.
    """

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        signal_and_kw=signal_type_and_keyword(),
        case_variation=_case_variation_st,
        prefix=_surrounding_text_st,
        suffix=_surrounding_text_st,
    )
    def test_keyword_in_any_case_produces_signal(
        self, app, signal_and_kw, case_variation, prefix, suffix
    ):
        """extract_signals() must detect a keyword regardless of its case.

        **Validates: Requirements 16.1, 16.2**
        """
        # Feature: hubspot-crm-migration, Property 14: Signal extraction keyword match is case-insensitive
        signal_type, keyword = signal_and_kw
        cased_keyword = _apply_case_variation(keyword, case_variation)
        body = f"{prefix} {cased_keyword} {suffix}"

        with app.app_context():
            _seed_dictionary(db.session)

            lead = _make_lead(db.session)
            engagement = _make_engagement(
                hubspot_id=f"eng-p14-{signal_type[:6]}-{case_variation}",
                body=body,
            )
            db.session.add(engagement)
            db.session.flush()

            service = HubSpotSignalExtractorService()
            signals = service.extract_signals(engagement, lead_id=lead.id)

            extracted_types = {s.signal_type for s in signals}
            assert signal_type in extracted_types, (
                f"Expected signal type {signal_type!r} to be extracted from body "
                f"{body!r} (keyword={keyword!r}, case_variation={case_variation!r}), "
                f"but got: {extracted_types}"
            )

            db.session.rollback()

    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        signal_and_kw=signal_type_and_keyword(),
        case_variation=_case_variation_st,
    )
    def test_keyword_only_body_produces_signal(
        self, app, signal_and_kw, case_variation
    ):
        """extract_signals() detects a keyword even when it is the entire body text.

        **Validates: Requirements 16.1, 16.2**
        """
        # Feature: hubspot-crm-migration, Property 14: Signal extraction keyword match is case-insensitive
        signal_type, keyword = signal_and_kw
        cased_keyword = _apply_case_variation(keyword, case_variation)

        with app.app_context():
            _seed_dictionary(db.session)

            lead = _make_lead(db.session)
            engagement = _make_engagement(
                hubspot_id=f"eng-p14b-{signal_type[:6]}-{case_variation}",
                body=cased_keyword,
            )
            db.session.add(engagement)
            db.session.flush()

            service = HubSpotSignalExtractorService()
            signals = service.extract_signals(engagement, lead_id=lead.id)

            extracted_types = {s.signal_type for s in signals}
            assert signal_type in extracted_types, (
                f"Expected signal type {signal_type!r} from keyword-only body "
                f"{cased_keyword!r} (case_variation={case_variation!r}), "
                f"but got: {extracted_types}"
            )

            db.session.rollback()

    def test_empty_body_produces_no_keyword_signals(self, app):
        """An empty body must not produce any keyword-based signals.

        **Validates: Requirements 16.1, 16.2**
        """
        # Feature: hubspot-crm-migration, Property 14: Signal extraction keyword match is case-insensitive
        with app.app_context():
            _seed_dictionary(db.session)

            lead = _make_lead(db.session)
            engagement = _make_engagement(
                hubspot_id="eng-p14-empty",
                body="",
            )
            db.session.add(engagement)
            db.session.flush()

            service = HubSpotSignalExtractorService()
            signals = service.extract_signals(engagement, lead_id=lead.id)

            # FOLLOW_UP_OVERDUE may appear if there's an overdue task, but
            # no keyword-based signals should be present for an empty body.
            keyword_signals = [
                s for s in signals if s.signal_type != "FOLLOW_UP_OVERDUE"
            ]
            assert keyword_signals == [], (
                f"Expected no keyword signals for empty body, got: "
                f"{[s.signal_type for s in keyword_signals]}"
            )

            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 15: Suppression flag set for DO_NOT_CONTACT and WRONG_NUMBER signals
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 15: Suppression flag set for DO_NOT_CONTACT and WRONG_NUMBER signals


class TestProperty15SuppressionFlagSet:
    """**Validates: Requirements 16.3**

    For any Lead that has a HubSpotSignal of type DO_NOT_CONTACT or WRONG_NUMBER,
    the Lead's suppression_flag must be True after apply_suppression() is called.
    """

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        suppression_type=_suppression_signal_type_st,
    )
    def test_suppression_flag_set_after_apply_suppression(
        self, app, suppression_type
    ):
        """apply_suppression() must set suppression_flag=True on the Lead.

        **Validates: Requirements 16.3**
        """
        # Feature: hubspot-crm-migration, Property 15: Suppression flag set for DO_NOT_CONTACT and WRONG_NUMBER signals
        with app.app_context():
            # Use property_street=None to avoid UNIQUE constraint violations
            # across Hypothesis examples (NULL != NULL in SQL)
            lead = _make_lead(db.session)
            assert lead.suppression_flag is False, (
                "Lead should start with suppression_flag=False"
            )

            # Create a HubSpotSignal of the suppression type pointing to this lead
            signal = HubSpotSignal(
                lead_id=lead.id,
                signal_type=suppression_type,
                source_engagement_id="eng-p15-test",
                raw_evidence=f"test evidence for {suppression_type}",
            )
            db.session.add(signal)
            db.session.flush()

            service = HubSpotSignalExtractorService()
            service.apply_suppression([signal])

            # Refresh from DB to confirm the flag was persisted
            db.session.refresh(lead)
            assert lead.suppression_flag is True, (
                f"Expected suppression_flag=True after apply_suppression() "
                f"with signal_type={suppression_type!r} on lead_id={lead.id}"
            )

            db.session.rollback()

    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        suppression_type=_suppression_signal_type_st,
        n_other_signals=st.integers(min_value=0, max_value=3),
    )
    def test_suppression_flag_set_when_mixed_with_other_signals(
        self, app, suppression_type, n_other_signals
    ):
        """apply_suppression() sets the flag even when mixed with non-suppression signals.

        **Validates: Requirements 16.3**
        """
        # Feature: hubspot-crm-migration, Property 15: Suppression flag set for DO_NOT_CONTACT and WRONG_NUMBER signals
        _non_suppression_types = [
            "PRIOR_INTERACTION_EXISTS",
            "PRIOR_RESPONSE_EXISTS",
            "PRIOR_WARM_CONVERSATION",
            "ASKING_PRICE_GIVEN",
            "APPOINTMENT_OCCURRED",
        ]

        with app.app_context():
            lead = _make_lead(db.session)

            signals = []

            # Add some non-suppression signals first
            for i in range(n_other_signals):
                other_type = _non_suppression_types[i % len(_non_suppression_types)]
                other_signal = HubSpotSignal(
                    lead_id=lead.id,
                    signal_type=other_type,
                    source_engagement_id=f"eng-p15-other-{i}",
                    raw_evidence=f"other signal {i}",
                )
                db.session.add(other_signal)
                signals.append(other_signal)

            # Add the suppression signal
            suppression_signal = HubSpotSignal(
                lead_id=lead.id,
                signal_type=suppression_type,
                source_engagement_id="eng-p15-suppression",
                raw_evidence=f"suppression evidence for {suppression_type}",
            )
            db.session.add(suppression_signal)
            signals.append(suppression_signal)
            db.session.flush()

            service = HubSpotSignalExtractorService()
            service.apply_suppression(signals)

            db.session.refresh(lead)
            assert lead.suppression_flag is True, (
                f"Expected suppression_flag=True after apply_suppression() "
                f"with {suppression_type!r} mixed with {n_other_signals} other signals"
            )

            db.session.rollback()

    def test_non_suppression_signals_do_not_set_flag(self, app):
        """apply_suppression() must NOT set suppression_flag for non-suppression signals.

        **Validates: Requirements 16.3**
        """
        # Feature: hubspot-crm-migration, Property 15: Suppression flag set for DO_NOT_CONTACT and WRONG_NUMBER signals
        _non_suppression_types = [
            "PRIOR_INTERACTION_EXISTS",
            "PRIOR_RESPONSE_EXISTS",
            "PRIOR_WARM_CONVERSATION",
            "ASKING_PRICE_GIVEN",
            "APPOINTMENT_OCCURRED",
            "OFFER_PREVIOUSLY_SENT",
            "SELLER_SAID_MAYBE_LATER",
            "SELLER_NOT_INTERESTED",
            "PRIOR_LEAD_SOURCE_KNOWN",
        ]

        with app.app_context():
            lead = _make_lead(db.session)

            signals = []
            for i, signal_type in enumerate(_non_suppression_types):
                signal = HubSpotSignal(
                    lead_id=lead.id,
                    signal_type=signal_type,
                    source_engagement_id=f"eng-p15-nonsup-{i}",
                    raw_evidence=f"non-suppression evidence {i}",
                )
                db.session.add(signal)
                signals.append(signal)
            db.session.flush()

            service = HubSpotSignalExtractorService()
            service.apply_suppression(signals)

            db.session.refresh(lead)
            assert lead.suppression_flag is False, (
                f"Expected suppression_flag=False after apply_suppression() "
                f"with only non-suppression signals, but got True"
            )

            db.session.rollback()

    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        suppression_type=_suppression_signal_type_st,
        n_leads=st.integers(min_value=2, max_value=4),
    )
    def test_suppression_only_affects_leads_with_suppression_signals(
        self, app, suppression_type, n_leads
    ):
        """apply_suppression() only sets the flag on leads that have suppression signals.

        **Validates: Requirements 16.3**
        """
        # Feature: hubspot-crm-migration, Property 15: Suppression flag set for DO_NOT_CONTACT and WRONG_NUMBER signals
        with app.app_context():
            # Create multiple leads (all with property_street=None to avoid
            # UNIQUE constraint violations across Hypothesis examples)
            leads = []
            for i in range(n_leads):
                lead = Lead(property_street=None)
                db.session.add(lead)
                leads.append(lead)
            db.session.flush()

            # Only give the first lead a suppression signal
            suppression_signal = HubSpotSignal(
                lead_id=leads[0].id,
                signal_type=suppression_type,
                source_engagement_id="eng-p15-isolation",
                raw_evidence="isolation test",
            )
            db.session.add(suppression_signal)
            db.session.flush()

            service = HubSpotSignalExtractorService()
            service.apply_suppression([suppression_signal])

            # First lead should be suppressed
            db.session.refresh(leads[0])
            assert leads[0].suppression_flag is True, (
                f"Lead 0 should have suppression_flag=True"
            )

            # All other leads should remain unsuppressed
            for i in range(1, n_leads):
                db.session.refresh(leads[i])
                assert leads[i].suppression_flag is False, (
                    f"Lead {i} should have suppression_flag=False "
                    f"(no suppression signal was applied to it)"
                )

            db.session.rollback()
