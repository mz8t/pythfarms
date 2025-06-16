#!/usr/bin/env python3
import os
import json
from decimal import Decimal, getcontext, ROUND_HALF_UP
from math import isclose
from dotenv import load_dotenv

# ── Load .env so RISK_AVERSION (and other vars) can be read ──────────────────────
load_dotenv()

# ── Increase precision for decimal math ─────────────────────────────────────────
getcontext().prec = 50

# ── Configuration ────────────────────────────────────────────────────────────────
DASHBOARD_PATH   = "data/votes_dashboard.json"
TOL              = Decimal("1e-12")
MAX_ITERS        = 100
TOP_N            = 6

# Read RISK_AVERSION (0–100) from ENV (default 0 = fully aggressive)
RISK_AVERSION = int(os.getenv("RISK_AVERSION", "0"))
if not (0 <= RISK_AVERSION <= 100):
    print("❌  RISK_AVERSION must be between 0 and 100.")
    exit(1)

# Compute θ = risk fraction
θ = Decimal(RISK_AVERSION) / Decimal(100)

def load_dashboard(path):
    if not os.path.exists(path):
        print(f"❌  {path} not found.")
        exit(1)
    with open(path) as f:
        return json.load(f)

def compute_agg_allocation(pools, P):
    """
    “Aggressive” allocation: solves
      maximize ∑ R_i * (Δ_i / (W_i + Δ_i)), ∑ Δ_i = P
    Returns list of (pool_addr, Δ_i_agg as Decimal).
    """
    # Filter only pools with R_i>0
    active = []
    for p in pools:
        R = Decimal(str(p["total_usd"]))
        W = Decimal(str(p["weight"]))
        if R > 0 and W >= 0:
            active.append((p["pool"], R, W))
    if not active:
        return [(p["pool"], Decimal(0)) for p in pools]

    def sum_delta(lam):
        s = Decimal(0)
        for (_, R, W) in active:
            num = R * W
            if num <= 0:
                continue
            Δ = (num / lam).sqrt() - W
            if Δ > 0:
                s += Δ
        return s

    # Bracket λ so that sum_delta(λ_lo) > P and sum_delta(λ_hi) < P
    lam_lo = Decimal("1e-30")
    lam_hi = Decimal("1")
    for _ in range(200):
        if sum_delta(lam_hi) < P:
            break
        lam_hi *= 2
    else:
        raise RuntimeError("Could not bracket λ_hi for aggressive allocation")

    # Binary search λ
    for _ in range(MAX_ITERS):
        lam_mid = (lam_lo + lam_hi) / 2
        S_mid = sum_delta(lam_mid)
        if abs(S_mid - P) < TOL:
            lam_lo = lam_mid
            break
        if S_mid > P:
            lam_lo = lam_mid
        else:
            lam_hi = lam_mid
    lam = lam_lo

    # Compute final Δ_i^agg
    allocation = []
    for p in pools:
        pool_addr = p["pool"]
        R = Decimal(str(p["total_usd"]))
        W = Decimal(str(p["weight"]))
        if R <= 0 or W < 0:
            allocation.append((pool_addr, Decimal(0)))
        else:
            Δ = ((R * W) / lam).sqrt() - W
            if Δ < 0:
                Δ = Decimal(0)
            allocation.append((pool_addr, Δ))
    return allocation

def compute_safe_allocation(pools, P):
    """
    “Safe” allocation: allocate in proportion to existing weight W_i.
    That is, Δ_i^safe = P * (W_i / ∑ W_j). Even if R_i=0, we still allocate proportionally.
    Returns list of (pool_addr, Δ_i_safe as Decimal).
    """
    weights = [Decimal(str(p["weight"])) for p in pools]
    total_W = sum(weights)
    if total_W <= 0:
        # If all W_i=0, just zero‐allocate
        return [(p["pool"], Decimal(0)) for p in pools]

    allocation = []
    for p in pools:
        W = Decimal(str(p["weight"]))
        Δ_safe = (P * W) / total_W if W > 0 else Decimal(0)
        allocation.append((p["pool"], Δ_safe))
    return allocation

def main():
    data = load_dashboard(DASHBOARD_PATH)

    # 1) Extract P and pools
    P = Decimal(str(data.get("our_voting_power", 0)))
    pools = data.get("pools", [])
    if P <= 0 or not pools:
        print("❌  No voting power or no pools found.")
        return

    # 2) Build simplified pool list
    pool_list = [
        {
            "pool":       p["pool"],
            "symbol":     p["symbol"],
            "total_usd":  Decimal(str(p["total_usd"])),
            "weight":     Decimal(str(p["weight"]))
        }
        for p in pools
    ]

    # 3) Aggressive and Safe allocations
    agg_alloc = compute_agg_allocation(pool_list, P)
    safe_alloc = compute_safe_allocation(pool_list, P)

    # 4) Combine: Δ_i = (1-θ)*Δ_i^agg + θ*Δ_i^safe
    combined = []
    for (pool_addr, Δ_agg), (_, Δ_safe) in zip(agg_alloc, safe_alloc):
        Δ_comb = (Decimal(1) - θ) * Δ_agg + θ * Δ_safe
        combined.append((pool_addr, Δ_comb))

    # 5) Renormalize (tiny rounding errors)
    total_comb = sum(Δ for (_, Δ) in combined)
    if total_comb == 0:
        print("❌  Combined allocation is zero for all pools.")
        return

    # 6) Build final result list: only pools with Δ>0 → get nearest‐percent
    result = []
    for (pool_addr, Δ) in combined:
        if Δ <= 0:
            continue
        frac = Δ / total_comb
        pct_dec = frac * Decimal(100)
        pct_int = int(pct_dec.to_integral_value(rounding=ROUND_HALF_UP))
        # Find symbol
        sym = next(p["symbol"] for p in pools if p["pool"] == pool_addr)
        result.append({
            "symbol":  sym,
            "pool":    pool_addr,
            "votes":   float(Δ),    # how many votes to cast
            "percent": pct_int      # integer percent of your P
        })

    # 7) Sort by percent descending and print top N
    result.sort(key=lambda x: x["percent"], reverse=True)

    print(f"\n🏗️  Optimizer (risk‐aversion={RISK_AVERSION}%) → top {TOP_N} pools:\n")
    for r in result[:TOP_N]:
        print(f" • {r['symbol']}: {r['percent']}%  ({r['votes']:.0f} votes)  [pool {r['pool']}]")
    print(f"\n✅  Done. (θ = {θ:.2f})\n")

if __name__ == "__main__":
    main()
