import click
from flask.cli import with_appcontext

from app import db
from app.models.deal import Deal
from app.services.multifamily.deal_service import DealService


@click.command(
    "recompute-deal-priority-scores", help="Recalculates priority_score for all active deals."
)
@with_appcontext
def recompute_deal_priority_scores():
    """Recalculates priority_score for all active deals."""
    click.echo("Starting recompute of deal priority scores...")
    
    deal_service = DealService()
    all_deals = Deal.query.filter(Deal.deleted_at.is_(None)).all()
    
    updated_count = 0
    for deal in all_deals:
        initial_score = deal.priority_score
        deal_service.calculate_priority_score(deal.id, deal=deal)
        # calculate_priority_score flushes, so we just check if it changed
        if deal.priority_score != initial_score:
            click.echo(f"Updated priority_score for Deal {deal.id} (Old: {initial_score}, New: {deal.priority_score})")
            updated_count += 1
    
    db.session.commit() # Commit any changes from calculate_priority_score
    click.echo(f"Finished recomputing priority scores. {updated_count} deals updated.")
