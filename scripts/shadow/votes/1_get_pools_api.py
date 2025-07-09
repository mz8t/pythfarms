#!/usr/bin/env python3
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = os.getenv(
    "SHADOW_API_URL",
    "https://api.shadow.so/mixed-pairs?tokens=False&poolData=false"
)
OUTPUT_PATH = os.getenv(
    "OUTPUT_PATH",
    "data/shadow/classic_api_pools.json"
)

def fetch_pools():
    response = requests.get(ENDPOINT)
    response.raise_for_status()
    data = response.json()
    return data.get("pairs", [])

# fallback to gauge
def is_active(pool):
    v2 = pool.get("gaugeV2") or {}
    if v2.get("isAlive", False):
        return True
    g = pool.get("gauge") or {}
    return bool(g.get("isAlive", False))

# Main execution
def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    print("🔍 Fetching pools from Shadow API…")
    pools = fetch_pools()
    print(f"   → Retrieved {len(pools)} pools total.")

    active_pools = [p for p in pools if is_active(p)]
    print(f"   → {len(active_pools)} active pools after filtering.")
    #sort
    sorted_pools = sorted(
        active_pools,
        key=lambda p: p.get("stats", {}).get("last_7d_fees", 0),
        reverse=True
    )

    output = {"pools": []}
    for p in sorted_pools:
        stats = p.get("stats", {})
        entry = {
            "pool": p.get("id"),
            "symbol": p.get("symbol"),
            "fee_last_7d_usd": stats.get("last_7d_fees", 0),
            "vol_last_7d": stats.get("last_7d_vol", 0),
            "bribes_usd": p.get("voteBribesUsd", 0)
        }
        output["pools"].append(entry)

    # Write to file
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Saved {len(output['pools'])} pools to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
