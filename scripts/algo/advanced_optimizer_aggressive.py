#!/usr/bin/env python3
import os
import json
from decimal import Decimal, getcontext, ROUND_HALF_UP
from math import isclose

# ── Increase precision for decimal math ─────────────────────────────────────────
getcontext().prec = 50

# ── Configuration ────────────────────────────────────────────────────────────────
DASHBOARD_PATH = "data/votes_dashboard.json"
# Tolerance for solving lambda
TOL = Decimal("1e-12")
MAX_ITERS = 100

# How many top pools to show
TOP_N = 10

def load_dashboard(path):
    if not os.path.exists(path):
        print(f"❌  {path} not found.")
        exit(1)
    with open(path) as f:
        return json.load(f)

def compute_optimal_allocation(pools, P):
    """
    Input:
      pools = list of dicts with keys
        - pool       (address, str)
        - total_usd  (Decimal)
        - weight     (Decimal)
      P = your total voting power (Decimal)

    We solve for Δ_i >= 0 that maximize sum_i R_i * (Δ_i/(W_i+Δ_i))
    subject to sum_i Δ_i = P.  The closed‐form “equal‐marginal” system is:
      Δ_i = max( sqrt(R_i*W_i / λ) - W_i, 0 )
    and we choose λ > 0 so that sum_i Δ_i = P.

    Returns a list of tuples: (pool, Δ_i as Decimal).
    """
    # Filter out any pool with R_i = 0 (no revenue)
    active = []
    for p in pools:
        R = Decimal(str(p["total_usd"]))
        W = Decimal(str(p["weight"]))
        if R > 0 and W >= 0:
            active.append((p["pool"], R, W))
    if not active:
        # No pool with revenue → allocate nothing
        return [(p["pool"], Decimal(0)) for p in pools]

    # Define S(λ) = sum_i max( sqrt(R_i*W_i/λ) - W_i, 0 )
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

    # Bracket λ so that sum_delta(lam_lo) > P and sum_delta(lam_hi) < P
    lam_lo = Decimal("1e-30")
    lam_hi = Decimal("1")
    for _ in range(200):
        if sum_delta(lam_hi) < P:
            break
        lam_hi *= 2
    else:
        raise RuntimeError("Could not bracket λ_hi")

    # Binary search for λ
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

    # Compute final Δ_i
    allocation = []
    for p in pools:
        pool_addr = p["pool"]
        R = Decimal(str(p["total_usd"]))
        W = Decimal(str(p["weight"]))
        if R <= 0 or W < 0:
            allocation.append((pool_addr, Decimal(0)))
        else:
            Δ = ( (R * W) / lam ).sqrt() - W
            if Δ < 0:
                Δ = Decimal(0)
            allocation.append((pool_addr, Δ))

    return allocation

def main():
    data = load_dashboard(DASHBOARD_PATH)

    # 1) Extract your voting power and pools
    P = Decimal(str(data.get("our_voting_power", 0)))
    pools = data.get("pools", [])
    if P <= 0 or not pools:
        print("❌  No voting power or no pools found.")
        return

    # 2) Build list of (pool, total_usd, weight)
    pool_list = [
        {
            "pool":      p["pool"],
            "symbol":    p["symbol"],
            "total_usd": Decimal(str(p["total_usd"])),
            "weight":    Decimal(str(p["weight"]))
        }
        for p in pools
    ]

    # 3) Compute optimal Δ_i for each pool
    allocation = compute_optimal_allocation(pool_list, P)

    # 4) Convert Δ_i to percentages and format output
    total_alloc = sum(Δ for (_, Δ) in allocation)
    if total_alloc == 0:
        print("❌  Allocation is zero for all pools (maybe all R_i=0).")
        return

    # Build final output: list of { symbol, pool, Δ, percent_int }
    result = []
    for (pool_addr, Δ) in allocation:
        if Δ <= 0:
            continue
        pct_dec = (Δ / total_alloc) * Decimal(100)
        # Round to nearest integer percent
        pct_int = int(pct_dec.to_integral_value(rounding=ROUND_HALF_UP))
        # Retrieve symbol
        sym = next(p["symbol"] for p in pools if p["pool"] == pool_addr)
        result.append({
            "symbol":   sym,
            "pool":     pool_addr,
            "votes":    float(Δ),       # Δ in human units
            "percent":  pct_int         # nearest integer percent
        })

    # Sort by descending percent
    result.sort(key=lambda x: x["percent"], reverse=True)

    # 5) Print top N only
    print(f"\n🏗️  Optimizer → top {TOP_N} pools (nearest %):\n")
    for r in result[:TOP_N]:
        print(f" • {r['symbol']}: {r['percent']}%  ({r['votes']:.0f} votes)  [pool {r['pool']}]")
    print("\n✅  Done.")

if __name__ == "__main__":
    main()
