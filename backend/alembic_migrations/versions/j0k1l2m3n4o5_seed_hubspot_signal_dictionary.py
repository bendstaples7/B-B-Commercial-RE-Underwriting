"""seed hubspot_signal_dictionary with 11 default signal keyword entries

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-05-14 00:00:00.000000

Changes:
  - Insert 11 default rows into hubspot_signal_dictionary (one per signal type).
  - Uses INSERT ... ON CONFLICT DO NOTHING so the migration is idempotent —
    safe to run multiple times or against a DB that already has the seed data.
  - downgrade() deletes all 11 rows by signal_type.

Requirements: 16.1, 16.6
"""
import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Default signal keyword dictionary entries
# ---------------------------------------------------------------------------
_SEED_ROWS = [
    {
        "signal_type": "PRIOR_WARM_CONVERSATION",
        "keywords": ["interested", "wants to sell", "open to offers",
                     "let's talk", "call me back", "warm lead"],
    },
    {
        "signal_type": "APPOINTMENT_OCCURRED",
        "keywords": ["appointment", "meeting", "showed up",
                     "walked the property", "met with"],
    },
    {
        "signal_type": "OFFER_PREVIOUSLY_SENT",
        "keywords": ["offer sent", "sent offer", "submitted offer",
                     "offer submitted", "offer letter"],
    },
    {
        "signal_type": "SELLER_SAID_MAYBE_LATER",
        "keywords": ["maybe later", "not right now", "call back in",
                     "follow up in", "check back", "not yet"],
    },
    {
        "signal_type": "SELLER_NOT_INTERESTED",
        "keywords": ["not interested", "no thanks", "don't call",
                     "remove me", "not selling"],
    },
    {
        "signal_type": "WRONG_NUMBER",
        "keywords": ["wrong number", "wrong person", "not the owner",
                     "disconnected"],
    },
    {
        "signal_type": "DO_NOT_CONTACT",
        "keywords": ["do not contact", "dnc", "cease and desist",
                     "stop calling", "harassment"],
    },
    {
        "signal_type": "ASKING_PRICE_GIVEN",
        "keywords": ["asking", "wants", "price is", "listed at", "they want"],
    },
    {
        "signal_type": "PRIOR_INTERACTION_EXISTS",
        "keywords": ["called", "spoke with", "left voicemail",
                     "emailed", "texted", "mailed"],
    },
    {
        "signal_type": "PRIOR_RESPONSE_EXISTS",
        "keywords": ["responded", "replied", "called back",
                     "returned call", "answered"],
    },
    {
        "signal_type": "PRIOR_LEAD_SOURCE_KNOWN",
        "keywords": ["from list", "from mailer", "from driving",
                     "from zillow", "from mls"],
    },
]

# Signal types used in downgrade to identify rows to remove
_SEED_SIGNAL_TYPES = [row["signal_type"] for row in _SEED_ROWS]


def upgrade():
    """Insert the 11 default signal keyword entries.

    Uses raw SQL with ON CONFLICT DO NOTHING so the migration is idempotent —
    running it twice (or against a DB that already has the rows) is safe.
    The `updated_at` column is set to the current timestamp at migration time.
    """
    conn = op.get_bind()
    now = datetime.utcnow()

    for row in _SEED_ROWS:
        conn.execute(
            sa.text(
                """
                INSERT INTO hubspot_signal_dictionary (signal_type, keywords, updated_at)
                VALUES (:signal_type, :keywords, :updated_at)
                ON CONFLICT (signal_type) DO NOTHING
                """
            ),
            {
                "signal_type": row["signal_type"],
                "keywords": json.dumps(row["keywords"]),
                "updated_at": now,
            },
        )


def downgrade():
    """Remove the 11 seeded rows from hubspot_signal_dictionary.

    Only deletes rows whose signal_type matches the seeded values, so any
    user-added entries are left untouched.
    """
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM hubspot_signal_dictionary WHERE signal_type = ANY(:types)"
        ),
        {"types": _SEED_SIGNAL_TYPES},
    )
