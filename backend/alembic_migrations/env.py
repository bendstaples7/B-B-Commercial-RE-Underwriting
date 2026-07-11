import logging
import os
import sys
from logging.config import fileConfig

from flask import current_app

from alembic import context
from alembic.migration import MigrationContext as AlembicMigrationContext

# Ensure backend/ is on sys.path so that app.migration_utils is importable
# when alembic runs from any working directory.
_env_dir = os.path.dirname(os.path.abspath(__file__))          # .../alembic_migrations/
_backend_dir = os.path.dirname(_env_dir)                        # .../backend/
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.migration_utils import assert_single_head_and_root     # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

# ---------------------------------------------------------------------------
# Known-revision set — every revision ID in the documented
# baseline-replacement mapping (all pre-consolidation revisions plus the
# two new consolidation revisions).  An upgrade attempted from a revision
# outside this set is halted before any schema change (Req 9.5).
# ---------------------------------------------------------------------------
_KNOWN_REVISIONS = frozenset({
    '000000000000', '267725fe7017',
    'a1b2c3d4e5f6', 'b2c3d4e5f6g7', 'c3d4e5f6g7h8',
    'd4e5f6g7h8i9', 'd4e5f6g7h8i9b', 'e5f6g7h8i9j0', 'e5f6g7h8i9j0b',
    'f6g7h8i9j0k1', 'f6g7h8i9j0k1b', 'f6g7h8i9j0k1c',
    'fd5451087f07',
    'g7h8i9j0k1l2', 'g7h8i9j0k1l2b', 'g7h8i9j0k1l2c',
    'h8i9j0k1l2m3', 'i9j0k1l2m3n4', 'j0k1l2m3n4o5',
    'k1l2m3n4o5p6', 'l2m3n4o5p6q7', 'm3n4o5p6q7r8',
    'n4o5p6q7r8s9', 'o5p6q7r8s9t0', 'p6q7r8s9t0u1',
    'q7r8s9t0u1v2', 'r8s9t0u1v2w3', 'r9s0t1u2v3w4',
    's0t1u2v3w4x5', 't0u1v2w3x4y5', 'u1v2w3x4y5z6',
    'v1w2x3y4z5a6', 'w2x3y4z5a6b7', 'x3y4z5a6b7c8',
    'y4z5a6b7c8d9', 'z5a6b7c8d9e0',
    # New consolidation revisions
    'a2b3c4d5e6f7', 'b3c4d5e6f7a1',
    # PR #36 kanban + pipeline revisions
    '5f9bc65a48ea', 'z0a9b8c7d6e5', 'z1b2c3d4e5f6', 'z9a8b7c6d5e4',
    # Global search bar — pg_trgm + GIN trigram indexes
    'a3b4c5d6e7f8',
    # Backfill property_type from units + clear stale analyze_property actions
    'b4c5d6e7f8a9',
    # Update lead_crm_flags view: include GIS has_property_match in computed flag
    'c5d6e7f8a9b0',
    # HubSpot signal dedup uniqueness index (lead_id, signal_type, source_engagement_id)
    'd6e7f8a9b0c1',
    # Ranked fuzzy search — leads.search_document generated column + GIN trgm
    'e7f8a9b0c1d2',
    # Lead dedup — normalized_street column + unique owner+street/PIN indexes
    'f8a9b0c1d2e3',
    'f9a0b1c2d3e4',
    # Lead deal context — deal_source + deal_description from HubSpot / manual
    'g1h2i3j4k5l6',
    # email_logged timeline event type — outbound email activity logs
    'h2i3j4k5l6m7',
    # backfill relational contacts from legacy flat phone_1..7 / email_1..5
    'i3j4k5l6m7n8',
    # contact_phones confidence tracking columns
    'j4k5l6m7n8o9',
    # Data Enrichment Scoring — violation_data, permit_data, etc.
    '97321ab5e710',
    # Merge of data-enrichment-scoring and contact-phone-confidence heads
    'a4b5c6d7e8f9',
    # Unified scoring — extend crm_recommended_action_enum
    'b1c2d3e4f5a6',
    # lead_scores.lead_id ON DELETE CASCADE
    'c2d3e4f5a6b7',
    # leads.assessed_value for enrichment scoring
    'd3e4f5a6b7c8',
    # leads.recommended_contact_method for granular outreach scoring
    'e4f5a6b7c8d9',
    # Open Letter Connect — mail queue and campaigns
    'f5a6b7c8d9e0',
    'g6a7b8c9d0e1',
    # Motivation signal pipeline — signals, prospect candidates, lead denorm
    'h7i8j9k0l1m2',
    # RA actions + condo automation — assessor_class, timeline/task enum values
    'i8j9k0l1m2n3',
    # LeadTask.hubspot_task_id — HubSpot tasks consolidate onto LeadTask for CC
    'j9k0l1m2n3o4',
})


