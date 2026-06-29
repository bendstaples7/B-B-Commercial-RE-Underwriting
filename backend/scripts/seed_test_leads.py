"""Seed test leads into the database for scoring demo.

Creates 3 leads with varying data quality, runs the scoring engine,
and prints results so the user can verify different scores and
scoring dimensions in the dashboard.
"""
import os
import sys
from datetime import date, datetime, timedelta

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Load .env before importing app
from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, '.env'))

from app import create_app, db
from app.models.lead import Lead
from app.models.lead_score import LeadScore
from app.services.deterministic_scoring_engine import DeterministicScoringEngine

app = create_app()


def create_leads():
    """Create 3 test leads with varying data quality."""
    today = date.today()

    # ──────────────────────────────────────────────────────────────────
    # LEAD 1: "Rich" lead — all fields filled, high scoring potential
    # ──────────────────────────────────────────────────────────────────
    lead_rich = Lead(
        property_street="123 Main Street",
        property_city="Springfield",
        property_state="IL",
        property_zip="62701",
        property_type="single_family",
        bedrooms=3,
        bathrooms=2.0,
        square_footage=1800,
        lot_size=7500,
        year_built=1955,

        owner_first_name="John",
        owner_last_name="Smith",
        ownership_type="individual",
        acquisition_date=today - timedelta(days=365 * 15),  # 15 years

        phone_1="+1-555-123-4567",
        phone_2="+1-555-987-6543",
        email_1="john.smith@email.com",
        email_2="jsmith@work.com",

        mailing_address="456 Oak Avenue",
        mailing_city="Springfield",
        mailing_state="IL",
        mailing_zip="62702",

        source="public_records",
        source_type="tax_distress",
        notes="Motivated seller! Needs to sell quickly. Vacant property.",
        needs_skip_trace=False,
        date_skip_traced=today - timedelta(days=30),
        date_identified=today - timedelta(days=60),

        county_assessor_pin="14-25-301-002",
        units=1,
        zoning="R-2",
        socials="https://facebook.com/john.smith, https://linkedin.com/in/johnsmith",
        lead_category="residential",
        manual_priority=8,
        has_phone=True,
        has_email=True,
        data_completeness_score=85.0,
    )

    # ──────────────────────────────────────────────────────────────────
    # LEAD 2: "Medium" lead — some data filled, moderate scoring
    # ──────────────────────────────────────────────────────────────────
    lead_medium = Lead(
        property_street="789 Elm Street",
        property_city="Springfield",
        property_state="IL",
        property_zip="62704",
        property_type="multi_family",
        bedrooms=2,
        bathrooms=1.0,
        square_footage=1200,
        # No lot_size
        year_built=1985,

        owner_first_name="Sarah",
        owner_last_name="Johnson",
        # No ownership_type
        acquisition_date=today - timedelta(days=365 * 7),  # 7 years

        phone_1="+1-555-456-7890",
        # No email

        mailing_address="789 Elm Street",
        mailing_city="Springfield",
        mailing_state="IL",
        # No mailing_zip

        source="county_records",
        # No source_type
        notes="Property is currently rented. Owner lives out of state.",
        needs_skip_trace=True,
        # No date_skip_traced

        # No county_assessor_pin
        units=2,
        # No zoning
        # No socials
        lead_category="residential",
        # No manual_priority
        has_phone=True,
        has_email=False,
        data_completeness_score=55.0,
    )

    # ──────────────────────────────────────────────────────────────────
    # LEAD 3: "Poor" lead — minimal data, low scoring
    # ──────────────────────────────────────────────────────────────────
    lead_poor = Lead(
        property_street="555 Nowhere Lane",  # Still need a street (NOT NULL)
        property_city="Springfield",
        # No property_state
        # No property_zip
        # No property_type
        # No bedrooms, bathrooms
        # No square_footage, lot_size, year_built

        owner_first_name="Unknown",
        # No owner_last_name
        # No ownership_type
        # No acquisition_date

        # No phones
        # No emails

        # No mailing_address
        # No mailing_city, state, zip

        source="web_scrape",
        # No source_type
        # No notes
        needs_skip_trace=True,
        # No date_skip_traced

        # No county_assessor_pin
        # No units
        lead_category="residential",
        has_phone=False,
        has_email=False,
        data_completeness_score=15.0,
    )

    db.session.add_all([lead_rich, lead_medium, lead_poor])
    db.session.commit()

    print(f"Created leads:")
    print(f"  Lead 1 (Rich):   ID={lead_rich.id}   {lead_rich.property_street}")
    print(f"  Lead 2 (Medium): ID={lead_medium.id} {lead_medium.property_street}")
    print(f"  Lead 3 (Poor):   ID={lead_poor.id}   (no street address)")

    return [lead_rich, lead_medium, lead_poor]


