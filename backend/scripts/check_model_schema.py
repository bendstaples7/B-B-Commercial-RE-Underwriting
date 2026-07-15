"""CI/deployment entry point for the model-to-database schema contract."""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from env_loader import load_project_env

load_project_env()

from app import create_app, db
from app.services.schema_contract_service import (
    assert_model_schema_matches_database,
)


def main() -> None:
    # A drift check must never auto-apply the migrations it is meant to detect.
    os.environ["KIRO_MIGRATION"] = "1"
    app = create_app()
    with app.app_context():
        assert_model_schema_matches_database(db.engine, db.metadata)
    print("Model schema contract passed: all required tables, views, and columns exist.")


if __name__ == "__main__":
    main()
