#!/usr/bin/env python3
import os
import json
from decimal import Decimal, getcontext, ROUND_HALF_UP
from dotenv import load_dotenv
from web3 import Web3

# Increase precision for Decimal operations
getcontext().prec = 50

TOL = Decimal("1e-12")
MAX_ITERS = 100
TOTAL_WEIGHT_TARGET = Decimal(100) * (Decimal(10) ** 18)  # scale to 100e18 for bot outputs

# Load environment variables
dotenv_path = load_dotenv()
SHADOW_RPC_URL = os.getenv("SHADOW_RPC_URL")
SHADOW_VOTER_ADDRESS = os.getenv("SHADOW_VOTER_ADDRESS")  
VOTER_ABI_PATH = os.getenv('VOTER_ABI_PATH', 'abi/shadow/Voter.json')
ANALYTICS_PATH = os.getenv(
    "ANALYTICS_PATH", "analytics/shadow/analytics_report.json"
)
DASHBOARD_PATH = os.getenv(
    "DASHBOARD_PATH", "data/shadow/votes_dashboard.json"
)
HUMAN_OUT_PATH = os.getenv(
    "HUMAN_OUT_PATH", "optimizer/shadow/optimized_votes_human.json"
)
BOT_OUT_PATH = os.getenv(
    "BOT_OUT_PATH", "optimizer/shadow/optimized_votes_bot.txt"
)

# Load full ABI from file
try:
    with open(VOTER_ABI_PATH) as abi_file:
        VOTING_ABI = json.load(abi_file)
except Exception as e:
    print(f"❌  Failed to load ABI from {VOTER_ABI_PATH}: {e}")
    exit(1)


