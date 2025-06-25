#!/usr/bin/env bash
set -euo pipefail

echo
echo "🛠  Running Dashboard for veNFT and Optimizer"
echo

# Step 1: build vote dashboard (weights + our_votes)
echo "──────────"
echo "1/2 → python scripts/votes/5_create_votes_dashboard.py"
python scripts/votes/5_create_votes_dashboard.py
echo "✅  Completed Step 5"
echo

# Step 2: run advanced optimizer
echo "──────────"
echo "2/2 → python scripts/algo/optimizer_corrected_logic.py"
python scripts/algo/optimizer_corrected_logic.py
echo "✅  Completed Step 6"
echo

echo "🎉 All steps finished successfully."
echo

# Step 7: run analytics
echo "──────────"
echo "7/7 → python scripts/analytics/vote_analytics.py"
python scripts/analytics/vote_analytics.py
echo "✅  Completed Step 7"
echo