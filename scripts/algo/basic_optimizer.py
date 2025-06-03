#!/usr/bin/env python3
import os
import json
from decimal import Decimal, getcontext

# Increase precision for decimal math
getcontext().prec = 28

DASHBOARD_PATH = "data/votes_dashboard.json"

def load_dashboard(path):
    if not os.path.exists(path):
        print(f"❌  {path} not found.")
        exit(1)
    with open(path) as f:
        return json.load(f)

def compute_scores(pools):
    """
    For each pool entry (which has 'total_usd' and 'weight'), compute:
      score = total_usd / (weight if weight > 0 else 1)
    Returns a list of tuples: (pool_symbol, pool_address, score_decimal).
    """
    scores = []
    for p in pools:
        total_usd = Decimal(str(p.get("total_usd", 0)))
        weight    = Decimal(str(p.get("weight", 0)))
        denom = weight if weight > 0 else Decimal(1)
        score = total_usd / denom
        scores.append((p["symbol"], p["pool"], score))
    return scores

def allocate_percentages(scores):
    """
    Given a list of (symbol, pool_addr, score), allocate integer percentages
    so that sum(percentages) == 100:
      1) raw_frac_i = score_i / sum(scores)
      2) percent_i  = round(raw_frac_i * 100)
      3) Adjust the pool with the largest score if sum != 100
    Returns a list of (symbol, pool_addr, percent_int).
    """
    total_score = sum(score for (_, _, score) in scores)
    if total_score == 0:
        return [(sym, addr, 0) for (sym, addr, _) in scores]

    temp = []
    for sym, addr, score in scores:
        raw_frac = score / total_score
        pct = int((raw_frac * Decimal(100)).to_integral_value(rounding="ROUND_HALF_UP"))
        temp.append([sym, addr, score, pct])

    sum_pct = sum(entry[3] for entry in temp)
    diff = 100 - sum_pct
    if diff != 0:
        idx_largest = max(range(len(temp)), key=lambda i: temp[i][2])
        temp[idx_largest][3] += diff

    return [(sym, addr, pct) for (sym, addr, _, pct) in temp]

def main():
    dash = load_dashboard(DASHBOARD_PATH)
    pools = dash.get("pools", [])
    if not pools:
        print("❌  No pools found in dashboard.")
        return

    # Step 1: compute scores
    scores = compute_scores(pools)
    # Step 2: sort by descending score
    scores.sort(key=lambda x: x[2], reverse=True)
    # Step 3: allocate integer percentages
    allocation = allocate_percentages(scores)

    print("\n🏗️  Basic vote‐allocation (rounded to nearest %):\n")
    for sym, addr, pct in allocation:
        if pct > 0:
            print(f" • {sym}: {pct}%  (pool: {addr})")
    print("\n✅  Done.")

if __name__ == "__main__":
    main()
