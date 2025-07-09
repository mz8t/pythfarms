
import os
import json
import time
import datetime
import requests
from decimal import Decimal
from web3 import Web3
from web3.exceptions import ContractLogicError
from dotenv import load_dotenv

load_dotenv()


RPC_URL             = os.getenv("RPC_URL")
REWARDS_SUGAR_ADDR  = os.getenv("REWARDS_SUGAR_ADDRESS")


VOTABLE_POOLS_PATH  = "data/aero/enriched_votable_pools.json"
TOKEN_ID_MAPPING    = "data/aero/token_to_id.json"
OUTPUT_PATH         = "data/aero/live_epoch_fees_usd.json"


COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_COINS_LIST_URL    = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"


REWARDS_SUGAR_ABI = json.load(open("abi/aero/RewardsSugar.json"))

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


if RPC_URL is None:
    print("❌  Please set RPC_URL in your .env")
    exit(1)

w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))
rewards_sugar = w3.eth.contract(
    address=w3.to_checksum_address(REWARDS_SUGAR_ADDR),
    abi=REWARDS_SUGAR_ABI
)



def current_epoch_start_ts():
    """
    Returns UNIX timestamp for the most recent Thursday 00:00 UTC.
    """
    now = datetime.datetime.utcnow()
    days_back = (now.weekday() - 3) % 7  
    thursday = now - datetime.timedelta(days=days_back)
    th_start = datetime.datetime(
        year=thursday.year, month=thursday.month, day=thursday.day,
        hour=0, minute=0, second=0, microsecond=0,
        tzinfo=datetime.timezone.utc
    )
    return int(th_start.timestamp())


_token_decimals_cache = {}
_token_symbol_cache   = {}
_price_cache          = {}  