def score_leads(leads):
    """Run the scoring engine on each lead and print results."""
    engine = DeterministicScoringEngine()

    print("\n" + "=" * 80)
    print("SCORING RESULTS")
    print("=" * 80)

    for lead in leads:
        try:
            score_record = engine.recalculate_lead_score(lead)

            print(f"\n{'─' * 80}")
            print(f"LEAD {lead.id}: {lead.property_street or '(no address)'}")
            print(f"{'─' * 80}")
            print(f"  Total Score:      {score_record.total_score:.1f}")
            print(f"  Tier:             {score_record.score_tier}")
            print(f"  Data Quality:     {score_record.data_quality_score:.1f}/100")
            print(f"  Recommended:      {score_record.recommended_action}")
            print(f"  Score Version:    {score_record.score_version}")

            print(f"\n  ── Dimension Breakdown ──")
            details = score_record.score_details
            for dim, pts in sorted(details.items(), key=lambda x: x[1], reverse=True):
                if pts > 0:
                    print(f"    {dim:35s}  {pts:5.1f} pts")

            print(f"\n  ── Top Signals ──")
            for sig in score_record.top_signals:
                print(f"    {sig['dimension']:35s}  {sig['points']:5.1f} pts")

            print(f"\n  ── Missing Data ──")
            if score_record.missing_data:
                for field in score_record.missing_data:
                    print(f"    - {field}")
            else:
                print(f"    (none)")

        except Exception as e:
            print(f"\n  ERROR scoring lead {lead.id}: {e}")
            import traceback
            traceback.print_exc()


def check_leads_in_db():
    """Verify leads exist and have scores."""
    leads = Lead.query.order_by(Lead.id.desc()).limit(3).all()
    scores = LeadScore.query.order_by(LeadScore.lead_id.desc()).limit(3).all()

    print("\n" + "=" * 80)
    print("VERIFICATION: Leads in Database")
    print("=" * 80)
    for lead in leads:
        print(f"  Lead ID={lead.id}: {lead.property_street or '(no address)'}")
        print(f"    Score: {lead.lead_score}")
        print(f"    Type:  {lead.property_type or 'N/A'}")
        print(f"    Phone: {lead.phone_1 or 'N/A'}")
        print(f"    Email: {lead.email_1 or 'N/A'}")
        print(f"    PIN:   {lead.county_assessor_pin or 'N/A'}")
        print(f"    Year:  {lead.year_built or 'N/A'}")
        print(f"    Acquired: {lead.acquisition_date or 'N/A'}")
        print(f"    Contactability dimensions:")
        print(f"      date_skip_traced={lead.date_skip_traced}")
        print(f"      phone_1={lead.phone_1}")
        print(f"      socials={'YES' if lead.socials else 'NO'}")
        print(f"      has_phone={lead.has_phone}")
        print(f"      has_email={lead.has_email}")
        print()

    print(f"\nScore records created: {len(scores)}")
    for s in scores:
        print(f"  LeadScore lead_id={s.lead_id}: total={s.total_score:.1f} tier={s.score_tier}")


if __name__ == "__main__":
    with app.app_context():
        print("Creating test leads...")
        leads = create_leads()
        score_leads(leads)
        check_leads_in_db()
        print("\n✅ Seed complete! Check http://localhost:5180/ for the dashboard.")