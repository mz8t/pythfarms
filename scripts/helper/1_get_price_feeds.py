#!/usr/bin/env python3
import json
import os
from web3 import Web3

# ── CONFIG ────────────────────────────────────────────────────────────────────────
# Path to your “enriched votable pools” JSON (with each entry containing token0/token1)
VOTABLE_POOLS_PATH = "data/enriched_votable_pools.json"
# Output path for the mapping template (optional)
OUT_PATH           = "data/token_to_feed_mapping.py"

# ── KNOWN BASE FEEDS (hardcoded from Chainlink’s docs) ─────────────────────────────
#
# As of June 2025, Chainlink’s Data Feeds page for Base Mainnet lists at least:
#  • ETH/USD → 0x7104…Bb70  :contentReference[oaicite:0]{index=0}
#  • USDC/USD → 0x7e86…bc6B :contentReference[oaicite:1]{index=1}
#
# (You can add more here once you find them in docs.chain.link/data‐feeds/price‐feeds/addresses – Base section.)
#
KNOWN_BASE_FEEDS = {
    # lowercase token → lowercase feed address
    "0x0000000000000000000000000000000000000000": "UNKNOWN",  # placeholder
    # [ETH] 
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee": "0x7104a37f2efb13d03f60dbec070dd834165bcb70",
    # [USDC]
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "0x7e86aaaf2b1715d485a9afa874f8d5bc6bcc0bc6",
    # …add others as needed (e.g. DAI/USD, USDT/USD, LINK/USD, etc.) once you look them up
}


def load_votable_pools(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Could not find {path}")
    with open(path, "r") as f:
        arr = json.load(f)
    return arr


def extract_unique_tokens(pools):
    """
    Scan each entry for 'token0' and 'token1' (both should be checksummed
    or lowercase 0x‐prefixed strings) and return a set of unique lowercase addresses.
    """
    tokens = set()
    for p in pools:
        t0 = p.get("token0", "").lower()
        t1 = p.get("token1", "").lower()
        if Web3.isAddress(t0):
            tokens.add(Web3.toChecksumAddress(t0).lower())
        if Web3.isAddress(t1):
            tokens.add(Web3.toChecksumAddress(t1).lower())
    return tokens


def build_feed_mapping(token_addresses):
    """
    For each token addr in token_addresses, look it up in KNOWN_BASE_FEEDS.
    If found, assign that feed; otherwise assign "UNKNOWN".
    """
    mapping = {}
    for tok in sorted(token_addresses):
        feed = KNOWN_BASE_FEEDS.get(tok, "UNKNOWN")
        mapping[tok] = feed
    return mapping


def main():
    print(f"ℹ️ Loading enriched pools from {VOTABLE_POOLS_PATH}…")
    pools = load_votable_pools(VOTABLE_POOLS_PATH)
    print(f"ℹ️ Found {len(pools)} pools. Extracting tokens…")
    tokens = extract_unique_tokens(pools)
    print(f"ℹ️ Discovered {len(tokens)} unique tokens.\n")

    mapping = build_feed_mapping(tokens)

    # Print out a Python‐literal dict you can paste into your PRICE_FEEDS = { … } block
    print(">>> Copy/paste the following into your script’s PRICE_FEEDS = {...}:\n")
    print("PRICE_FEEDS = {")
    for tok, feed in mapping.items():
        print(f'    "{tok}": "{feed}",')
    print("}\n")

    # Optionally, write out a small Python file for you to import later
    out = [
        "# Auto‐generated token→Chainlink‐feed mapping",
        "PRICE_FEEDS = {"
    ]
    for tok, feed in mapping.items():
        out.append(f'    "{tok}": "{feed}",')
    out.append("}")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write("\n".join(out))
    print(f"✅  Wrote template mapping to {OUT_PATH}")


if __name__ == "__main__":
    main()
