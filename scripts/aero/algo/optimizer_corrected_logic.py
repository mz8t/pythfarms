import os
import json
from decimal import Decimal, getcontext, ROUND_HALF_UP

# Increase precision for allocation math
getcontext().prec = 50

# Constants
TOL = Decimal("1e-12")
MAX_ITERS = 100
TOP_N = 6
TOTAL_WEIGHT_TARGET = Decimal(100) * (Decimal(10) ** 18)  # sum weights to 100e18

# Paths
DASHBOARD_PATH   = "data/aero/votes_dashboard.json"
RELAY_VOTES_PATH = "data/aero/relay_votes.json"
HUMAN_OUT_PATH   = "optimizer/aero/optimized_votes_human.json"
BOT_OUT_PATH     = "optimizer/aero/optimized_votes_bot.txt"

# Load JSON or exit if missing
def load_json(path):
    if not os.path.exists(path):
        print(f"❌  {path} not found.")
        exit(1)
    with open(path) as f:
        return json.load(f)

# Sum relay weights per pool
def build_relay_totals(relays):
    out = {}
    for r in relays:
        for v in r.get("votes", []):
            addr = v["pool"].lower()
            whr = Decimal(str(v.get("weight_hr", 0)))
            out[addr] = out.get(addr, Decimal(0)) + whr
    return out

# Equal-marginal solver: maximize sum R_i * Δ_i/(W_i+Δ_i) subject to sum Δ_i = P
def equal_marginal(RW, P):
    active = [(p, R, W) for (p, R, W) in RW if R > 0 and W >= 0]
    if not active:
        return [(p, Decimal(0)) for (p, _, _) in RW]

    def sum_delta(lam):
        s = Decimal(0)
        for _, R, W in active:
            num = R * W
            if num <= 0:
                continue
            d = (num / lam).sqrt() - W
            if d > 0:
                s += d
        return s

    # bracket λ so sum_delta(hi) < P
    lo, hi = Decimal("1e-30"), Decimal("1")
    for _ in range(200):
        if sum_delta(hi) < P:
            break
        hi *= 2
    else:
        raise RuntimeError("Could not bracket lambda")

    # binary search for λ
    for _ in range(MAX_ITERS):
        mid = (lo + hi) / 2
        s = sum_delta(mid)
        if abs(s - P) < TOL:
            lo = mid
            break
        if s > P:
            lo = mid
        else:
            hi = mid
    lam = lo

    # compute Δ_i for each pool
    out = []
    for p, R, W in RW:
        if R <= 0 or W < 0:
            out.append((p, Decimal(0)))
        else:
            d = ((R * W) / lam).sqrt() - W
            out.append((p, d if d > 0 else Decimal(0)))
    return out

# Main orchestration
if __name__ == "__main__":
    # load data
    dash = load_json(DASHBOARD_PATH)
    rels = load_json(RELAY_VOTES_PATH)
    pools = dash["pools"]

    # our total voting power and already cast votes
    P_our = Decimal(str(dash.get("our_voting_power", 0)))
    already_cast = sum(Decimal(str(p.get("our_votes", 0))) for p in pools)
    P_rem = max(P_our - already_cast, Decimal(0))

    # build baseline weights (on-chain + relay)
    relay_totals = build_relay_totals(rels)
    base = []
    locked = {}
    for p in pools:
        addr = p["pool"].lower()
        R = Decimal(str(p.get("total_usd", 0)))
        W0 = Decimal(str(p.get("weight", 0)))
        WR = relay_totals.get(addr, Decimal(0))
        Wb = W0 + WR
        locked[addr] = Wb
        base.append((addr, R, Wb))

    # allocate our remaining votes across pools
    alloc = equal_marginal(base, P_rem)
    total_alloc = sum(d for _, d in alloc)

    # prepare outputs
    human = []
    bot_lines = []
    for addr, d in alloc:
        if d <= 0:
            continue
        p = next(x for x in pools if x["pool"].lower() == addr)
        sym = p.get("symbol", "")
        pct = (d / total_alloc * Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        total_usd_dec = Decimal(str(p.get("total_usd", 0)))
        fraction = (d / (locked[addr] + d)) if (locked[addr] + d) > 0 else Decimal(0)
        exp_usd_dec = (total_usd_dec * fraction).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        exp_usd = float(exp_usd_dec)

        human.append({
            "symbol": sym,
            "pool": addr,
            "votes": float(d),
            "pct": int(pct),
            "exp_usd": exp_usd
        })
        # scale to 100e18 total
        weight_i = (d / P_rem * TOTAL_WEIGHT_TARGET).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        bot_lines.append(f"{addr} {int(weight_i)}")

    # compute total expected USD return
    total_exp_usd = sum(item['exp_usd'] for item in human)

    # sort by percentage
    human.sort(key=lambda x: x['pct'], reverse=True)

    # assemble output with total at top
    human_output = {
        "total_expected_usd": round(total_exp_usd, 2),
        "allocations": human
    }

    # write files
    os.makedirs(os.path.dirname(HUMAN_OUT_PATH), exist_ok=True)
    with open(HUMAN_OUT_PATH, "w") as f:
        json.dump(human_output, f, indent=2)
    with open(BOT_OUT_PATH, "w") as f:
        f.write("\n".join(bot_lines))

    print(f"✅  Total expected USD return: ${total_exp_usd:.2f}")
    print(f"✅  Allocated {P_rem} remaining votes via equal-marginal across pools.")
    print(f"✅  Written human output to {HUMAN_OUT_PATH}")
    print(f"✅  Written bot file to {BOT_OUT_PATH}")
