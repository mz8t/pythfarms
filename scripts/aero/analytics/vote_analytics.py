import os
import json
import requests
from decimal import Decimal, getcontext, ROUND_HALF_UP


getcontext().prec = 28


dashboard_path = "data/aero/votes_dashboard.json"
human_alloc_path = "optimizer/aero/optimized_votes_human.json"
token_id_map_path = "data/aero/token_to_id.json"
output_path = "analytics/aero/analytics_report.json"


aero_slug = "aerodrome-finance"
simple_price_url = "https://api.coingecko.com/api/v3/simple/price"


def load_json(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found")
    with open(path) as f:
        return json.load(f)


def fetch_price(slug):
    params = {"ids": slug, "vs_currencies": "usd"}
    resp = requests.get(simple_price_url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    price = data.get(slug, {}).get("usd")
    if price is None:
        raise ValueError(f"No price for {slug}")
    return Decimal(str(price))

if __name__ == "__main__":
    
    dash = load_json(dashboard_path)
    alloc = load_json(human_alloc_path)
    token_map = load_json(token_id_map_path)

    
    our_power = Decimal(str(dash.get("our_voting_power", 0)))

    
    total_expected = Decimal(str(alloc.get("total_expected_usd", 0)))

    
    nft_amount = our_power  
    
    aero_price = fetch_price(aero_slug)
    nft_value = (aero_price * nft_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    
    
    apr = (total_expected * Decimal(52) / nft_value * Decimal(100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    
    report = {
        "our_voting_power": float(our_power),
        "aero_price_usd": float(aero_price),
        "nft_value_usd": float(nft_value),
        "total_expected_usd_per_epoch": float(total_expected),
        "forecasted_apr_percent": float(apr)
    }

    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"✅ Analytics written to {output_path}")
