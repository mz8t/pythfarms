#!/usr/bin/env python3
import os
import json
from web3 import Web3
from web3.exceptions import ContractLogicError
from dotenv import load_dotenv
from decimal import Decimal

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────────
RPC_URL        = os.getenv("RPC_URL")
VOTER_ADDRESS  = os.getenv("VOTER_ADDRESS")
VE_ADDRESS     = os.getenv("VE_ADDRESS")
NFT_ID         = int(os.getenv("NFT_ID", "0"))

LIVE_FEES_PATH = "data/live_epoch_fees_usd.json"
OUTPUT_PATH    = "data/votes_dashboard.json"

# ── Voter ABI (must include totalWeight(), weights(address), votes(tokenId,pool)) ─
VOTER_ABI = json.load(open("abi/Voter.json"))
VE_ABI = json.load(open("abi/Ve.json"))


# ── Web3 Setup ───────────────────────────────────────────────────────────────────
if not RPC_URL or not VOTER_ADDRESS or not VE_ADDRESS or NFT_ID  == 0:
    print("❌  Please set RPC_URL, VOTER_ADDRESS, and NFT_ID (nonzero) in your .env")
    exit(1)

w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))
voter = w3.eth.contract(
    address=w3.to_checksum_address(VOTER_ADDRESS),
    abi=VOTER_ABI
)
Ve = w3.eth.contract(
    address=w3.to_checksum_address(VE_ADDRESS),
    abi=VE_ABI
)

# ── Helpers ───────────────────────────────────────────────────────────────────────
def get_our_veNFT_balance() -> Decimal:
    """
    Calls Ve.balanceOfNFT() to get our balance (raw wei),
    converts to Decimal by dividing by 10**18.
    """
    try:
        raw = Ve.functions.balanceOfNFT(NFT_ID).call()
        return Decimal(raw) / Decimal(10**18)
    except ContractLogicError as e:
        print(f"X Error calling balanceOfNft(): {e}")
        return Decimal(0)
    except Exception as e:
        print(f"❌  Unexpected error in balanceOfNft(): {e}")
        return Decimal(0)


def get_total_weight() -> Decimal:
    """
    Calls Voter.totalWeight() to get sum of all pool weights (raw wei),
    converts to Decimal by dividing by 10**18.
    """
    try:
        raw = voter.functions.totalWeight().call()
        return Decimal(raw) / Decimal(10**18)
    except ContractLogicError as e:
        print(f"❌  Error calling totalWeight(): {e}")
        return Decimal(0)
    except Exception as e:
        print(f"❌  Unexpected error in totalWeight(): {e}")
        return Decimal(0)

def get_weight_for_pool(pool_addr: str) -> Decimal:
    """
    Calls Voter.weights(poolAddress) to get raw weight (wei),
    converts to Decimal by dividing by 10**18.
    """
    try:
        raw = voter.functions.weights(w3.to_checksum_address(pool_addr)).call()
        return Decimal(raw) / Decimal(10**18)
    except ContractLogicError:
        return Decimal(0)
    except Exception as e:
        print(f"⚠️  Error fetching weight for {pool_addr}: {e}")
        return Decimal(0)

def get_our_votes(pool_addr: str) -> Decimal:
    """
    Calls Voter.votes(NFT_ID, poolAddress) to get raw votes (wei),
    converts to Decimal by dividing by 10**18.
    """
    try:
        raw = Ve.functions.votes(NFT_ID, w3.to_checksum_address(pool_addr)).call()
        return Decimal(raw) / Decimal(10**18)
    except ContractLogicError:
        return Decimal(0)
    except Exception:
        return Decimal(0)

# ── Main ───────────────────────────────────────────────────────────────────────────

def main():
    # 1) Load live_epoch_fees_usd.json
    if not os.path.exists(LIVE_FEES_PATH):
        print(f"❌  {LIVE_FEES_PATH} not found. Run 4_live_epoch_fees_with_coingecko.py first.")
        return

    with open(LIVE_FEES_PATH) as f:
        pools = json.load(f)

    # 2) Call totalWeight() on Voter (converted to human‐readable)
    total_weight = get_total_weight()
    print(f"ℹ️  Voter.totalWeight() = {total_weight} (vote‐units)")
    our_nft_weight = get_our_veNFT_balance()
    print(f"ℹ️  Ve.ourBalance() = {our_nft_weight} (vote‐units)")

    # 3) For each pool, fetch weight and our_votes, both converted to human‐readable
    augmented_pools = []
    for entry in pools:
        # entry is e.g.:
        # {
        #   "pool": "0x…",
        #   "symbol": "TOKEN0/TOKEN1",
        #   "type": "V2",       ← this is carried over
        #   "fee0_amount": …,
        #   "fee1_amount": …,
        #   "fees_usd": …,
        #   "bribes_usd": …,
        #   "bribes": […],
        #   "total_usd": …
        # }
        pool_addr   = entry["pool"].lower()
        weight_hr   = get_weight_for_pool(pool_addr)   # Decimal
        our_votes_hr= get_our_votes(pool_addr)         # Decimal

        # Copy existing fields (including "type"), then add "weight" and "our_votes"
        e = entry.copy()
        e["weight"]    = float(weight_hr)
        e["our_votes"] = float(our_votes_hr)

        augmented_pools.append(e)

    # 4) Wrap under top‐level object
    output = {
        "total_weight": float(total_weight),
        "our_voting_power": float(our_nft_weight),
        "pools":        augmented_pools
    }

    # 5) Sort pools by total_usd descending
    output["pools"].sort(key=lambda x: x["total_usd"], reverse=True)

    # 6) Write JSON
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅  Wrote votes dashboard (with type, weight & our_votes) to {OUTPUT_PATH}\n")
    print("🏆 Top 5 pools by USD (fees+bribes), showing each pool’s type, weight & our_votes:")
    for r in output["pools"][:5]:
        print(
            f" • {r['symbol']} (type={r.get('type')}) @ {r['pool']}: "
            f"total_usd=${r['total_usd']:.2f}, "
            f"weight={r['weight']}, our_votes={r['our_votes']}"
        )

if __name__ == "__main__":
    main()
