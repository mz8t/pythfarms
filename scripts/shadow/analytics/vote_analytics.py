#!/usr/bin/env python3
import os
import json
import requests
from decimal import Decimal, getcontext, ROUND_HALF_UP
from dotenv import load_dotenv

# Increase precision for financial calculations
getcontext().prec = 28

# Load environment variables
load_dotenv()

# Paths and parameters
DASHBOARD_PATH   = os.getenv('DASHBOARD_PATH', 'data/shadow/votes_dashboard.json')
HUMAN_ALLOC_PATH = os.getenv('HUMAN_ALLOC_PATH', 'optimizer/shadow/optimized_votes_human.json')
OUTPUT_PATH      = os.getenv('OUTPUT_PATH', 'analytics/shadow/analytics_report.json')
SHADOW_SLUG      = os.getenv('SHADOW_SLUG', 'shadow-2')
SIMPLE_PRICE_URL = 'https://api.coingecko.com/api/v3/simple/price'

# Helper: load JSON or raise
def load_json(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found")
    with open(path) as f:
        return json.load(f)

# Fetch token price for any slug candidates
def fetch_price(slug_list):
    """
    Try a list of slug candidates until a valid price is returned.
    Logs the requested URL for debugging.
    """
    params = {'vs_currencies': 'usd'}
    for slug in slug_list:
        params['ids'] = slug
        # Debug: log the full request URL
        temp_resp = requests.Request('GET', SIMPLE_PRICE_URL, params=params).prepare()
        print(f"ℹ️ Requesting URL: {temp_resp.url}")
        resp = requests.get(SIMPLE_PRICE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        price = data.get(slug, {}).get('usd')
        if price is not None:
            print(f"ℹ️ Coingecko: using slug '{slug}' => ${price}")
            return Decimal(str(price))
    raise ValueError(f"No valid price found for slugs: {slug_list}")
    raise ValueError(f"No valid price found for slugs: {slug_list}")

# Load total voting power from env
NFT_SIZE = Decimal(os.getenv('NFT_SIZE', '0'))  # user-specified xShadow amount

# Main execution
def main():
    # Load dashboard and allocation data
    alloc = load_json(HUMAN_ALLOC_PATH)
    our_power = NFT_SIZE
    print(f"ℹ️ NFT_SIZE (voting power) from .env = {our_power}")
    total_expected = Decimal(str(alloc.get('total_expected_usd', 0)))
    slug_list = [s.strip() for s in SHADOW_SLUG.split(',')]
    price_usd = fetch_price(slug_list)
    token_value = (price_usd * our_power).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if token_value == 0:
        apr = Decimal('0')
    else:
        apr = (total_expected * Decimal(52) / token_value * Decimal(100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    report = {
        'our_voting_power': float(our_power),
        'token_price_usd': float(price_usd),
        'token_value_usd': float(token_value),
        'total_expected_usd_per_epoch': float(total_expected),
        'forecasted_apr_percent': float(apr)
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"✅ Analytics written to {OUTPUT_PATH}")

if __name__ == '__main__':
    main()
