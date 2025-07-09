#!/usr/bin/env python3
import os
import json
from decimal import Decimal, ROUND_HALF_UP
from dotenv import load_dotenv

# Load env
load_dotenv()

# Required env
VOTER_ADDRESS = os.getenv('VOTER_ADDRESS')
if not VOTER_ADDRESS:
    print("❌ Please set VOTER_ADDRESS in your .env")
    exit(1)

# Paths
HUMAN_ALLOC_PATH = os.getenv('HUMAN_ALLOC_PATH', 'optimizer/shadow/optimized_votes_human.json')
OUTPUT_PATH      = os.getenv('OUTPUT_PATH', 'optimizer/shadow/calldata.json')

# Load human allocations
def load_json(path):
    if not os.path.exists(path):
        print(f"❌ {path} not found. Run optimizer first.")
        exit(1)
    with open(path) as f:
        return json.load(f)

alloc_data = load_json(HUMAN_ALLOC_PATH)
allocs = alloc_data.get('allocations', [])

if not allocs:
    print("❌ No allocations found in human output.")
    exit(1)

# Extract votes and pool addresses
votes = [Decimal(str(item['votes'])) for item in allocs]
pools = [item['pool'] for item in allocs]
total_votes = sum(votes)

if total_votes <= 0:
    print("❌ Sum of votes is zero; cannot generate weights.")
    exit(1)

# Compute integer weights summing to 1_000_000
weights = []
for v in votes:
    # proportional share of 1e6
    share = (v / total_votes * Decimal(1_000_000)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    weights.append(int(share))

# Fix rounding drift: adjust last weight
drift = 1_000_000 - sum(weights)
if drift != 0:
    weights[-1] += drift

# Build calldata object
calldata = {
    'voter': VOTER_ADDRESS,
    '_pools': pools,
    '_weights': weights
}

# Write to file
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
with open(OUTPUT_PATH, 'w') as f:
    json.dump(calldata, f, indent=2)

print(f"✅ Calldata written to {OUTPUT_PATH}")
