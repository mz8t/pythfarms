#!/usr/bin/env python3
import os
import json
import time
import datetime
from decimal import Decimal
from web3 import Web3
from web3.exceptions import ContractLogicError
from dotenv import load_dotenv

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────────
RPC_URL             = os.getenv("RPC_URL")
REWARDS_SUGAR_ADDR  = os.getenv("REWARDS_SUGAR_ADDRESS")

# Path to your enriched votable pools JSON
VOTABLE_POOLS_PATH  = "data/enriched_votable_pools.json"
OUTPUT_PATH         = "data/live_epoch_fees_usd.json"

# Manual Price‐Feed map (tokenAddress → Chainlink USD feed)
PRICE_FEEDS = {
    # Lowercase keys, e.g.:
    # "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "0xYour_USDC_USD_Feed",
    # "0xc02aaA39b223FE8D0a0e5C4F27eAD9083C756Cc2".lower(): "0xYour_ETH_USD_Feed",
    # … etc. …
}

# ── ABI snippets ──────────────────────────────────────────────────────────────────

# RewardsSugar (for reading epochsByAddress)
REWARDS_SUGAR_ABI = json.load(open("abi/RewardsSugar.json"))

# Minimal Chainlink aggregator ABI (for manual PRICE_FEEDS)
CHAINLINK_ABI = [
    {
        "inputs": [], "name": "latestRoundData", "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"}
        ],
        "stateMutability": "view", "type": "function"
    },
    {
        "inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view", "type": "function"
    }
]

# ERC20 ABI snippet (for symbol() and decimals())
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    }
]

# ── Web3 Setup ───────────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))

rewards_sugar = w3.eth.contract(
    address=w3.to_checksum_address(REWARDS_SUGAR_ADDR),
    abi=REWARDS_SUGAR_ABI
)

# ── Helpers ───────────────────────────────────────────────────────────────────────

def current_epoch_start_ts():
    """
    Returns the UNIX timestamp for the most recent Thursday 00:00 UTC.
    """
    now = datetime.datetime.utcnow()
    days_back = (now.weekday() - 3) % 7  # Thursday == 3
    thursday = now - datetime.timedelta(days=days_back)
    th_start = datetime.datetime(
        year=thursday.year,
        month=thursday.month,
        day=thursday.day,
        hour=0, minute=0, second=0, microsecond=0,
        tzinfo=datetime.timezone.utc
    )
    return int(th_start.timestamp())

# Caches to avoid repeated RPCs
_token_decimals_cache = {}
_token_symbol_cache   = {}
_price_feed_decimals_cache = {}
_price_cache                = {}

def get_token_decimals(token_addr: str) -> int:
    """
    Returns ERC20 token decimals, caching the result.
    """
    key = token_addr.lower()
    if key in _token_decimals_cache:
        return _token_decimals_cache[key]

    try:
        c = w3.eth.contract(address=w3.to_checksum_address(key), abi=ERC20_ABI)
        d = c.functions.decimals().call()
    except Exception:
        d = 18
    _token_decimals_cache[key] = d
    return d

def get_token_symbol(token_addr: str) -> str:
    """
    Returns ERC20 token symbol, caching the result. If symbol() fails, returns None.
    """
    key = token_addr.lower()
    if key in _token_symbol_cache:
        return _token_symbol_cache[key]

    try:
        c = w3.eth.contract(address=w3.to_checksum_address(key), abi=ERC20_ABI)
        s = c.functions.symbol().call()
    except Exception:
        s = None
    _token_symbol_cache[key] = s
    return s

def get_price_usd(token_addr: str) -> Decimal:
    """
    Returns latest USD price for token_addr via the manual PRICE_FEEDS map.
    If token_addr not in PRICE_FEEDS, returns None.
    """
    key = token_addr.lower()
    if key not in PRICE_FEEDS:
        return None
    if key in _price_cache:
        return _price_cache[key]

    agg_addr = PRICE_FEEDS[key]
    agg = w3.eth.contract(address=w3.to_checksum_address(agg_addr), abi=CHAINLINK_ABI)
    try:
        dec = agg.functions.decimals().call()
        _, answer, *_ = agg.functions.latestRoundData().call()
        price = Decimal(answer) / (Decimal(10) ** dec)
    except Exception:
        price = None

    _price_feed_decimals_cache[key] = dec
    _price_cache[key] = price
    return price