def get_token_decimals(token_addr: str) -> int:
    """
    Returns token decimals, caching the result.
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
    Returns token symbol, caching the result. If fails, returns None.
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

def fetch_prices_from_coingecko(token_to_id: dict) -> dict:
    """
    Given { contract_address → coingecko_id }, fetch current USD prices via
    /simple/price?ids={comma-separated IDs}&vs_currencies=usd.
    Returns { contract_address: Decimal(price) }.
    """
    
    unique_ids = list(set(token_to_id.values()))
    prices = {}
    
    CHUNK = 80
    for i in range(0, len(unique_ids), CHUNK):
        chunk_ids = unique_ids[i:i+CHUNK]
        ids_param = ",".join(chunk_ids)
        params = {
            "ids": ids_param,
            "vs_currencies": "usd"
        }
        try:
            resp = requests.get(COINGECKO_SIMPLE_PRICE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"⚠️  Coingecko API error for ids[{ids_param}]: {e}")
            continue

        
        for coin_id, price_info in data.items():
            price = price_info.get("usd")
            if price is None:
                continue
            
            for contract, cid in token_to_id.items():
                if cid == coin_id:
                    prices[contract] = Decimal(str(price))
    return prices


def main():
    
    if not os.path.exists(VOTABLE_POOLS_PATH):
        print(f"❌  {VOTABLE_POOLS_PATH} not found. Run enrichment first.")
        return

    enriched = json.load(open(VOTABLE_POOLS_PATH))
    pool_info = {
        p["lp"].lower(): {
            "symbol": p.get("symbol", ""),
            "token0": p["token0"].lower(),
            "token1": p["token1"].lower(),
            "type":   p.get("type")    
        }
        for p in enriched
    }

    
    if not os.path.exists(TOKEN_ID_MAPPING):
        print(f"❌  {TOKEN_ID_MAPPING} not found. Run get_coingecko_token_ids.py first.")
        return
    token_to_id = json.load(open(TOKEN_ID_MAPPING))

    
    print(f"ℹ️  Fetching USD prices for {len(token_to_id)} tokens from CoinGecko…")
    contract_prices = fetch_prices_from_coingecko(token_to_id)
    print(f"✅  Retrieved prices for {len(contract_prices)} tokens.\n")

    epoch_start = current_epoch_start_ts()
    print(f"ℹ️  Current epoch start: {epoch_start} ({time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(epoch_start))})")
    print(f"ℹ️  Computing live fees/bribes for {len(pool_info)} pools…\n")

    results = []
    ZERO = "0x0000000000000000000000000000000000000000"

    
    for pool_addr, info in pool_info.items():
        try:
            ep_arr = rewards_sugar.functions.epochsByAddress(1, 0, w3.to_checksum_address(pool_addr)).call()
        except ContractLogicError:
            continue
        if not ep_arr:
            continue

        ep         = ep_arr[0]
        ts         = ep[0]
        bribes_arr = ep[4]  
        fees_arr   = ep[5]  

        
        fee0_amt = 0
        fee1_amt = 0
        fees_usd = Decimal(0)

        if ts == epoch_start:
            t0 = info["token0"]
            t1 = info["token1"]
            
            for tok, amt in fees_arr:
                tok_l = tok.lower()
                if tok_l == t0:
                    fee0_amt = int(amt)
                elif tok_l == t1:
                    fee1_amt = int(amt)

            
            if fee0_amt > 0:
                price0 = contract_prices.get(t0)
                if price0 is not None:
                    dec0 = get_token_decimals(t0)
                    amt0 = Decimal(fee0_amt) / (Decimal(10) ** dec0)
                    fees_usd += (amt0 * price0)
            
            if fee1_amt > 0:
                price1 = contract_prices.get(t1)
                if price1 is not None:
                    dec1 = get_token_decimals(t1)
                    amt1 = Decimal(fee1_amt) / (Decimal(10) ** dec1)
                    fees_usd += (amt1 * price1)

        
        bribes_usd = Decimal(0)
        bribe_list = []
        if ts == epoch_start:
            for tok, amt in bribes_arr:
                tok_l = tok.lower()
                raw_amt = int(amt)
                if raw_amt == 0 or tok_l == ZERO:
                    continue

                
                sym_b = get_token_symbol(tok_l) or tok_l[:6]
                dec_b = get_token_decimals(tok_l)
                human_amt = Decimal(raw_amt) / (Decimal(10) ** dec_b)

                
                price_b = contract_prices.get(tok_l)
                if price_b is not None:
                    amt_usd = human_amt * price_b
                    bribes_usd += amt_usd
                else:
                    amt_usd = Decimal(0)

                bribe_list.append({
                    "token":        tok_l,
                    "symbol":       sym_b,
                    "amount":       raw_amt,
                    "amount_token": float(human_amt),
                    "amount_usd":   float(amt_usd)
                })

        total_usd = fees_usd + bribes_usd

        
        results.append({
            "pool":         pool_addr,
            "symbol":       info["symbol"],
            "type":         info["type"],       

            "fee0_amount":  fee0_amt,
            "fee1_amount":  fee1_amt,
            "fees_usd":     float(fees_usd),

            "bribes_usd":   float(bribes_usd),
            "bribes":       bribe_list,

            "total_usd":    float(total_usd)
        })

    
    results.sort(key=lambda x: x["total_usd"], reverse=True)

    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"✅  Saved live epoch fees+bribes (USD) for {len(results)} pools → {OUTPUT_PATH}\n")
    print("🏆 Top 5 pools by (fees+bribes) USD:")
    for r in results[:5]:
        print(
            f" • {r['symbol']} @ {r['pool']}: "
            f"fee0={r['fee0_amount']:,}, fee1={r['fee1_amount']:,}, "
            f"fees_usd=${r['fees_usd']:.2f}, "
            f"bribes_usd=${r['bribes_usd']:.2f}, total=${r['total_usd']:.2f}"
        )
        for b in r["bribes"]:
            print(f"    - {b['symbol']}: {b['amount_token']} → ${b['amount_usd']:.2f}")
        print("")

if __name__ == "__main__":
    main()