def load_json(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found.")
    with open(path) as f:
        return json.load(f)


def equal_marginal(RW, P):
    active = [(p, R, W) for (p, R, W) in RW if R > 0 and W >= 0]
    if not active:
        return [(p, Decimal(0)) for (p, _, _) in RW]

    def sum_delta(lam):
        total = Decimal(0)
        for _, R, W in active:
            num = R * W
            if num <= 0:
                continue
            d = (num / lam).sqrt() - W
            if d > 0:
                total += d
        return total

    lo, hi = Decimal("1e-30"), Decimal("1")
    for _ in range(200):
        if sum_delta(hi) < P:
            break
        hi *= 2
    else:
        raise RuntimeError("Could not bracket lambda for equal-marginal")

    for _ in range(MAX_ITERS):
        mid = (lo + hi) / 2
        s = sum_delta(mid)
        if abs(s - P) < TOL:
            lam = mid
            break
        if s > P:
            lo = mid
        else:
            hi = mid
    else:
        lam = lo

    out = []
    for p, R, W in RW:
        if R <= 0 or W < 0:
            out.append((p, Decimal(0)))
        else:
            d = ((R * W) / lam).sqrt() - W
            out.append((p, d if d > 0 else Decimal(0)))
    return out


def main():
    # Initialize Web3 and contract
    if not (SHADOW_RPC_URL and SHADOW_VOTER_ADDRESS):
        print("❌  RPC_URL or CONTRACT_ADDRESS not set in env.")
        exit(1)
    w3 = Web3(Web3.HTTPProvider(SHADOW_RPC_URL))
    contract = w3.eth.contract(address=Web3.to_checksum_address(SHADOW_VOTER_ADDRESS), abi=VOTING_ABI)

    # Load votes dashboard (assume it always exists per query context)
    try:
        dash = load_json(DASHBOARD_PATH)
        print(f"ℹ️  Votes dashboard loaded from {DASHBOARD_PATH}.")
    except FileNotFoundError:
        print(f"❌  Votes dashboard not found at {DASHBOARD_PATH}.")
        exit(1)

    # Attempt to load analytics report
    analytics = None
    try:
        analytics = load_json(ANALYTICS_PATH)
        print(f"ℹ️  Analytics report found at {ANALYTICS_PATH}.")
    except FileNotFoundError:
        print(f"⚠️  Analytics report not found. Optimizing with votes dashboard only.")

    owner_raw = os.getenv("SHADOW_NFT_OWNER_ADDRESS", "").lower()
    if not owner_raw:
        print("❌  SHADOW_NFT_OWNER_ADDRESS not set in env.")
        exit(1)
    owner = Web3.to_checksum_address(owner_raw)

    # Determine period to query
    if analytics and "current_votes" in analytics and "period" in analytics["current_votes"]:
        query_period = int(analytics["current_votes"]["period"])
    else:
        query_period = contract.functions.getPeriod().call() + 1
        print(f"ℹ️  Using fallback period: {query_period}")

    # Fetch voting power
    raw_power = contract.functions.userVotingPowerPerPeriod(owner, query_period).call()
    NFT_SIZE = Decimal(raw_power) / (Decimal(10) ** 18)
    print(f"ℹ️  Voting power for {owner} at period {query_period}: {NFT_SIZE}")

    # Prepare voting power and pools
    P_our = NFT_SIZE
    pools = dash.get("pools", [])
    pools = sorted(pools, key=lambda p: p.get("bribes_usd", 0), reverse=True)[:10]
    print(f"ℹ️  Allocating {P_our} votes based on bribes_usd.")

    # Initialize re-run variables
    re_run = False
    previous_votes = {}
    base = []
    locked = {}

    # Apply re-run logic only if analytics report exists
    if analytics and owner_raw and analytics.get("xshadow_holder", "").lower() == owner_raw and analytics.get("current_votes"):
        votes = analytics["current_votes"].get("votes", [])
        if votes:
            re_run = True
            for v in votes:
                pool = v["pool"].lower()
                weight = Decimal(str(v.get("weight", 0))) / (Decimal(10) ** 18)
                previous_votes[pool] = weight
            print(f"ℹ️  Re-run detected: found votes for {len(previous_votes)} pools.")
        else:
            re_run = False
            print(f"ℹ️  No previous votes found in current_votes. Treating as fresh run.")
    else:
        re_run = False
        print(f"ℹ️  Fresh run detected.")

    # Prepare optimization inputs
    for p in pools:
        addr = p["pool"].lower()
        R = Decimal(str(p.get("bribes_usd", 0)))
        W_total = Decimal(str(p.get("pool_votes_period", 0)))
        if re_run and addr in previous_votes:
            W = W_total - previous_votes[addr]
            if W < 0:
                W = Decimal(0)
        else:
            W = W_total
        locked[addr] = W_total
        base.append((addr, R, W))

    # Run optimization
    alloc = equal_marginal(base, P_our)
    total_alloc = sum(d for _, d in alloc)

    # Build outputs
    human, bot_lines = [], []
    for addr, d in alloc:
        if d <= 0:
            continue
        p = next(x for x in pools if x["pool"].lower() == addr)
        pct = (d / total_alloc * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        fraction = d / (locked[addr] + d) if (locked[addr] + d) > 0 else Decimal(0)
        exp_usd = float((Decimal(str(p.get("bribes_usd", 0))) * fraction).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        human.append({"symbol": p.get("symbol", ""), "pool": addr, "votes": float(d), "pct": int(pct), "exp_usd": exp_usd})
        weight_i = (d / P_our * TOTAL_WEIGHT_TARGET).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        bot_lines.append(f"{addr} {int(weight_i)}")

    total_exp = sum(item['exp_usd'] for item in human)
    human.sort(key=lambda x: x['pct'], reverse=True)

    # Write outputs
    out = {"total_expected_usd": round(total_exp, 2), "allocations": human, "re_run": re_run}
    os.makedirs(os.path.dirname(HUMAN_OUT_PATH), exist_ok=True)
    with open(HUMAN_OUT_PATH, 'w') as f:
        json.dump(out, f, indent=2)
    with open(BOT_OUT_PATH, 'w') as f:
        f.write("\n".join(bot_lines))

    print(f"✅ Total expected USD return: ${total_exp:.2f}")
    print(f"✅ Allocated {P_our} votes; outputs written.")

if __name__ == "__main__":
    main()