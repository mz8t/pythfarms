
import os
import json
from decimal import Decimal, getcontext
from web3 import Web3
from web3.exceptions import ContractLogicError
from dotenv import load_dotenv

load_dotenv()


RPC_URL              = os.getenv("RPC_URL")
RELAY_SUGAR_ADDRESS  = os.getenv("RELAY_SUGAR_ADDRESS")
RELAY_ACCOUNT        = os.getenv("RELAY_ACCOUNT")

ENRICHED_POOLS_PATH  = "data/enriched_votable_pools.json"
OUTPUT_PATH          = "data/relay_votes.json"


getcontext().prec = 28


RELAYSUGAR_ABI = json.load(open("abi/RelaySugar.json"))


if not RPC_URL or not RELAY_SUGAR_ADDRESS or not RELAY_ACCOUNT:
    print("❌  Please set RPC_URL, RELAY_SUGAR_ADDRESS, and RELAY_ACCOUNT in .env")
    exit(1)

w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))
relay_sugar = w3.eth.contract(
    address=w3.to_checksum_address(RELAY_SUGAR_ADDRESS),
    abi=RELAYSUGAR_ABI
)



def load_enriched_pools(path):
    """
    Returns a dict mapping pool_address (lowercase) → symbol (string).
    """
    if not os.path.exists(path):
        print(f"❌  {path} not found. Run your enrichment step first.")
        exit(1)
    arr = json.load(open(path))
    return { p["lp"].lower(): p.get("symbol", "") for p in arr }

def fetch_relays_for_account(account):
    """
    Calls RelaySugar.all(account) → returns an array of Relay structs.
    """
    try:
        relays = relay_sugar.functions.all(w3.to_checksum_address(account)).call()
        return relays
    except ContractLogicError as e:
        print(f"❌  Error calling RelaySugar.all({account}): {e}")
        return []
    except Exception as e:
        print(f"❌  Unexpected error fetching relays: {e}")
        return []

def parse_relay_struct(raw):
    """
    Given one raw Relay tuple, return a dict with:
      - relay_address    (string, lowercase)
      - name             (string)
      - voting_amount_hr (Decimal): raw voting_amount / 10**decimals
      - votes_arr        (list of (pool_addr, weight_raw))
    Field indices (0-based) in raw:
      0: venft_id
      1: decimals
      2: amount
      3: voting_amount
      4: used_voting_amount
      5: voted_at
      6: votes (list of [pool_addr, weight_raw])
      7: token
      8: compounded
      9: run_at
     10: manager
     11: relay (address)
     12: compounder (bool)
     13: inactive (bool)
     14: name (string)
     15: account_venfts (list)
    """
    
    decimals_raw      = raw[1]
    voting_amount_raw = raw[3]

    
    votes_arr = raw[6] if isinstance(raw[6], list) else []

    
    relay_address = raw[11]

    
    raw_name = raw[14]
    name = raw_name if isinstance(raw_name, str) else ""

    
    voting_amount_hr = Decimal(voting_amount_raw) / (Decimal(10) ** int(decimals_raw))

    return {
        "relay_address":    relay_address.lower(),
        "name":             name,
        "decimals":         int(decimals_raw),
        "voting_amount_hr": voting_amount_hr,
        "votes_arr":        votes_arr
    }

def compute_vote_percentages(votes_arr, voting_amount_hr):
    """
    votes_arr: list of (pool_addr, weight_raw), where weight_raw is in 10**18 units.
    voting_amount_hr: Decimal.
    Return a list of dicts: { pool, weight_hr, percent }.
    """
    entries = []
    if voting_amount_hr == 0:
        for (pool_addr, weight_raw) in votes_arr:
            weight_hr = Decimal(weight_raw) / (Decimal(10) ** 18)
            entries.append({
                "pool":      pool_addr.lower(),
                "weight_hr": float(weight_hr),
                "percent":   0.0
            })
        return entries

    for (pool_addr, weight_raw) in votes_arr:
        pool_l    = pool_addr.lower()
        weight_hr = Decimal(weight_raw) / (Decimal(10) ** 18)
        percent   = (weight_hr / voting_amount_hr) * Decimal(100)
        entries.append({
            "pool":      pool_l,
            "weight_hr": float(weight_hr),
            "percent":   float(percent)
        })
    return entries

def format_human_number(dec):
    """
    Format a Decimal with commas (up to 6 decimals).
    """
    s = f"{dec:,.6f}".rstrip("0").rstrip(".")
    return s



def main():
    pool_symbols = load_enriched_pools(ENRICHED_POOLS_PATH)

    relays_raw = fetch_relays_for_account(RELAY_ACCOUNT)
    print(f"ℹ️  Retrieved {len(relays_raw)} Relay entries for account {RELAY_ACCOUNT}.\n")

    parsed_relays = []
    for raw in relays_raw:
        relay = parse_relay_struct(raw)
        relay_addr       = relay["relay_address"]
        relay_name       = relay["name"]
        voting_amount_hr = relay["voting_amount_hr"]
        votes_arr        = relay["votes_arr"]

        vote_entries = compute_vote_percentages(votes_arr, voting_amount_hr)

        pools_info = []
        for v in vote_entries:
            lp = v["pool"]
            pools_info.append({
                "pool":      lp,
                "symbol":    pool_symbols.get(lp, ""),
                "weight_hr": v["weight_hr"],
                "percent":   v["percent"]
            })

        parsed_relays.append({
            "relay":          relay_addr,
            "name":           relay_name,
            "voting_amount":  float(voting_amount_hr),  
            "votes":          pools_info
        })

    
    parsed_relays.sort(key=lambda x: Decimal(str(x["voting_amount"])), reverse=True)

    
    for r in parsed_relays:
        r["voting_amount"] = format_human_number(Decimal(str(r["voting_amount"])))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(parsed_relays, f, indent=2)

    print(f"✅  Wrote relay vote breakdown (sorted) to {OUTPUT_PATH}\n")

    if parsed_relays:
        print("🏆 Top Relays by Voting Power:")
        for r in parsed_relays[:3]:
            print(f" • {r['name'] or '(no name)'} ({r['relay']}): {r['voting_amount']} votes")
            for v in r["votes"]:
                if v["percent"] > 0:
                    print(f"    – {v['symbol']} @ {v['pool']}: {v['percent']:.2f}% (weight={v['weight_hr']})")
            print("")

if __name__ == "__main__":
    main()