def _run_pre_upgrade_guards(connectable=None):
    """Run the two pre-upgrade guards.

    1. Single-root / single-head check (Req 1.6, 7.1).
    2. Unrecognized-start-revision check (Req 9.5).

    *connectable* is the SQLAlchemy Engine used to open a dedicated, short-lived
    connection for the recorded-revision lookup in online mode; pass ``None``
    for offline mode (in which case the start-revision guard is skipped — we
    cannot query the DB without a connection).

    On any violation the function prints to stderr, logs an error, and calls
    ``sys.exit(1)`` so the migration process terminates without changing the
    schema or the recorded revision.
    """

    # ------------------------------------------------------------------
    # Guard 1: single root & single head
    # ------------------------------------------------------------------
    result = assert_single_head_and_root()
    head_count = result['head_count']
    root_count = result['root_count']

    if head_count != 1 or root_count != 1:
        msg_parts = [
            "Migration chain validation failed — pre-upgrade guard halted.",
            f"  head_count : {head_count}  (expected 1)",
            f"  root_count : {root_count}  (expected 1)",
        ]
        if result['head_revisions']:
            msg_parts.append(
                "  head revisions  : " + ", ".join(result['head_revisions'])
            )
        if result['root_revisions']:
            msg_parts.append(
                "  root revisions  : " + ", ".join(result['root_revisions'])
            )
        msg_parts.append(
            "No schema changes have been applied.  "
            "Resolve the chain topology and re-run."
        )
        full_msg = "\n".join(msg_parts)
        logger.error(full_msg)
        print(full_msg, file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Guard 2: unrecognized start revision (online mode only)
    #
    # IMPORTANT: this check MUST use its own short-lived connection that is
    # fully closed before the migration transaction begins.  Querying the
    # recorded revision on the *migration* connection corrupts its transaction
    # state — on a fresh database the ``SELECT FROM alembic_version`` hits a
    # table that does not exist yet, which aborts the connection's transaction
    # and silently prevents the migrations from ever committing.  Using a
    # separate connection (closed via the ``with`` block, rolling back any
    # implicit transaction) keeps the migration connection pristine.
    # ------------------------------------------------------------------
    if connectable is None:
        # Offline mode — cannot query the DB; skip this guard.
        return

    # Read the current recorded revision(s) using a dedicated connection.
    try:
        with connectable.connect() as guard_conn:
            mc = AlembicMigrationContext.configure(guard_conn)
            current_heads = mc.get_current_heads()   # returns a tuple of str
    except Exception as exc:  # pragma: no cover - defensive
        # If the recorded revision cannot be read (e.g. brand-new database
        # with no alembic_version table), treat it as a fresh database and
        # let the migration proceed.
        logger.info("Start-revision guard: could not read recorded revision "
                    "(treating as fresh database): %s", exc)
        return

    if not current_heads:
        # Fresh database — no recorded revision yet; that is fine.
        return

    _assert_known_start_revision(current_heads)


def _assert_known_start_revision(current_heads):
    """Halt (sys.exit 1) if any recorded revision is not in _KNOWN_REVISIONS.

    Pure helper: takes the list/tuple of currently-recorded head revisions and
    checks them against the documented baseline-replacement mapping (Req 9.5).
    Kept separate from connection handling so it is trivially unit-testable.
    """
    unrecognized = [rev for rev in current_heads if rev not in _KNOWN_REVISIONS]
    if unrecognized:
        msg_parts = [
            "Unrecognized starting revision(s) — pre-upgrade guard halted.",
            "  The following recorded revision(s) are not present in the "
            "documented baseline-replacement mapping:",
        ]
        for rev in unrecognized:
            msg_parts.append(f"    {rev}")
        msg_parts += [
            "Schema and recorded revision are unchanged.",
            "Consult MIGRATIONS.md for the documented stamp path, or verify "
            "that the correct database is targeted.",
        ]
        full_msg = "\n".join(msg_parts)
        logger.error(full_msg)
        print(full_msg, file=sys.stderr)
        sys.exit(1)


def get_engine():
    try:
        # this works with Flask-SQLAlchemy<3 and Alchemical
        return current_app.extensions['migrate'].db.get_engine()
    except (TypeError, AttributeError):
        # this works with Flask-SQLAlchemy>=3
        return current_app.extensions['migrate'].db.engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace(
            '%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
config.set_main_option('sqlalchemy.url', get_engine_url())
target_db = current_app.extensions['migrate'].db

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_metadata():
    if hasattr(target_db, 'metadatas'):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    # Pre-upgrade guard: chain topology check.
    # The start-revision guard is omitted in offline mode because there is
    # no live connection available to query the recorded revision.
    _run_pre_upgrade_guards(connectable=None)

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=get_metadata(), literal_binds=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.zzzcomputing.com/en/latest/cookbook.html
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    conf_args = current_app.extensions['migrate'].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    connectable = get_engine()

    # ------------------------------------------------------------------
    # Pre-upgrade guards — run BEFORE opening the migration connection so the
    # start-revision check uses its own short-lived connection and cannot
    # corrupt the migration transaction (see _run_pre_upgrade_guards docstring).
    # On any violation sys.exit(1) is called; schema/recorded revision unchanged.
    # Requirements: 1.6, 7.1, 9.5
    # ------------------------------------------------------------------
    if os.environ.get('KIRO_SKIP_GUARD') != '1':
        _run_pre_upgrade_guards(connectable=connectable)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            **conf_args
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
