#!/usr/bin/env python3
import os
import json
from decimal import Decimal, getcontext, ROUND_HALF_UP
from dotenv import load_dotenv

# ── Load .env so RISK_AVERSION and AVOID_FOUNDATION can be read ─────────────────
load_dotenv()

# ── Increase precision for decimal math ─────────────────────────────────────────
getcontext().prec = 50

# ── Configuration ────────────────────────────────────────────────────────────────
DASHBOARD_PATH       = "data/votes_dashboard.json"
RELAY_VOTES_PATH     = "data/relay_votes.json"
TOL                  = Decimal("1e-12")
MAX_ITERS            = 100
TOP_N                = 20

# ── Read env vars ─────────────────────────────────────────────────────────────────
# RISK_AVERSION: 0–100 (0 = fully aggressive, 100 = fully safe)
RISK_AVERSION = int(os.getenv("RISK_AVERSION", "0"))
if not (0 <= RISK_AVERSION <= 100):
    print("❌  RISK_AVERSION must be between 0 and 100.")
    exit(1)

# AVOID_FOUNDATION: 0–100 (0 = no relay‐avoidance, 100 = maximum squared penalty)
AVOID_FOUNDATION = int(os.getenv("AVOID_FOUNDATION", "0"))
if not (0 <= AVOID_FOUNDATION <= 100):
    print("❌  AVOID_FOUNDATION must be between 0 and 100.")
    exit(1)

# θ = fraction of Aggressive vs Safe:
#    We will do: Δ_i = θ·Δ_i^agg + (1-θ)·Δ_i^safe
θ = Decimal(RISK_AVERSION) / Decimal(100)

# α = AVOID fraction
α = Decimal(AVOID_FOUNDATION) / Decimal(100)


def load_json(path):
    if not os.path.exists(path):
        print(f"❌  {path} not found.")
        exit(1)
    with open(path) as f:
        return json.load(f)


def build_relay_penalties(relay_votes, top_k=3):
    """
    Look at relay_votes (an array of { voting_amount, votes:[{pool,percent},…] }).
    👉 Sort by voting_amount descending, take top_k relays.
    👉 For each of their vote entries, accumulate `percent/100` per pool.
    👉 Clamp each pool’s sum to at most 1.0.
    Returns: { pool_addr_lowercase: relay_score_in_[0,1] }.
    """
    parsed = []
    for r in relay_votes:
        va_str = r.get("voting_amount", "0").replace(",", "")
        try:
            va = Decimal(va_str)
        except:
            va = Decimal(0)
        parsed.append((va, r["votes"]))

    # Sort by voting_amount (descending) and pick top_k
    parsed.sort(key=lambda x: x[0], reverse=True)
    top_relays = parsed[:top_k]

    penalties = {}
    for (_, votes_list) in top_relays:
        for entry in votes_list:
            pool = entry["pool"].lower()
            frac = Decimal(str(entry.get("percent", 0))) / Decimal(100)
            penalties[pool] = penalties.get(pool, Decimal(0)) + frac

    # Clamp at 1.0
    for pool in penalties:
        if penalties[pool] > 1:
            penalties[pool] = Decimal(1)
    return penalties


