#!/usr/bin/env python3
import os
import json
import requests
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────────
RPC_URL               = os.getenv("RPC_URL")
ENRICHED_POOLS_PATH   = "data/enriched_votable_pools.json"
OUT_TOKEN_ID_MAPPING  = "data/token_to_id.json"

# ── Load enriched votable pools and extract unique tokens ────────────────────────
def load_tokens(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found. Run enrichment first.")
    arr = json.load(open(path))
    tokens = set()
    for p in arr:
        t0 = p.get("token0", "").lower()
        t1 = p.get("token1", "").lower()
        # Use Web3.is_address to validate, and then checksum‐normalize
        if Web3.is_address(t0):
            tokens.add(Web3.to_checksum_address(t0).lower())
        if Web3.is_address(t1):
            tokens.add(Web3.to_checksum_address(t1).lower())
    return tokens

# ── Fetch full CoinGecko coins list (with platforms) ─────────────────────────────
def fetch_all_coins_list():
    """
    Calls https://api.coingecko.com/api/v3/coins/list?include_platform=true
    Returns a list of coin entries, each with 'id', 'symbol', 'name', and 'platforms'.
    """
    url = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"
    print("ℹ️  Fetching full /coins/list?include_platform=true from Coingecko…")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()

# ── Build mapping contract_address → coingecko_id ────────────────────────────────
def build_mapping(tokens, all_coins):
    """
    For each coin in all_coins, check if coin['platforms'].get('base') is in our tokens set.
    Return dict { "0x…": "coingecko-id", … }.
    """
    mapping = {}
    missing = set(tokens)
    for coin in all_coins:
        platforms = coin.get("platforms") or {}
        base_addr = platforms.get("base")
        if base_addr:
            base_addr_lc = base_addr.lower()
            if base_addr_lc in tokens:
                mapping[base_addr_lc] = coin["id"]
                missing.discard(base_addr_lc)
    return mapping, missing

def main():
    # 1) Extract tokens from enriched pools
    tokens = load_tokens(ENRICHED_POOLS_PATH)
    print(f"ℹ️  Found {len(tokens)} unique token addresses in enriched pools.")

    # 2) Fetch full coins list from Coingecko
    coins = fetch_all_coins_list()
    print(f"ℹ️  Retrieved {len(coins)} entries from /coins/list.")

    # 3) Build mapping contract → id
    mapping, missing = build_mapping(tokens, coins)
    print(f"✅  Mapped {len(mapping)} of {len(tokens)} tokens to Coingecko IDs.")
    if missing:
        print(f"⚠️  {len(missing)} addresses had no Base entry on Coingecko. They will be omitted:")
        for i, addr in enumerate(sorted(missing), 1):
            print(f"  {i}. {addr}")
    print("")

    # 4) Write out JSON
    os.makedirs(os.path.dirname(OUT_TOKEN_ID_MAPPING), exist_ok=True)
    with open(OUT_TOKEN_ID_MAPPING, "w") as f:
        json.dump(mapping, f, indent=2)

    print(f"✅  Wrote contract→Coingecko-ID mapping to {OUT_TOKEN_ID_MAPPING}")
    print("\nYou can now use this mapping to fetch USD prices via /simple/price?ids={{…}}&vs_currencies=usd.")

if __name__ == "__main__":
    main()
