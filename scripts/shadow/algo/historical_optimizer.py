#fetches last epoch's final votes, optimized as if we were the last voter, computes expected return.
import json
import os
from decimal import Decimal, getcontext, ROUND_HALF_UP
from optimizer import equal_marginal  


getcontext().prec = 50

def load_json(path):
    """Load a JSON file from the given path."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found")
    with open(path, 'r') as f:
        return json.load(f)

def deduct_user_votes(dashboard, user_votes):
    """Deduct user's votes from the dashboard totals and pool votes."""
    adjusted_pools = []
    total_votes_deducted = Decimal(0)

    for pool in dashboard['pools']:
        adjusted_pool = pool.copy()
        for vote in user_votes['votes']:
            if vote['pool'].lower() == pool['pool'].lower():
                your_weight = Decimal(vote['weight']) / Decimal(10**18)
                adjusted_pool['pool_votes_period'] = float(Decimal(pool['pool_votes_period']) - your_weight)
                total_votes_deducted += your_weight
                break
        adjusted_pools.append(adjusted_pool)

    adjusted_total_votes = Decimal(dashboard['total_votes_period']) - total_votes_deducted
    return {
        'period': dashboard['period'],
        'total_votes_period': float(adjusted_total_votes),
        'pools': adjusted_pools
    }

def run_optimizer(adjusted_dashboard, voting_power):
    """Run the optimizer on the adjusted dashboard to get optimal allocation."""
    base = []
    for p in adjusted_dashboard['pools']:
        addr = p['pool'].lower()
        R = Decimal(str(p.get('bribes_usd', 0)))
        W = Decimal(str(p.get('pool_votes_period', 0)))
        base.append((addr, R, W))

    alloc = equal_marginal(base, voting_power)
    total_alloc = sum(d for _, d in alloc)

    human = []
    for addr, d in alloc:
        if d > 0:
            p = next(x for x in adjusted_dashboard['pools'] if x['pool'].lower() == addr)
            fraction = d / (Decimal(p['pool_votes_period']) + d) if (Decimal(p['pool_votes_period']) + d) > 0 else Decimal(0)
            exp_usd = float((Decimal(str(p.get('bribes_usd', 0))) * fraction).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            human.append({
                "symbol": p.get("symbol", ""),
                "pool": addr,
                "votes": float(d),
                "exp_usd": exp_usd
            })

    total_exp = sum(item['exp_usd'] for item in human)
    return {
        "total_expected_usd": round(total_exp, 2),
        "allocations": human
    }

def main():
    
    dashboard_path = input("Enter the path to the historical votes dashboard file (e.g., data/shadow/2898_votes_dashboard_160725.json): ")
    dashboard = load_json(dashboard_path)

    
    analytics_path = 'analytics/shadow/analytics_report.json'  
    analytics = load_json(analytics_path)

    
    period = dashboard['period']
    last_period_votes = analytics.get('last_period_votes', {})
    if last_period_votes.get('period') != period:
        raise ValueError(f"Vote analytics period ({last_period_votes.get('period')}) does not match dashboard period ({period})")

    user_votes = last_period_votes

    
    adjusted_dashboard = deduct_user_votes(dashboard, user_votes)

    
    voting_power = Decimal(str(analytics['our_voting_power']))

    
    optimal_result = run_optimizer(adjusted_dashboard, voting_power)

    
    date_str = dashboard_path.split('_')[-1].replace('.json', '')
    output_path = f'optimizer/shadow/historical/optimized_votes_{date_str}.json'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    
    with open(output_path, 'w') as f:
        json.dump(optimal_result, f, indent=2)

    print(f"✅ Optimization complete. Results saved to {output_path}")

if __name__ == "__main__":
    main()