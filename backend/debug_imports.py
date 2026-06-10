"""Diagnose which import hangs in create_app."""
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv
load_dotenv()

print("=== Testing blueprint imports one by one ===")

imports_to_test = [
    "app.controllers",
    "app.controllers.property_controller",
    "app.controllers.import_controller",
    "app.controllers.enrichment_controller",
    "app.controllers.marketing_controller",
    "app.controllers.condo_filter_controller",
    "app.controllers.lead_score_controller",
    "app.controllers.multifamily_deal_controller",
    "app.controllers.multifamily_rent_roll_controller",
    "app.controllers.multifamily_market_rent_controller",
    "app.controllers.multifamily_sale_comp_controller",
    "app.controllers.multifamily_rehab_controller",
    "app.controllers.multifamily_lender_controller",
    "app.controllers.multifamily_funding_controller",
    "app.controllers.multifamily_pro_forma_controller",
    "app.controllers.multifamily_dashboard_controller",
    "app.controllers.multifamily_import_export_controller",
    "app.tasks.multifamily_recompute",
    "app.controllers.cache_controller",
    "app.controllers.om_intake_controller",
    "app.controllers.organization_controller",
    "app.controllers.interaction_controller",
    "app.controllers.task_controller",
    "app.controllers.hubspot_controller",
    "app.controllers.hubspot_webhook_controller",
    "app.controllers.contact_controller",
    "app.controllers.queue_controller",
    "app.controllers.bulk_action_controller",
    "app.controllers.command_center_controller",
    "app.controllers.pipeline_config_controller",
    "app.controllers.lead_kanban_controller",
    "app.controllers.auth_controller",
    "app.controllers.admin_controller",
    "app.controllers.ingestion_controller",
    "app.openapi",
]

for mod_name in imports_to_test:
    print(f"  Importing {mod_name}...", end=" ", flush=True)
    try:
        __import__(mod_name)
        print("OK")
    except Exception as e:
        print(f"ERROR: {e}")
