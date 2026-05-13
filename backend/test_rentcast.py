import os, json, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
import requests

api_key = os.getenv('RENTCAST_API_KEY', '')
resp = requests.get(
    "https://api.rentcast.io/v1/avm/rent/long-term",
    headers={"X-Api-Key": api_key, "Accept": "application/json"},
    params={"address": "7616 N Rogers Ave, Chicago, IL 60626", "propertyType": "Multi-Family", "bedrooms": 0, "bathrooms": 1, "squareFootage": 1170},
    timeout=15,
)
result = {"status": resp.status_code, "body": resp.json()}
with open("rentcast_result.json", "w") as f:
    json.dump(result, f, indent=2)
