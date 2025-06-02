#!/usr/bin/env python3
import os
import json
import time
import signal
import sys
from web3 import Web3
from dotenv import load_dotenv
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Ctrl-C Handler ───────────────────────────────────────────────────────────────
def handle_sigint(sig, frame):
    print("\n🛑  Interrupted by user, exiting.")
    sys.exit(0)
signal.signal(signal.SIGINT, handle_sigint)

# ── Load ENV & Config ────────────────────────────────────────────────────────────
load_dotenv()
RPC_URL     = os.getenv("RPC_URL")
V2_FACTORY  = os.getenv("V2_FACTORY")
CL_FACTORY  = os.getenv("CL_FACTORY")
START_BLOCK = int(os.getenv("START_BLOCK", 0))
CHUNK       = int(os.getenv("BLOCK_CHUNK", 100_000))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 5))

# Clamp chunk size to provider’s max (100k)
MAX_RANGE = 100_000
if CHUNK > MAX_RANGE:
    print(f"⚠️  BLOCK_CHUNK={CHUNK} exceeds {MAX_RANGE}, clamping.")
    CHUNK = MAX_RANGE

# ── Web3 Setup ───────────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 180}))
V2_FACTORY = w3.to_checksum_address(V2_FACTORY)
CL_FACTORY = w3.to_checksum_address(CL_FACTORY)

# ── Correct event signatures ──────────────────────────────────────────────────────
SIG_V2 = "0x" + w3.keccak(text="PoolCreated(address,address,bool,address,uint256)").hex()
# **Updated**: include the `int24` tickSpacing param
SIG_CL = "0x" + w3.keccak(text="PoolCreated(address,address,uint24,int24,address)").hex()

# ── Helper to standardize raw data ────────────────────────────────────────────────
def _raw_data(log):
    d = log["data"]
    if isinstance(d, (bytes, bytearray)):
        return d
    return bytes.fromhex(d[2:] if d.startswith("0x") else d)

# ── Fetch logs with retries ───────────────────────────────────────────────────────
def fetch_logs(factory_addr, event_sig):
    latest = w3.eth.block_number
    ranges = [(b, min(b + CHUNK - 1, latest)) for b in range(START_BLOCK, latest+1, CHUNK)]

    def fetch_chunk(frm, to):
        for attempt in range(3):
            try:
                return w3.eth.get_logs({
                    "fromBlock": frm,
                    "toBlock":   to,
                    "address":   factory_addr,
                    "topics":    [event_sig]
                })
            except Exception as e:
                wait = 2 ** attempt
                print(f"⚠️ {factory_addr[:6]} {frm}-{to} failed (try {attempt+1}): {e}")
                time.sleep(wait)
        print(f"❌ {factory_addr[:6]} {frm}-{to} skipped after 3 retries")
        return []

    logs = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {exe.submit(fetch_chunk, frm, to): (frm, to) for frm, to in ranges}
        for fut in tqdm(as_completed(futures), total=len(futures),
                        desc=f"Logs {factory_addr[:6]}"):
            chunk = fut.result()
            if chunk:
                logs.extend(chunk)
    return logs

# ── Decoders ──────────────────────────────────────────────────────────────────────
def decode_v2(log):
    token0 = "0x" + log["topics"][1].hex()[-40:]
    token1 = "0x" + log["topics"][2].hex()[-40:]
    data   = _raw_data(log)
    stable = bool(int.from_bytes(data[0:32], "big"))
    pool   = "0x" + data[32+12:32+12+20].hex()
    return {
        "pool":   w3.to_checksum_address(pool),
        "token0": w3.to_checksum_address(token0),
        "token1": w3.to_checksum_address(token1),
        "type":   "V2",
        "stable": stable
    }

def decode_cl(log):
    token0 = "0x" + log["topics"][1].hex()[-40:]
    token1 = "0x" + log["topics"][2].hex()[-40:]
    # fee is indexed in topics[3], but we don’t need it for registry
    raw = _raw_data(log)
    # first 32 bytes = tickSpacing (signed int24 in low 3 bytes)
    tick = int.from_bytes(raw[29:32], "big", signed=True)
    # next 32 bytes = pool address (right-aligned)
    pool = "0x" + raw[32+12:32+12+20].hex()
    return {
        "pool":        w3.to_checksum_address(pool),
        "token0":      w3.to_checksum_address(token0),
        "token1":      w3.to_checksum_address(token1),
        "type":        "CL",
        "tickSpacing": tick
    }

def index_factory(addr, sig, decoder):
    logs = fetch_logs(addr, sig)
    print(f"   → Decoding {len(logs)} events…")
    return [decoder(log) for log in logs]

# ── Main ─────────────────────────────────────────────────────────────────────────
def main():
    cache = "data/indexed_pools.json"
    os.makedirs("data", exist_ok=True)
    if os.path.exists(cache):
        print(f"📂 Cache exists, exiting.")
        return

    print("🔍 Indexing V2 pools…")
    v2 = index_factory(V2_FACTORY, SIG_V2, decode_v2)

    print("🔍 Indexing CL pools…")
    cl = index_factory(CL_FACTORY, SIG_CL, decode_cl)

    merged = {p["pool"]: p for p in (v2 + cl)}.values()
    merged_list = list(merged)
    print(f"⚙️  Total unique pools: {len(merged_list)}")

    with open(cache, "w") as f:
        json.dump(merged_list, f, indent=2)
    print("✅ Cached to data/indexed_pools.json")

if __name__ == "__main__":
    main()