def compute_agg_allocation(pools, P):
    """
    “Aggressive” allocation: solve
      maximize ∑ R_i_eff * [Δ_i / (W_i_eff + Δ_i)], subject to ∑ Δ_i = P.
    Inputs:
      pools = list of dicts { pool, total_usd_eff, weight_eff } (all Decimal)
      P = total voting power (Decimal)
    Returns: list of (pool_addr, Δ_i^agg as Decimal).
    """
    active = []
    for p in pools:
        R = p["total_usd_eff"]
        W = p["weight_eff"]
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

    # Bracket λ so that sum_delta(λ_lo) > P > sum_delta(λ_hi)
    lam_lo = Decimal("1e-30")
    lam_hi = Decimal("1")
    for _ in range(200):
        if sum_delta(lam_hi) < P:
            break
        lam_hi *= 2
    else:
        raise RuntimeError("Could not bracket λ_hi for aggressive allocation")

    # Binary‐search λ until sum_delta(λ) ≈ P
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

    allocation = []
    for p in pools:
        pool_addr = p["pool"]
        R = p["total_usd_eff"]
        W = p["weight_eff"]
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
    “Safe” allocation: split P in proportion to W_i_eff.
    Returns list of (pool_addr, Δ_i^safe).
    """
    weights = [p["weight_eff"] for p in pools]
    total_W = sum(weights)
    if total_W <= 0:
        return [(p["pool"], Decimal(0)) for p in pools]

    allocation = []
    for p in pools:
        W = p["weight_eff"]
        Δ_safe = (P * W) / total_W if W > 0 else Decimal(0)
        allocation.append((p["pool"], Δ_safe))
    return allocation


def main():
    data        = load_json(DASHBOARD_PATH)
    relay_votes = load_json(RELAY_VOTES_PATH)

    # 1) Extract total voting power P and raw pool data
    P = Decimal(str(data.get("our_voting_power", 0)))
    pools_raw = data.get("pools", [])
    if P <= 0 or not pools_raw:
        print("❌  No voting power or no pools found.")
        return

    # 2) Build relay penalties from top 3 relays by voting_amount
    penalties = build_relay_penalties(relay_votes, top_k=3)

    # 3) Determine exponent = 2 * α. 
    #    If AVOID_FOUNDATION=0 → α=0 → exponent=0 → factor=1 (no penalty).
    #    If AVOID_FOUNDATION=100 → α=1 → exponent=2 → factor=(1-ρ)^2.
    exponent = Decimal(2) * α

    # 4) Build a new pool list with “effective” revenue + weight:
    pool_list = []
    for p in pools_raw:
        pool_addr = p["pool"].lower()
        sym       = p["symbol"]
        R_orig    = Decimal(str(p["total_usd"]))
        W_orig    = Decimal(str(p["weight"]))
        relay_score = penalties.get(pool_addr, Decimal(0))
        leftover = (Decimal(1) - relay_score)
        if leftover < 0:
            leftover = Decimal(0)
        factor = leftover ** exponent  # if exponent=0, factor=1
        R_eff = R_orig * factor
        W_eff = W_orig * factor
        pool_list.append({
            "pool":          pool_addr,
            "symbol":        sym,
            "total_usd_eff": R_eff,
            "weight_eff":    W_eff
        })

    # 5) Compute aggressive and safe allocations using the “effective” values
    agg_alloc  = compute_agg_allocation(pool_list, P)
    safe_alloc = compute_safe_allocation(pool_list, P)

    # 6) Blend them: Δ_i = θ * Δ_i^agg + (1 - θ) * Δ_i^safe
    combined = []
    for (addr_a, Δ_agg), (addr_s, Δ_safe) in zip(agg_alloc, safe_alloc):
        assert addr_a == addr_s  # same pool ordering
        Δ_comb = (Decimal(RISK_AVERSION) / Decimal(100)) * Δ_safe + (Decimal(1) - (Decimal(RISK_AVERSION) / Decimal(100))) * Δ_agg
        combined.append((addr_a, Δ_comb))

    # 7) Renormalize in case of rounding drift
    total_comb = sum(Δ for _, Δ in combined)
    if total_comb == 0:
        print("❌  Combined allocation is zero for all pools.")
        return

    # 8) Build final array, rounding each share to nearest 1%
    result = []
    for (pool_addr, Δ) in combined:
        if Δ <= 0:
            continue
        frac = Δ / total_comb
        pct_dec = frac * Decimal(100)
        pct_int = int(pct_dec.to_integral_value(rounding=ROUND_HALF_UP))
        sym = next(p["symbol"] for p in pools_raw if p["pool"].lower() == pool_addr)
        result.append({
            "symbol":  sym,
            "pool":    pool_addr,
            "votes":   float(Δ),
            "percent": pct_int
        })

    result.sort(key=lambda x: x["percent"], reverse=True)

    print(
        f"\n🏗️  Optimizer "
        f"(risk‐aversion={RISK_AVERSION}%, avoid‐relays={AVOID_FOUNDATION}%) → top {TOP_N} pools:\n"
    )
    for r in result[:TOP_N]:
        print(f" • {r['symbol']}: {r['percent']}%  ({r['votes']:.0f} votes)  [pool {r['pool']}]")
    exp = exponent if exponent == 0 else exponent  # just to show value
    print(
        f"\n✅  Done.\n"
        f"   θ = RISK_AVERSION/100 = {Decimal(RISK_AVERSION)/Decimal(100):.2f}\n"
        f"   exponent = 2 * α = {exp:.2f}\n"
    )

if __name__ == "__main__":
    main()
