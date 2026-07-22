"""CLI command to seed lead-status pipeline stage weights for Kanban + scoring."""
import click
from flask.cli import with_appcontext

from app import db
from app.models.pipeline_stage_config import PipelineStageConfig
from app.services.lead_pipeline_stages import (
    LEAD_PIPELINE_STAGES,
    LEGACY_PIPELINE_STAGE_NAMES,
)


@click.command("seed-pipeline-stages", help="Seed lead_status pipeline stage weights.")
@click.option(
    '--force',
    is_flag=True,
    default=False,
    help='Overwrite weights/order on existing stages (default: insert missing only).',
)
@with_appcontext
def seed_pipeline_stages(force: bool = False):
    """Insert (and optionally update) PipelineStageConfig rows for each lead_status."""
    click.echo("Seeding lead pipeline stages...")

    # Remove known legacy labels first so unique(order) inserts cannot collide.
    legacy_rows = PipelineStageConfig.query.filter(
        PipelineStageConfig.stage_name.in_(LEGACY_PIPELINE_STAGE_NAMES)
    ).all()
    for row in legacy_rows:
        click.echo(f"  Removed legacy stage: {row.stage_name}")
        db.session.delete(row)
    if legacy_rows:
        db.session.flush()

    created_count = 0
    updated_count = 0
    skipped_count = 0

    if force:
        # Park orders to avoid unique collisions while rewriting.
        for i, stage_data in enumerate(LEAD_PIPELINE_STAGES):
            existing = PipelineStageConfig.query.filter_by(
                stage_name=stage_data["stage_name"]
            ).first()
            if existing is not None:
                existing.order = 10_000 + i
        db.session.flush()

    for stage_data in LEAD_PIPELINE_STAGES:
        existing = PipelineStageConfig.query.filter_by(
            stage_name=stage_data["stage_name"]
        ).first()
        if existing is None:
            config = PipelineStageConfig(
                stage_name=stage_data["stage_name"],
                order=stage_data["order"],
                weight=stage_data["weight"],
            )
            db.session.add(config)
            created_count += 1
            click.echo(
                f"  Created: {stage_data['stage_name']} "
                f"(order={stage_data['order']}, weight={stage_data['weight']})"
            )
        elif force:
            existing.order = stage_data["order"]
            existing.weight = stage_data["weight"]
            updated_count += 1
            click.echo(
                f"  Updated: {stage_data['stage_name']} "
                f"(order={stage_data['order']}, weight={stage_data['weight']})"
            )
        else:
            skipped_count += 1

    db.session.commit()
    click.echo(
        f"Done — created={created_count}, updated={updated_count}, "
        f"skipped_existing={skipped_count}, removed_legacy={len(legacy_rows)}. "
        f"(Unknown/custom stages left intact.)"
    )
