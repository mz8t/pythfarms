#!/usr/bin/env python3
import os
import json
import signal
import sys
from web3 import Web3
from web3.exceptions import ContractLogicError
from eth_typing import HexStr
from dotenv import load_dotenv

load_dotenv()

# ── Setup & Config ───────────────────────────────────────────────────────────────
RPC_URL          = os.getenv("RPC_URL")
LP_SUGAR_ADDRESS = os.getenv("LP_SUGAR_ADDRESS")
PAGE_SIZE        = int(os.getenv("PAGE_SIZE", 200))
OUTPUT_PATH      = "data/sugar_pools.json"

# Gracefully handle Ctrl+C
def handle_sigint(sig, frame):
    print("\n🛑  Interrupted by user, exiting.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_sigint)

# ── Web3 & Contract ──────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 120}))
lp_sugar = w3.eth.contract(
    address=w3.to_checksum_address(LP_SUGAR_ADDRESS),
    abi=json.load(open("abi/LpSugar.json"))
)

# Find the “all” function’s output components so we know field names/order
fn_abi = None
for item in lp_sugar.abi:
    if item.get("name") == "all" and item.get("type") == "function":
        fn_abi = item
        break

if not fn_abi:
    print("❌ Could not find `all` in LpSugar ABI.")
    sys.exit(1)

# The “all” function returns an array of Lp structs.  
# Grab the component definitions (name/type) for each field:
components = fn_abi["outputs"][0]["components"]
field_names = [c["name"] for c in components]  # e.g. ["lp","symbol","decimals",…]
# We'll use these names to build our dict.

# ── Helper to convert Web3 return values to JSON-able Python types ───────────────
def serialize_value(val):
    """
    Convert val to a JSON-serializable Python primitive:
    - If val is HexBytes or bytes: return 0x-prefixed hex string.
    - If val is an address (string starting '0x'): leave as-is.
    - If val is int or bool: leave as-is.
    - Otherwise (e.g. string symbol), leave as-is.
    """
    # Web3 often returns HexBytes for addresses or bytes fields
    if isinstance(val, (bytes, bytearray)):
        return "0x" + val.hex()
    # Addresses are usually already strings like "0xAbC..."
    # Numeric and bool types are JSON-safe.
    return val

# ── Pagination loop ───────────────────────────────────────────────────────────────
def fetch_all_pools(limit: int):
    """
    Call lp_sugar.all(limit, offset) repeatedly until it returns empty or reverts.
    Returns a list of raw tuples (one tuple per Lp struct).
    """
    offset = 0
    all_pools = []
    while True:
        try:
            batch = lp_sugar.functions.all(limit, offset).call()
        except ContractLogicError:
            # Once offset is beyond number of pools, sugar reverts.
            break
        if not batch:
            # No more pools (empty list) → done
            break
        all_pools.extend(batch)
        offset += limit
    return all_pools

# ── Main Script ──────────────────────────────────────────────────────────────────
def main():
    os.makedirs("data", exist_ok=True)
    print("🔍 Fetching all pools via LpSugar…")

    raw_pools = fetch_all_pools(PAGE_SIZE)
    print(f"   → Retrieved {len(raw_pools)} total entries.\n")

    # Convert each raw tuple into a dict using field_names
    formatted = []
    for entry in raw_pools:
        # entry is a tuple of the same length as components
        pool_dict = {}
        for name, val in zip(field_names, entry):
            pool_dict[name] = serialize_value(val)
        formatted.append(pool_dict)

    # Sort descending by liquidity (converted to int)
    # Some ABI fields are strings for numbers; ensure we cast if needed
    def liquidity_key(o):
        liq = o.get("liquidity")
        if isinstance(liq, str) and liq.startswith("0x"):
            # unlikely, but in case liquidity is hex bytes, parse it
            return int(liq, 16)
        return int(liq)

    formatted.sort(key=liquidity_key, reverse=True)

    # Write to disk
    with open(OUTPUT_PATH, "w") as f:
        json.dump(formatted, f, indent=2)

    print(f"✅ Saved {len(formatted)} pools to {OUTPUT_PATH}\n")
    print("🏆 Top 5 pools by on-chain liquidity:")
    for p in formatted[:5]:
        print(f" • {p['symbol']}  @ {p['lp']}:  {p['liquidity']:,}")

if __name__ == "__main__":
    main()
