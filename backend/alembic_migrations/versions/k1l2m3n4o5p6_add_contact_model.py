"""Add contact model: contacts, contact_phones, contact_emails, property_contacts tables
and migrate existing flat owner/phone/email columns from leads into the new structure.

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-05-15 00:00:00.000000

Changes:
  - Create enum types: contact_role_enum, phone_label_enum, email_label_enum,
    property_contact_role_enum
  - Create tables: contacts, contact_phones, contact_emails, property_contacts
  - Data migration: for each lead row with owner_first_name or owner_last_name,
    create Contact (role=owner), migrate phone_1–phone_7 as ContactPhone records
    (label=other, skip null/empty), migrate email_1–email_5 as ContactEmail records
    (label=other, skip null/empty), create PropertyContact with is_primary=True.
    If owner_2_first_name or owner_2_last_name is non-null, create a second Contact
    and PropertyContact with is_primary=False.
  - Idempotency guard: skip leads that already have a PropertyContact record.
  - Downgrade: drop tables in dependency order, then drop enum types.

Requirements: 8.9
"""
import logging
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')


def upgrade():
    # ------------------------------------------------------------------
    # 1. Enum types are created implicitly by the op.create_table() calls
    # below.  Each enum (contact_role_enum, phone_label_enum,
    # email_label_enum, property_contact_role_enum) is used by exactly one
    # table, so SQLAlchemy emits its CREATE TYPE exactly once before the
    # owning table.
    #
    # NOTE: do NOT create these types explicitly here.  ``create_type=False``
    # is not honoured by op.create_table() in this SQLAlchemy/Alembic version
    # (it emits the CREATE TYPE regardless), so an explicit create here — or
    # the historical ``sa.Enum(...).create(checkfirst=True)`` — produced a
    # duplicate ``CREATE TYPE`` and aborted the fresh-DB upgrade with
    # ``DuplicateObject``.  Letting create_table own the creation keeps it to
    # a single emission.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 2. Create contacts table
    # ------------------------------------------------------------------
    op.create_table(
        'contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('first_name', sa.String(128), nullable=True),
        sa.Column('last_name', sa.String(128), nullable=True),
        sa.Column(
            'role',
            sa.Enum(
                'owner', 'property_manager', 'attorney', 'family_member', 'other',
                name='contact_role_enum',
                create_type=False
            ),
            nullable=False,
            server_default='owner'
        ),
        sa.Column('role_description', sa.String(255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # ------------------------------------------------------------------
    # 3. Create contact_phones table
    # ------------------------------------------------------------------
    op.create_table(
        'contact_phones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('value', sa.String(50), nullable=False),
        sa.Column(
            'label',
            sa.Enum(
                'mobile', 'home', 'work', 'other',
                name='phone_label_enum',
                create_type=False
            ),
            nullable=False,
            server_default='other'
        ),
        sa.ForeignKeyConstraint(
            ['contact_id'], ['contacts.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        op.f('ix_contact_phones_contact_id'),
        'contact_phones',
        ['contact_id'],
        unique=False
    )

    # ------------------------------------------------------------------
    # 4. Create contact_emails table
    # ------------------------------------------------------------------
    op.create_table(
        'contact_emails',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('value', sa.String(255), nullable=False),
        sa.Column(
            'label',
            sa.Enum(
                'personal', 'work', 'other',
                name='email_label_enum',
                create_type=False
            ),
            nullable=False,
            server_default='other'
        ),
        sa.ForeignKeyConstraint(
            ['contact_id'], ['contacts.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        op.f('ix_contact_emails_contact_id'),
        'contact_emails',
        ['contact_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_contact_emails_value'),
        'contact_emails',
        ['value'],
        unique=False
    )

    # ------------------------------------------------------------------
    # 5. Create property_contacts table
    # ------------------------------------------------------------------
    op.create_table(
        'property_contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column(
            'role',
            sa.Enum(
                'owner', 'property_manager', 'attorney', 'family_member', 'other',
                name='property_contact_role_enum',
                create_type=False
            ),
            nullable=False,
            server_default='owner'
        ),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(
            ['property_id'], ['leads.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['contact_id'], ['contacts.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('property_id', 'contact_id', name='uq_property_contact')
    )
    op.create_index(
        op.f('ix_property_contacts_property_id'),
        'property_contacts',
        ['property_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_property_contacts_contact_id'),
        'property_contacts',
        ['contact_id'],
        unique=False
    )

    # ------------------------------------------------------------------
    # 6. Data migration — raw SQL via op.get_bind()
    # ------------------------------------------------------------------
    conn = op.get_bind()
    now = datetime.utcnow()

    contacts_created = 0
    phones_created = 0
    emails_created = 0
    leads_processed = 0

    # Fetch all leads that have any owner name data
    leads = conn.execute(
        sa.text(
            """
            SELECT
                id,
                owner_first_name,
                owner_last_name,
                owner_2_first_name,
                owner_2_last_name,
                phone_1, phone_2, phone_3, phone_4, phone_5, phone_6, phone_7,
                email_1, email_2, email_3, email_4, email_5
            FROM leads
            WHERE
                owner_first_name IS NOT NULL
                OR owner_last_name IS NOT NULL
                OR owner_2_first_name IS NOT NULL
                OR owner_2_last_name IS NOT NULL
            """
        )
    ).fetchall()

    for lead in leads:
        lead_id = lead[0]
        owner_first = lead[1]
        owner_last = lead[2]
        owner2_first = lead[3]
        owner2_last = lead[4]
        phones = [lead[5], lead[6], lead[7], lead[8], lead[9], lead[10], lead[11]]
        emails = [lead[12], lead[13], lead[14], lead[15], lead[16]]

        # Idempotency guard: skip if a PropertyContact already exists for this property
        existing = conn.execute(
            sa.text(
                "SELECT id FROM property_contacts WHERE property_id = :pid LIMIT 1"
            ),
            {"pid": lead_id}
        ).fetchone()

        if existing is not None:
            continue

        leads_processed += 1

        # --- Owner 1 ---
        if owner_first or owner_last:
            result = conn.execute(
                sa.text(
                    """
                    INSERT INTO contacts (first_name, last_name, role, created_at, updated_at)
                    VALUES (:first_name, :last_name, 'owner', :created_at, :updated_at)
                    RETURNING id
                    """
                ),
                {
                    "first_name": owner_first,
                    "last_name": owner_last,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            contact_id = result.fetchone()[0]
            contacts_created += 1

            # Migrate phones (phone_1 through phone_7)
            for phone_val in phones:
                if phone_val and phone_val.strip():
                    conn.execute(
                        sa.text(
                            """
                            INSERT INTO contact_phones (contact_id, value, label)
                            VALUES (:contact_id, :value, 'other')
                            """
                        ),
                        {"contact_id": contact_id, "value": phone_val.strip()}
                    )
                    phones_created += 1

            # Migrate emails (email_1 through email_5)
            for email_val in emails:
                if email_val and email_val.strip():
                    conn.execute(
                        sa.text(
                            """
                            INSERT INTO contact_emails (contact_id, value, label)
                            VALUES (:contact_id, :value, 'other')
                            """
                        ),
                        {"contact_id": contact_id, "value": email_val.strip()}
                    )
                    emails_created += 1

            # Create PropertyContact with is_primary=True
            conn.execute(
                sa.text(
                    """
                    INSERT INTO property_contacts (property_id, contact_id, role, is_primary)
                    VALUES (:property_id, :contact_id, 'owner', TRUE)
                    """
                ),
                {"property_id": lead_id, "contact_id": contact_id}
            )

        # --- Owner 2 ---
        if owner2_first or owner2_last:
            result2 = conn.execute(
                sa.text(
                    """
                    INSERT INTO contacts (first_name, last_name, role, created_at, updated_at)
                    VALUES (:first_name, :last_name, 'owner', :created_at, :updated_at)
                    RETURNING id
                    """
                ),
                {
                    "first_name": owner2_first,
                    "last_name": owner2_last,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            contact2_id = result2.fetchone()[0]
            contacts_created += 1

            # Create PropertyContact with is_primary=False
            conn.execute(
                sa.text(
                    """
                    INSERT INTO property_contacts (property_id, contact_id, role, is_primary)
                    VALUES (:property_id, :contact_id, 'owner', FALSE)
                    """
                ),
                {"property_id": lead_id, "contact_id": contact2_id}
            )

    # ------------------------------------------------------------------
    # 7. Log migration summary
    # ------------------------------------------------------------------
    logger.info(
        "Contact model migration complete: "
        "leads_processed=%d, contacts_created=%d, "
        "phones_created=%d, emails_created=%d",
        leads_processed, contacts_created, phones_created, emails_created
    )
    print(
        f"[k1l2m3n4o5p6] Migration complete: "
        f"leads_processed={leads_processed}, "
        f"contacts_created={contacts_created}, "
        f"phones_created={phones_created}, "
        f"emails_created={emails_created}"
    )


def downgrade():
    # Drop tables in dependency order (most-dependent first)
    op.drop_index(op.f('ix_property_contacts_contact_id'), table_name='property_contacts')
    op.drop_index(op.f('ix_property_contacts_property_id'), table_name='property_contacts')
    op.drop_table('property_contacts')

    op.drop_index(op.f('ix_contact_emails_value'), table_name='contact_emails')
    op.drop_index(op.f('ix_contact_emails_contact_id'), table_name='contact_emails')
    op.drop_table('contact_emails')

    op.drop_index(op.f('ix_contact_phones_contact_id'), table_name='contact_phones')
    op.drop_table('contact_phones')

    op.drop_table('contacts')

    # Drop enum types
    sa.Enum(name='property_contact_role_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='email_label_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='phone_label_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='contact_role_enum').drop(op.get_bind(), checkfirst=True)
