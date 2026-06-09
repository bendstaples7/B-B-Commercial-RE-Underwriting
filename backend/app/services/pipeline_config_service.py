from app import db
from app.models.pipeline_stage_config import PipelineStageConfig
from datetime import datetime
from typing import List, Dict, Any
from decimal import Decimal


class PipelineConfigService:
    """Service for managing PipelineStageConfig records."""

    def get_all_stages_ordered(self) -> List[PipelineStageConfig]:
        """Retrieves all PipelineStageConfig entries, ordered by 'order'."""
        return PipelineStageConfig.query.order_by(PipelineStageConfig.order).all()

    def get_stage_weight(self, stage_name: str) -> Decimal:
        """Returns the weight for a given stage_name. Defaults to 0 if not found."""
        config = PipelineStageConfig.query.filter_by(stage_name=stage_name).first()
        return config.weight if config else Decimal("0.0")

    def update_stage_weights(self, updates: List[Dict[str, Any]]) -> List[PipelineStageConfig]:
        """Updates weights for multiple stages and handles creation of new stages.

        Args:
            updates: A list of dictionaries, where each dict contains
                     'stage_name', 'weight', and optionally 'order'.

        Returns:
            List of updated/created PipelineStageConfig instances.
        """
        updated_configs = []
        for update_data in updates:
            stage_name = update_data["stage_name"]
            weight = Decimal(str(update_data["weight"]))
            order = update_data.get("order")

            config = PipelineStageConfig.query.filter_by(stage_name=stage_name).first()
            if config:
                config.weight = weight
                if order is not None: # Only update order if provided
                    config.order = order
                config.updated_at = datetime.utcnow()
            else:
                # Create new stage if not found. Requires an order.
                if order is None:
                    # Find max order and add 1, or start from 1 if no existing stages
                    max_order = db.session.query(db.func.max(PipelineStageConfig.order)).scalar()
                    order = (max_order or 0) + 1
                config = PipelineStageConfig(stage_name=stage_name, order=order, weight=weight)
                db.session.add(config)
            updated_configs.append(config)
        # Flush once after all updates to avoid unique constraint violations on order swaps
        db.session.flush()
        db.session.commit() # Commit all changes at once
        return updated_configs

    def create_stage(self, stage_name: str, order: int, weight: Decimal) -> PipelineStageConfig:
        """Creates a new pipeline stage configuration."""
        config = PipelineStageConfig(stage_name=stage_name, order=order, weight=weight)
        db.session.add(config)
        db.session.commit()
        return config

    def delete_stage(self, stage_name: str) -> bool:
        """Deletes a pipeline stage configuration."""
        config = PipelineStageConfig.query.filter_by(stage_name=stage_name).first()
        if config:
            db.session.delete(config)
            db.session.commit()
            return True
        return False