# ── Main: compute live fees & bribes in USD, with bribe detail ──────────────────
def main():
    if not os.path.exists(VOTABLE_POOLS_PATH):
        print(f"❌  {VOTABLE_POOLS_PATH} not found. Run your enrichment/filter steps first.")
        return

    # 1) Load enriched votable pools (each has "lp", "symbol", "token0", "token1", etc.)
    enriched = json.load(open(VOTABLE_POOLS_PATH))
    pool_info = {
        p["lp"].lower(): {
            "symbol": p.get("symbol", ""),
            "token0": p["token0"].lower(),
            "token1": p["token1"].lower()
        }
        for p in enriched
    }

    epoch_start = current_epoch_start_ts()
    print(f"ℹ️  Current epoch start: {epoch_start} ({time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(epoch_start))})")
    print(f"ℹ️  Processing {len(pool_info)} votable pools…")

    results = []
    ZERO = "0x0000000000000000000000000000000000000000"

    # 2) For each pool, fetch its “live” LpEpoch via epochsByAddress(1,0,pool)
    for pool_addr, info in pool_info.items():
        try:
            ep_arr = rewards_sugar.functions.epochsByAddress(1, 0, w3.to_checksum_address(pool_addr)).call()
        except ContractLogicError:
            continue
        if not ep_arr:
            continue

        ep = ep_arr[0]
        ts         = ep[0]   # epoch start timestamp
        bribes_arr = ep[4]   # array of (token, amount) pairs
        fees_arr   = ep[5]   # array of (token, amount) pairs

        # Initialize raw fee amounts for token0/token1
        fee0_amt = 0
        fee1_amt = 0
        fees_usd = Decimal(0)

        # 3) If ts matches this epoch, compute fees
        if ts == epoch_start:
            t0 = info["token0"]
            t1 = info["token1"]
            # a) Split raw fees into token0 vs token1
            for tok, amt in fees_arr:
                tok_l = tok.lower()
                if tok_l == t0:
                    fee0_amt = int(amt)
                elif tok_l == t1:
                    fee1_amt = int(amt)
                # else ignore other tokens (if any)

            # b) Convert each token’s fee → USD
            #    - token0
            if fee0_amt > 0:
                price0 = get_price_usd(t0)
                if price0 is not None:
                    dec0 = get_token_decimals(t0)
                    amt0 = Decimal(fee0_amt) / (Decimal(10) ** dec0)
                    fees_usd += (amt0 * price0)

            #    - token1
            if fee1_amt > 0:
                price1 = get_price_usd(t1)
                if price1 is not None:
                    dec1 = get_token_decimals(t1)
                    amt1 = Decimal(fee1_amt) / (Decimal(10) ** dec1)
                    fees_usd += (amt1 * price1)

        # 4) Compute detailed bribe info
        bribes_usd = Decimal(0)
        bribe_list = []
        if ts == epoch_start:
            for tok, amt in bribes_arr:
                tok_l = tok.lower()
                if tok_l == ZERO:
                    continue
                # a) Raw on-chain amount:
                raw_amt = int(amt)
                # b) Human token amount:
                dec_b = get_token_decimals(tok_l)
                human_amt = Decimal(raw_amt) / (Decimal(10) ** dec_b)
                # c) Symbol:
                sym_b = get_token_symbol(tok_l) or tok_l[:6]
                # d) USD price per token:
                price_b = get_price_usd(tok_l) or Decimal(0)
                # e) USD value:
                usd_val = (human_amt * price_b)
                bribes_usd += usd_val

                bribe_list.append({
                    "token":       tok_l,
                    "symbol":      sym_b,
                    "amount":      raw_amt,
                    "amount_token": float(human_amt),
                    "amount_usd":  float(usd_val)
                })

        total_usd = fees_usd + bribes_usd

        # 5) Collect final result
        results.append({
            "pool":         pool_addr,
            "symbol":       info["symbol"],

            "fee0_amount":  fee0_amt,
            "fee1_amount":  fee1_amt,
            "fees_usd":     float(fees_usd),

            "bribes_usd":   float(bribes_usd),
            "bribes":       bribe_list,       # detailed array of bribe records

            "total_usd":    float(total_usd)
        })

    # 6) Sort descending by total_usd (fees + bribes)
    results.sort(key=lambda x: x["total_usd"], reverse=True)

    # 7) Write to disk
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"✅ Saved live epoch fees+bribes (USD) for {len(results)} pools → {OUTPUT_PATH}\n")
    print("🏆 Top 5 pools by (fees+bribes) USD:")
    for r in results[:5]:
        print(f" • {r['symbol']} @ {r['pool']}: "
              f"fee0={r['fee0_amount']:,}, fee1={r['fee1_amount']:,}, "
              f"fees_usd=${r['fees_usd']:.2f}, "
              f"bribes_usd=${r['bribes_usd']:.2f}, total=${r['total_usd']:.2f}")
        print("   bribes detail:")
        for b in r["bribes"]:
            print(f"    - {b['symbol']}: {b['amount_token']} → ${b['amount_usd']:.2f}")
        print("")

if __name__ == "__main__":
    main()
