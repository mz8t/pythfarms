#!/usr/bin/env python3
import os
import json
from web3 import Web3
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

# ── Configuration ───────────────────────────────────────────────────────────────
RPC_URL = os.getenv("RPC_URL")
VOTABLE_POOLS_PATH = "data/votable_pools.json"
ENRICHED_POOLS_PATH = "data/enriched_votable_pools.json"

# ERC20 ABI snippet for symbol() function
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    }
]

# ── Initialize Web3 ─────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))

# ── Load votable pools ───────────────────────────────────────────────────────────
if not os.path.exists(VOTABLE_POOLS_PATH):
    print(f"Error: {VOTABLE_POOLS_PATH} not found. Run filter_votable_pools.py first.")
    exit(1)

with open(VOTABLE_POOLS_PATH) as f:
    votable_pools = json.load(f)

# ── Cache for token symbols ───────────────────────────────────────────────────────
token_symbol_cache = {}

def get_token_symbol(token_address):
    """
    Return the ERC20 token symbol at token_address, caching so we only fetch each once.
    """
    checksum_addr = w3.to_checksum_address(token_address)
    if checksum_addr in token_symbol_cache:
        return token_symbol_cache[checksum_addr]

    try:
        token_contract = w3.eth.contract(address=checksum_addr, abi=ERC20_ABI)
        symbol = token_contract.functions.symbol().call()
    except Exception:
        symbol = None

    token_symbol_cache[checksum_addr] = symbol
    return symbol

# ── Enrichment ───────────────────────────────────────────────────────────────────
enriched_pools = []
zero_addr = "0x0000000000000000000000000000000000000000"

for pool in tqdm(votable_pools, desc="Enriching pools"):
    # If the pool already has a non-empty "symbol", leave it.
    symbol = pool.get("symbol", "") or ""
    if not symbol or symbol.lower().startswith("0x"):
        # Attempt to derive symbol from token0/token1
        token0 = pool.get("token0", zero_addr)
        token1 = pool.get("token1", zero_addr)

        sym0 = get_token_symbol(token0) or token0[:6]
        sym1 = get_token_symbol(token1) or token1[:6]
        symbol = f"{sym0}/{sym1}"

    pool["symbol"] = symbol
    enriched_pools.append(pool)

# ── Save enriched pools ───────────────────────────────────────────────────────────
os.makedirs("data", exist_ok=True)
with open(ENRICHED_POOLS_PATH, "w") as f:
    json.dump(enriched_pools, f, indent=2)

print(f"✅ Saved {len(enriched_pools)} enriched votable pools to {ENRICHED_POOLS_PATH}")
print("\n🏆 Sample enriched pools:")
for p in enriched_pools[:5]:
    print(f" • {p['symbol']} @ {p['lp']} (gauge: {p['gauge']}, liq: {int(p['liquidity']):,})")
