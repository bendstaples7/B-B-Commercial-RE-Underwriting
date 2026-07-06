"""Unit tests for expanded data source scoring dimensions.

Tests the 4 new scoring factors added to DeterministicScoringEngine:
- contactability (0-20): from skip tracer / contact completeness
- property_equity (0-25): estimated equity from property records
- ownership_duration (0-15): how long the owner has held the property
- engagement (0-10): lead engagement with outreach
"""
from datetime import date, timedelta
from unittest.mock import MagicMock
from app.services.deterministic_scoring_engine import (
    DeterministicScoringEngine,
    RESIDENTIAL_MAX_POINTS,
    COMMERCIAL_MAX_POINTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(**kwargs):
    """Return a minimal mock lead with all default attributes set to None/False."""
    lead = MagicMock()
    defaults = {
        "id": 1,
        "property_type": None,
        "property_city": None,
        "property_zip": None,
        "units": None,
        "mailing_address": None,
        "mailing_city": None,
        "mailing_state": None,
        "mailing_zip": None,
        "property_street": None,
        "acquisition_date": None,
        "notes": None,
        "manual_priority": None,
        "source_type": None,
        "tax_distress_data": None,
        "lead_category": "residential",
        "do_not_contact": False,
        "county_assessor_pin": None,
        "owner_first_name": None,
        "owner_last_name": None,
        "source": None,
        "data_source": None,
        "square_footage": None,
        "date_skip_traced": None,
        "phone_1": None,
        "email_1": None,
        "phone_2": None,
        "phone_3": None,
        "phone_4": None,
        "phone_5": None,
        "phone_6": None,
        "phone_7": None,
        "email_2": None,
        "email_3": None,
        "email_4": None,
        "email_5": None,
        "socials": None,
        "year_built": None,
        "lot_size": None,
        "mailer_history": None,
        "has_phone": False,
        "has_email": False,
        "follow_up_date": None,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(lead, k, v)
    return lead


# ---------------------------------------------------------------------------
# Contactability Score
# ---------------------------------------------------------------------------

class TestContactabilityScore:
    """Tests for _contactability_score — 0 to max_points (default 20)."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()
        self.max_pts = float(RESIDENTIAL_MAX_POINTS["contactability"])

    def test_no_data_scores_zero(self):
        lead = _make_lead()
        score = self.engine._contactability_score(lead)
        assert score == 0.0, f"Expected 0 for empty lead, got {score}"

    def test_skip_traced_only_scores_quarter(self):
        lead = _make_lead(date_skip_traced=date(2024, 1, 15))
        score = self.engine._contactability_score(lead)
        expected = self.max_pts / 4.0
        assert score == expected, f"Expected {expected}, got {score}"

    def test_full_contactability_scores_max(self):
        lead = _make_lead(
            date_skip_traced=date(2024, 1, 15),
            phone_1="555-0100",
            email_1="owner@example.com",
            socials="https://linkedin.com/in/owner",
        )
        score = self.engine._contactability_score(lead)
        assert score == self.max_pts, f"Expected {self.max_pts}, got {score}"

    def test_phone_email_socials_no_skip_trace(self):
        """Missing skip trace date but has all contact methods — 3/4 of max."""
        lead = _make_lead(
            phone_1="555-0100",
            email_1="owner@example.com",
            socials="@owner_handle",
        )
        score = self.engine._contactability_score(lead)
        expected = (self.max_pts / 4.0) * 3
        assert score == expected, f"Expected {expected}, got {score}"

    def test_uses_max_points_parameter(self):
        lead = _make_lead(
            date_skip_traced=date(2024, 1, 15),
            phone_1="555-0100",
            email_1="owner@example.com",
            socials="@owner",
        )
        score = self.engine._contactability_score(lead, max_points=10.0)
        assert score == 10.0, f"Expected 10.0 with custom max, got {score}"

    def test_any_phone_field_triggers_phone_segment(self):
        """phone_7 should count just as phone_1 does."""
        lead = _make_lead(phone_7="555-9999")
        score = self.engine._contactability_score(lead)
        expected = self.max_pts / 4.0
        assert score == expected, f"Expected {expected}, got {score}"


# ---------------------------------------------------------------------------
# Property Equity Score
# ---------------------------------------------------------------------------

class TestPropertyEquityScore:
    """Tests for _property_equity_score — 0 to max_points (default 25)."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()
        self.max_pts = float(RESIDENTIAL_MAX_POINTS["property_equity"])

    def test_no_data_scores_zero(self):
        lead = _make_lead()
        score = self.engine._property_equity_score(lead)
        assert score == 0.0, f"Expected 0, got {score}"

    def test_pre_1960_year_built(self):
        """Built before 1960 → 40% of max."""
        lead = _make_lead(year_built=1955)
        score = self.engine._property_equity_score(lead)
        expected = self.max_pts * 0.40
        assert score == expected, f"Expected {expected}, got {score}"

    def test_1960_to_1990_year_built(self):
        """Built between 1960-1990 → 30% of max."""
        lead = _make_lead(year_built=1975)
        score = self.engine._property_equity_score(lead)
        expected = self.max_pts * 0.30
        assert score == expected, f"Expected {expected}, got {score}"

    def test_post_1990_year_built(self):
        """Built after 1990 → 15% of max."""
        lead = _make_lead(year_built=2005)
        score = self.engine._property_equity_score(lead)
        expected = self.max_pts * 0.15
        assert score == expected, f"Expected {expected}, got {score}"

    def test_lot_size_adds_value(self):
        lead = _make_lead(lot_size=10000)
        score = self.engine._property_equity_score(lead)
        expected = self.max_pts * 0.30
        assert score == expected, f"Expected {expected}, got {score}"

    def test_square_footage_adds_value(self):
        lead = _make_lead(square_footage=1800)
        score = self.engine._property_equity_score(lead)
        expected = self.max_pts * 0.30
        assert score == expected, f"Expected {expected}, got {score}"

    def test_all_equity_sources(self):
        """Pre-1960 + lot_size + sqft = 40% + 30% + 30% = 100% of max."""
        lead = _make_lead(
            year_built=1945,
            lot_size=15000,
            square_footage=2000,
        )
        score = self.engine._property_equity_score(lead)
        assert score == self.max_pts, f"Expected {self.max_pts}, got {score}"


# ---------------------------------------------------------------------------
# Ownership Duration Score
# ---------------------------------------------------------------------------

class TestOwnershipDurationScore:
    """Tests for _ownership_duration_score — 0 to max_points (default 15)."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()
        self.max_pts = float(RESIDENTIAL_MAX_POINTS["ownership_duration"])

    def test_no_acquisition_date_scores_zero(self):
        lead = _make_lead()
        score = self.engine._ownership_duration_score(lead)
        assert score == 0.0, f"Expected 0, got {score}"

    def test_20_plus_years_scores_max(self):
        """20+ years → 100% of max."""
        twenty_years_ago = date.today() - timedelta(days=365 * 21)
        lead = _make_lead(acquisition_date=twenty_years_ago)
        score = self.engine._ownership_duration_score(lead)
        assert score == self.max_pts * 1.0, f"Expected {self.max_pts}, got {score}"

    def test_10_to_19_years_scores_eighty_percent(self):
        """10-19 years → 80% of max."""
        fifteen_years_ago = date.today() - timedelta(days=365 * 15)
        lead = _make_lead(acquisition_date=fifteen_years_ago)
        score = self.engine._ownership_duration_score(lead)
        expected = self.max_pts * 0.80
        assert score == expected, f"Expected {expected}, got {score}"

    def test_5_to_9_years_scores_fiftyfive_percent(self):
        seven_years_ago = date.today() - timedelta(days=365 * 7)
        lead = _make_lead(acquisition_date=seven_years_ago)
        score = self.engine._ownership_duration_score(lead)
        expected = self.max_pts * 0.55
        assert score == expected, f"Expected {expected}, got {score}"

    def test_2_to_4_years_scores_thirtyfive_percent(self):
        three_years_ago = date.today() - timedelta(days=365 * 3)
        lead = _make_lead(acquisition_date=three_years_ago)
        score = self.engine._ownership_duration_score(lead)
        expected = self.max_pts * 0.35
        assert score == expected, f"Expected {expected}, got {score}"

    def test_under_2_years_scores_fifteen_percent(self):
        one_year_ago = date.today() - timedelta(days=365)
        lead = _make_lead(acquisition_date=one_year_ago)
        score = self.engine._ownership_duration_score(lead)
        expected = self.max_pts * 0.15
        assert score == expected, f"Expected {expected}, got {score}"

    def test_most_recent_sale_used_when_acquisition_missing(self):
        one_year_ago = date.today() - timedelta(days=365)
        lead = _make_lead(
            acquisition_date=None,
            most_recent_sale=one_year_ago.strftime('%m/%d/%Y'),
        )
        score = self.engine._ownership_duration_score(lead)
        expected = self.max_pts * 0.15
        assert score == expected, f"Expected {expected}, got {score}"

    def test_future_acquisition_date_scores_zero(self):
        """Future dates (negative years owned) → 0."""
        future_date = date.today() + timedelta(days=365)
        lead = _make_lead(acquisition_date=future_date)
        score = self.engine._ownership_duration_score(lead)
        assert score == 0.0, f"Expected 0, got {score}"


# ---------------------------------------------------------------------------
# Engagement Score
# ---------------------------------------------------------------------------

class TestEngagementScore:
    """Tests for _engagement_score — 0 to max_points (default 10)."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()
        self.max_pts = float(RESIDENTIAL_MAX_POINTS["engagement"])

    def test_no_engagement_scores_zero(self):
        lead = _make_lead()
        score = self.engine._engagement_score(lead)
        assert score == 0.0, f"Expected 0, got {score}"

    def test_mailer_history_adds_points(self):
        lead = _make_lead(mailer_history=[{"mailing_id": 1, "sent_at": "2024-01-15"}])
        score = self.engine._engagement_score(lead)
        expected = self.max_pts * 0.30
        assert score == expected, f"Expected {expected}, got {score}"

    def test_has_phone_flag_adds_points(self):
        lead = _make_lead(has_phone=True)
        score = self.engine._engagement_score(lead)
        expected = self.max_pts * 0.25
        assert score == expected, f"Expected {expected}, got {score}"

    def test_has_email_flag_adds_points(self):
        lead = _make_lead(has_email=True)
        score = self.engine._engagement_score(lead)
        expected = self.max_pts * 0.25
        assert score == expected, f"Expected {expected}, got {score}"

    def test_follow_up_date_adds_points(self):
        lead = _make_lead(follow_up_date=date(2024, 6, 1))
        score = self.engine._engagement_score(lead)
        expected = self.max_pts * 0.20
        assert score == expected, f"Expected {expected}, got {score}"

    def test_full_engagement_scores_max(self):
        lead = _make_lead(
            mailer_history=[{"mailing_id": 1}],
            has_phone=True,
            has_email=True,
            follow_up_date=date(2024, 6, 1),
        )
        score = self.engine._engagement_score(lead)
        assert score == self.max_pts, f"Expected {self.max_pts}, got {score}"

    def test_empty_mailer_history_no_points(self):
        lead = _make_lead(mailer_history=[])
        score = self.engine._engagement_score(lead)
        assert score == 0.0, f"Expected 0 for empty mailer_history, got {score}"


# ---------------------------------------------------------------------------
# Integration: New dimensions appear in calculate_residential_score
# ---------------------------------------------------------------------------

class TestResidentialScoreIncludesNewDimensions:
    """The 4 new dimensions must appear in calculate_residential_score output."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_all_new_dimensions_present(self):
        lead = _make_lead()
        result = self.engine.calculate_residential_score(lead)
        details = result["score_details"]
        for dim in ("contactability", "property_equity", "ownership_duration", "engagement"):
            assert dim in details, f"Dimension {dim!r} missing from score_details"
            assert isinstance(details[dim], float)

    def test_fresh_lead_gets_no_extra_points(self):
        """A lead with no data scores 0 for all new dimensions."""
        lead = _make_lead()
        result = self.engine.calculate_residential_score(lead)
        assert result["score_details"]["contactability"] == 0.0
        assert result["score_details"]["property_equity"] == 0.0
        assert result["score_details"]["ownership_duration"] == 0.0
        assert result["score_details"]["engagement"] == 0.0

    def test_rich_lead_scores_high_on_new_dimensions(self):
        twenty_years_ago = date.today() - timedelta(days=365 * 21)
        lead = _make_lead(
            # contactability
            date_skip_traced=date(2024, 1, 15),
            phone_1="555-0100",
            email_1="owner@example.com",
            socials="@owner",
            # property equity
            year_built=1945,
            lot_size=15000,
            square_footage=2000,
            # ownership duration
            acquisition_date=twenty_years_ago,
            # engagement
            mailer_history=[{"mailing_id": 1}],
            has_phone=True,
            has_email=True,
            follow_up_date=date(2024, 6, 1),
        )
        result = self.engine.calculate_residential_score(lead)
        details = result["score_details"]
        # Each should be at or near max
        assert details["contactability"] == float(RESIDENTIAL_MAX_POINTS["contactability"]), \
            f"contactability: {details['contactability']}"
        assert details["property_equity"] == float(RESIDENTIAL_MAX_POINTS["property_equity"]), \
            f"property_equity: {details['property_equity']}"
        assert details["ownership_duration"] == float(RESIDENTIAL_MAX_POINTS["ownership_duration"]), \
            f"ownership_duration: {details['ownership_duration']}"
        assert details["engagement"] == float(RESIDENTIAL_MAX_POINTS["engagement"]), \
            f"engagement: {details['engagement']}"

    def test_score_version_updated(self):
        lead = _make_lead()
        result = self.engine.calculate_residential_score(lead)
        assert result["score_version"] == "unified_v1_residential"

    def test_total_score_includes_new_dimensions(self):
        """A fully-loaded lead should have a higher total with new dimensions."""
        twenty_years_ago = date.today() - timedelta(days=365 * 21)
        base_lead = _make_lead(
            property_type="single_family",
            property_city="Austin",
            property_zip="78701",
            units=2,
            mailing_address="456 Other Ave",
            property_street="123 Main St",
            notes="motivated seller",
        )
        rich_lead = _make_lead(
            property_type="single_family",
            property_city="Austin",
            property_zip="78701",
            units=2,
            mailing_address="456 Other Ave",
            property_street="123 Main St",
            notes="motivated seller",
            # New dimension data
            date_skip_traced=date(2024, 1, 15),
            phone_1="555-0100",
            email_1="owner@example.com",
            socials="@owner",
            year_built=1950,
            lot_size=10000,
            square_footage=1800,
            acquisition_date=twenty_years_ago,
            mailer_history=[{"mailing_id": 1}],
            has_phone=True,
            has_email=True,
            follow_up_date=date(2024, 6, 1),
        )
        base_result = self.engine.calculate_residential_score(base_lead)
        rich_result = self.engine.calculate_residential_score(rich_lead)
        assert rich_result["total_score"] > base_result["total_score"], (
            f"Rich lead total ({rich_result['total_score']}) should exceed base ({base_result['total_score']})"
        )


# ---------------------------------------------------------------------------
# Integration: New dimensions appear in calculate_commercial_score
# ---------------------------------------------------------------------------

class TestCommercialScoreIncludesNewDimensions:
    """The 4 new dimensions must appear in calculate_commercial_score output."""

    def setup_method(self):
        self.engine = DeterministicScoringEngine()

    def test_all_new_dimensions_present(self):
        lead = _make_lead(lead_category="commercial", condo_analysis=None)
        result = self.engine.calculate_commercial_score(lead)
        details = result["score_details"]
        for dim in ("contactability", "property_equity", "ownership_duration", "engagement"):
            assert dim in details, f"Dimension {dim!r} missing from commercial score_details"
            assert isinstance(details[dim], float)

    def test_score_version_updated(self):
        lead = _make_lead(lead_category="commercial", condo_analysis=None)
        result = self.engine.calculate_commercial_score(lead)
        assert result["score_version"] == "unified_v1_commercial"