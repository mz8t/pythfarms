#!/usr/bin/env bash
set -euo pipefail

echo
echo "🛠  Running full pipeline…"
echo

# Step 1: fetch all pools via Sugar
echo "──────────"
echo "1/7 → python scripts/votes/1_get_sugar_pools.py"
python scripts/votes/1_get_sugar_pools.py
echo "✅  Completed Step 1"
echo

# Step 2: filter to only votable pools
echo "──────────"
echo "2/7 → python scripts/votes/2_filter_votable_pools.py"
python scripts/votes/2_filter_votable_pools.py
echo "✅  Completed Step 2"
echo

# Step 3: enrich votable pools with symbols/decimals/etc.
echo "──────────"
echo "3/7 → python scripts/votes/3_enriched_votable_pools.py"
python scripts/votes/3_enriched_votable_pools.py
echo "✅  Completed Step 3"
echo

# Step 3.5: map token addresses to CoinGecko IDs
echo "──────────"
echo "4/7 → python scripts/helper/3_5_get_coingecko_token_ids.py"
python scripts/helper/3_5_get_coingecko_token_ids.py
echo "✅  Completed Step 3.5"
echo

# Step 4: fetch live-epoch fees/bribes in USD via CoinGecko
echo "──────────"
echo "5/7 → python scripts/votes/4_live_epoch_fees_with_coingecko.py"
python scripts/votes/4_live_epoch_fees_with_coingecko.py
echo "✅  Completed Step 4"
echo

# Step 5: build vote dashboard (weights + our_votes)
echo "──────────"
echo "6/7 → python scripts/votes/5_create_votes_dashboard.py"
python scripts/votes/5_create_votes_dashboard.py
echo "✅  Completed Step 5"
echo

# Step 6: run advanced optimizer
echo "──────────"
echo "7/7 → python scripts/algo/optimizer_corrected_logic.py"
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

echo "🎉 All steps finished successfully."
echo
