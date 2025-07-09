#!/usr/bin/env bash
set -euo pipefail

echo
echo "🛠  Running Dashboard for veNFT and Optimizer"
echo

# Step 1: build vote dashboard 
echo "──────────"
echo "1/5 → python scripts/shadow/votes/1_get_pools_api.py"
python scripts/shadow/votes/1_get_pools_api.py
echo "✅  Completed Step 1"
echo

# Step 2: append votes for dashboard
echo "──────────"
echo "2/5 → python scripts/shadow/votes/2_append_votes_dashboard.py"
python scripts/shadow/votes/2_append_votes_dashboard.py
echo "✅  Completed Step 2"
echo
echo

# Step 3: run advanced optimizer
echo "──────────"
echo "3/5 → python scripts/shadow/algo/optimizer_corrected_logic.py"
python scripts/shadow/algo/optimizer.py
echo "✅  Completed Step 3"
echo

# Step 6: run advanced optimizer
echo "──────────"
echo "4/5 → python scripts/shadow/analytics/generate_shadow_calldata.py"
python scripts/shadow/analytics/generate_shadow_calldata.py
echo "✅  Completed Step 4"
echo

# Step 7: run analytics
echo "──────────"
echo "5/5 → python scripts/analytics/vote_analytics.py"
python scripts/shadow/analytics/vote_analytics.py
echo "✅  Completed Step 5"
echo