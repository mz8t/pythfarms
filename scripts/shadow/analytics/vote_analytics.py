#!/usr/bin/env python3
import os
import json
import requests
from decimal import Decimal, getcontext, ROUND_HALF_UP
from web3 import Web3
from dotenv import load_dotenv
from collections import defaultdict
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Increase precision for financial calculations
getcontext().prec = 28

# Load environment variables
load_dotenv()
DASHBOARD_PATH           = os.getenv('DASHBOARD_PATH', 'data/shadow/votes_dashboard.json')
HUMAN_ALLOC_PATH         = os.getenv('HUMAN_ALLOC_PATH', 'optimizer/shadow/optimized_votes_human.json')
OUTPUT_PATH              = os.getenv('OUTPUT_PATH', 'analytics/shadow/analytics_report.json')
SHADOW_SLUG              = os.getenv('SHADOW_SLUG', 'shadow-2')
SIMPLE_PRICE_URL         = 'https://api.coingecko.com/api/v3/simple/price'

SHADOW_RPC_URL           = os.getenv('SHADOW_RPC_URL')
SHADOW_VOTER_ADDRESS     = os.getenv('SHADOW_VOTER_ADDRESS')      # voting contract
SHADOW_NFT_OWNER_ADDRESS = os.getenv('SHADOW_NFT_OWNER_ADDRESS')  # NFT-holder wallet
NFT_SIZE                 = Decimal(os.getenv('NFT_SIZE', '0'))
VOTER_ABI_PATH           = os.getenv('VOTER_ABI_PATH', 'abi/shadow/Voter.json')

def load_json(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found")
    with open(path, 'r') as f:
        return json.load(f)

def fetch_price(slugs):
    params = {'vs_currencies': 'usd'}
    for slug in slugs:
        params['ids'] = slug
        resp = requests.get(SIMPLE_PRICE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        price = data.get(slug, {}).get('usd')
        if price is not None:
            return Decimal(str(price))
    raise ValueError(f"No valid price for slugs: {slugs}")

def fetch_votes_for_period(rpc_url, voter_contract, nft_owner_address, abi_path, period):
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        logger.error("Failed to connect to RPC node")
        return None

    abi = load_json(abi_path)
    contract = w3.eth.contract(address=w3.to_checksum_address(voter_contract), abi=abi)
    owner_address = w3.to_checksum_address(nft_owner_address)

    try:
        # Get the number of pools voted for in the given period
        num_pools = contract.functions.userVotedPoolsPerPeriodLength(owner_address, period).call()
        logger.info(f"Number of pools voted for in period {period}: {num_pools}")

        # Get the list of pools
        pools = []
        for i in range(num_pools):
            pool = contract.functions.userVotedPoolsPerPeriod(owner_address, period, i).call()
            pools.append(pool)
        logger.info(f"Voted pools in period {period}: {pools}")

        # Get the vote weights for each pool
        votes = []
        for pool in pools:
            weight = contract.functions.userVotesForPoolPerPeriod(owner_address, period, pool).call()
            votes.append({'pool': pool, 'weight': weight})
        logger.info(f"Votes in period {period}: {votes}")

        # Return the period and votes as a dictionary
        return {'period': period, 'votes': votes}
    except AttributeError as e:
        logger.error(f"Function not found in contract ABI: {e}")
        logger.info("Check the ABI for the correct function names (e.g., userVotedPoolsPerPeriodLength, etc.)")
        return None
    except Exception as e:
        logger.error(f"Error fetching vote data for period {period}: {e}")
        return None

def fetch_last_period_votes(rpc_url, voter_contract, nft_owner_address, abi_path):
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        logger.error("Failed to connect to RPC node")
        return None

    abi = load_json(abi_path)
    contract = w3.eth.contract(address=w3.to_checksum_address(voter_contract), abi=abi)
    owner_address = w3.to_checksum_address(nft_owner_address)

    try:
        # Get the last voted period
        period = contract.functions.lastVoted(owner_address).call()
        logger.info(f"Last voted period for {owner_address}: {period}")
        return fetch_votes_for_period(rpc_url, voter_contract, nft_owner_address, abi_path, period)
    except AttributeError as e:
        logger.error(f"Function not found in contract ABI: {e}")
        logger.info("Check the ABI for the correct function names (e.g., lastVoted).")
        return None
    except Exception as e:
        logger.error(f"Error fetching last voted period: {e}")
        return None

def fetch_current_period_votes(rpc_url, voter_contract, nft_owner_address, abi_path):
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        logger.error("Failed to connect to RPC node")
        return None

    abi = load_json(abi_path)
    contract = w3.eth.contract(address=w3.to_checksum_address(voter_contract), abi=abi)

    try:
        # Get the current period and add 1
        current_period = contract.functions.getPeriod().call() + 1
        logger.info(f"Current period for voting: {current_period}")
        return fetch_votes_for_period(rpc_url, voter_contract, nft_owner_address, abi_path, current_period)
    except AttributeError as e:
        logger.error(f"Function not found in contract ABI: {e}")
        logger.info("Check the ABI for the correct function names (e.g., getPeriod).")
        return None
    except Exception as e:
        logger.error(f"Error fetching current period: {e}")
        return None

def main():
    alloc = load_json(HUMAN_ALLOC_PATH)
    total_expected_usd = Decimal(str(alloc.get('total_expected_usd', 0)))

    slugs = [s.strip() for s in SHADOW_SLUG.split(',')]
    price_usd = fetch_price(slugs)
    token_value = (price_usd * NFT_SIZE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    apr_percent = (Decimal('0') if token_value == 0 else
                   (total_expected_usd * Decimal(52) / token_value * Decimal(100))
                   .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    report = {
        'our_voting_power': float(NFT_SIZE),
        'token_price_usd': float(price_usd),
        'token_value_usd': float(token_value),
        'total_expected_usd_per_epoch': float(total_expected_usd),
        'forecasted_apr_percent': float(apr_percent),
    }

    if SHADOW_RPC_URL and SHADOW_VOTER_ADDRESS and SHADOW_NFT_OWNER_ADDRESS:
        # Fetch last period votes
        last_votes = fetch_last_period_votes(
            SHADOW_RPC_URL,
            SHADOW_VOTER_ADDRESS,
            SHADOW_NFT_OWNER_ADDRESS,
            VOTER_ABI_PATH
        )
        if last_votes:
            report['last_period_votes'] = last_votes
        else:
            logger.warning("No last period vote data retrieved")
            report['last_period_votes'] = None

        # Fetch current period votes
        current_votes = fetch_current_period_votes(
            SHADOW_RPC_URL,
            SHADOW_VOTER_ADDRESS,
            SHADOW_NFT_OWNER_ADDRESS,
            VOTER_ABI_PATH
        )
        if current_votes:
            report['current_votes'] = current_votes
        else:
            logger.warning("No current period vote data retrieved")
            report['current_votes'] = None
    else:
        logger.warning("Missing configuration for fetching votes")
        report['last_period_votes'] = None
        report['current_votes'] = None

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(report, f, indent=2)

    logger.info(f"Analytics + votes written to {OUTPUT_PATH}")

if __name__ == '__main__':
    main()