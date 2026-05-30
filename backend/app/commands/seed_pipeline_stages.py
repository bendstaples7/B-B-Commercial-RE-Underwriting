"""CLI command to seed initial pipeline stage configurations for the Kanban board."""
import click
from flask.cli import with_appcontext

from app import db
from app.models.pipeline_stage_config import PipelineStageConfig


INITIAL_STAGES = [
    {"stage_name": "Lead", "order": 1, "weight": 1},
    {"stage_name": "Qualification", "order": 2, "weight": 3},
    {"stage_name": "Proposal", "order": 3, "weight": 5},
    {"stage_name": "Negotiation", "order": 4, "weight": 8},
    {"stage_name": "Closed Won", "order": 5, "weight": 10},
    {"stage_name": "Closed Lost", "order": 6, "weight": 0},
]


@click.command("seed-pipeline-stages", help="Seed initial pipeline stage configurations for Kanban.")
@with_appcontext
def seed_pipeline_stages():
    """Insert initial PipelineStageConfig rows if they don't already exist."""
    click.echo("Seeding pipeline stages...")

    created_count = 0
    for stage_data in INITIAL_STAGES:
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
            click.echo(f"  Created stage: {stage_data['stage_name']} (order={stage_data['order']}, weight={stage_data['weight']})")
        else:
            click.echo(f"  Skipped (already exists): {stage_data['stage_name']}")

    if created_count > 0:
        db.session.commit()
        click.echo(f"Seeded {created_count} pipeline stage(s).")
    else:
        click.echo("All pipeline stages already exist — nothing to seed.")