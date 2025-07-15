#!/usr/bin/env python3
import os
import json
from decimal import Decimal, getcontext, ROUND_HALF_UP
from dotenv import load_dotenv

getcontext().prec = 50

TOL = Decimal("1e-12")
MAX_ITERS = 100
TOTAL_WEIGHT_TARGET = Decimal(100) * (Decimal(10) ** 18)  # scale to 100e18 for bot outputs

# Load environment variables
load_dotenv()

NFT_SIZE = Decimal(os.getenv("NFT_SIZE", "0"))  # total voting power to allocate
DASHBOARD_PATH = os.getenv(
    "DASHBOARD_PATH", "data/shadow/votes_dashboard.json"
)
HUMAN_OUT_PATH = os.getenv(
    "HUMAN_OUT_PATH", "optimizer/shadow/optimized_votes_human.json"
)
BOT_OUT_PATH = os.getenv(
    "BOT_OUT_PATH", "optimizer/shadow/optimized_votes_bot.txt"
)


def load_json(path):
    if not os.path.exists(path):
        print(f"❌  {path} not found.")
        exit(1)
    with open(path) as f:
        return json.load(f)

# Equal-marginal solver: maximize sum_i R_i * Δ_i/(W_i+Δ_i) s.t. sum Δ_i = P
# Inputs: list of (addr, R, W), target P

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
    dash = load_json(DASHBOARD_PATH)
    pools = dash.get("pools", [])

    # Filter to top 10 pools by bribes_usd
    pools = sorted(pools, key=lambda p: p.get("bribes_usd", 0), reverse=True)[:10]

    P_our = NFT_SIZE
    print(f"ℹ️  NFT_SIZE (voting power) = {P_our}")

    # build R (only bribes_usd), W list
    base = []
    locked = {}
    for p in pools:
        addr = p["pool"].lower()
        # Only consider bribes field (fees+bribes): R = bribes_usd
        R = Decimal(str(p.get("bribes_usd", 0)))
        W = Decimal(str(p.get("pool_votes_period", 0)))
        locked[addr] = W
        base.append((addr, R, W))

    # allocate votes via equal-marginal
    alloc = equal_marginal(base, P_our)
    total_alloc = sum(d for _, d in alloc)

    human = []
    bot_lines = []
    for addr, d in alloc:
        if d <= 0:
            continue
        p = next(x for x in pools if x["pool"].lower() == addr)
        sym = p.get("symbol", "")
        pct = (d / total_alloc * Decimal(100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        Wb = locked[addr]
        # expected USD return fraction: R * d/(Wb + d)
        R = Decimal(str(p.get("bribes_usd", 0)))
        fraction = (d / (Wb + d)) if (Wb + d) > 0 else Decimal(0)
        exp_usd_dec = (R * fraction).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        exp_usd = float(exp_usd_dec)

        human.append({
            "symbol": sym,
            "pool": addr,
            "votes": float(d),
            "pct": int(pct),
            "exp_usd": exp_usd
        })
        weight_i = (d / P_our * TOTAL_WEIGHT_TARGET).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        bot_lines.append(f"{addr} {int(weight_i)}")

    # total expected USD return
    total_exp_usd = sum(item['exp_usd'] for item in human)
    human.sort(key=lambda x: x['pct'], reverse=True)

    human_output = {
        "total_expected_usd": round(total_exp_usd, 2),
        "allocations": human
    }
    os.makedirs(os.path.dirname(HUMAN_OUT_PATH), exist_ok=True)
    with open(HUMAN_OUT_PATH, "w") as f:
        json.dump(human_output, f, indent=2)
    with open(BOT_OUT_PATH, "w") as f:
        f.write("\n".join(bot_lines))

    print(f"✅ Total expected USD return: ${total_exp_usd:.2f}")
    print(f"✅ Allocated {P_our} votes via equal-marginal based solely on bribes_usd.")
    print(f"✅ Written human output to {HUMAN_OUT_PATH}")
    print(f"✅ Written bot file to {BOT_OUT_PATH}")
