#!/usr/bin/env python3
import os
import json
from decimal import Decimal
from web3 import Web3
from dotenv import load_dotenv
import datetime

# Load environment variables
load_dotenv()

RPC_URL         = os.getenv('SHADOW_RPC_URL')
VOTER_ADDRESS   = os.getenv('SHADOW_VOTER_ADDRESS')
default_pools   = 'data/shadow/classic_api_pools.json'
LIVE_POOLS_PATH = os.getenv('LIVE_POOLS_PATH', default_pools)
VOTER_ABI_PATH  = os.getenv('VOTER_ABI_PATH', 'abi/shadow/Voter.json')

w3 = Web3(Web3.HTTPProvider(RPC_URL))
voter = w3.eth.contract(
    address=w3.to_checksum_address(VOTER_ADDRESS),
    abi=json.load(open(VOTER_ABI_PATH))
)

def from_wei(val):
    return Decimal(val) / Decimal(10**18)

def get_current_period():
    return voter.functions.getPeriod().call()

def get_total_votes_period(period: int) -> Decimal:
    raw = voter.functions.totalVotesPerPeriod(period).call()
    return from_wei(raw)

def get_pool_votes_period(pool_addr: str, period: int) -> Decimal:
    raw = voter.functions.poolTotalVotesPerPeriod(
        w3.to_checksum_address(pool_addr), period
    ).call()
    return from_wei(raw)

# Main execution
def main():
    if not RPC_URL or not VOTER_ADDRESS:
        print("❌ Please set RPC_URL and VOTER_ADDRESS in your .env file.")
        return

    if not os.path.exists(LIVE_POOLS_PATH):
        print(f"❌ {LIVE_POOLS_PATH} not found. Run the pools-fetch script first.")
        return

    with open(LIVE_POOLS_PATH) as f:
        data = json.load(f)
    pools = data.get('pools', [])
    print(f"🔍 Loaded {len(pools)} pools from {LIVE_POOLS_PATH}")

    query_period = get_current_period()
    
    # Calculate start timestamp of query_period
    seconds_per_week = 7 * 24 * 3600
    start_timestamp = query_period * seconds_per_week
    start_date = datetime.datetime.fromtimestamp(start_timestamp, tz=datetime.timezone.utc)
    date_str = start_date.strftime("%d%m%y")

    print(f"ℹ️  Querying votes for period {query_period}, starting on {start_date.strftime('%Y-%m-%d')}")

    total_votes = get_total_votes_period(query_period)
    print(f"ℹ️  Total votes for period {query_period}: {total_votes}")

    augmented = []
    for entry in pools:
        pool_id = entry.get('pool')
        pool_votes = get_pool_votes_period(pool_id, query_period)
        e = entry.copy()
        e['pool_votes_period'] = float(pool_votes)
        augmented.append(e)

    augmented.sort(key=lambda x: x.get('pool_votes_period', 0), reverse=True)

    output = {
        'period': query_period,
        'start_date': start_date.isoformat(),
        'total_votes_period': float(total_votes),
        'pools': augmented
    }

    output_path = f'data/shadow/historical/{query_period}_votes_dashboard_{date_str}.json'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"✅ Wrote votes dashboard for period {query_period} to {output_path} ({len(augmented)} pools)")

if __name__ == '__main__':
    main()