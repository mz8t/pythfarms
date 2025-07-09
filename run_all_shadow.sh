#!/usr/bin/env bash
set -euo pipefail

echo
echo "🛠  Running Dashboard for veNFT and Optimizer"
echo

# Step 1: build vote dashboard 
echo "──────────"
echo "1/2 → python scripts/shadow/votes/1_get_pools_api.py"
python scripts/shadow/votes/1_get_pools_api.py
echo "✅  Completed Step 5"
echo

# Step 2: append votes for dashboard
echo "──────────"
echo "2/2 → python scripts/shadow/votes/2_append_votes_dashboard.py"
python scripts/shadow/votes/2_append_votes_dashboard.py
echo "✅  Completed Step 6"
echo

echo "🎉 All steps finished successfully."
echo

# Step 7: run analytics
echo "──────────"
echo "7/7 → python scripts/analytics/vote_analytics.py"
python scripts/shadow/analytics/vote_analytics.py
echo "✅  Completed Step 7"
echo