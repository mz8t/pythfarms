# PyThFarms README

A Python toolkit for indexing Aerodrome liquidity pools, filtering votable pools, enriching them with metadata, and computing live epoch‐to‐date fees & bribes (in USD) using CoinGecko. Follow these steps to reproduce the data pipeline.

---

## 📁 Project Structure

```
p y t h f a r m s/
├── abi/
│   ├── LpSugar.json
│   ├── POOL_ABI.json
│   ├── RewardsSugar.json
│   ├── V2_FACTORY_ABI.json
│   └── V3_FACTORY_ABI.json
│
├── data/
│   ├── enriched_votable_pools.json
│   ├── indexed_pools.json
│   ├── live_epoch_fees_usd.json
│   ├── sugar_pools.json
│   ├── token_to_id.json
│   └── votable_pools.json
│
├── scripts/
│   ├── helper/
│   │   └── 1_get_coingecko_token_ids.py
│   │
│   ├── 1_get_sugar_pools.py
│   ├── 2_filter_votable_pools.py
│   ├── 3_enriched_votable_pools.py
│   └── 4_live_epoch_fees_with_coingecko.py
│
├── venv/                      ← Python virtual environment (ignored by Git)
├── .env                       ← Environment variables (RPC URL, RewardsSugar address)
├── .gitignore
├── README.md
└── requirements.txt
```

---

## 🛠️ Setup

1. **Clone the repo** (if you haven’t already):

   ```bash
   git clone https://github.com/yourusername/pythfarms.git
   cd pythfarms
   ```

2. **Create a Python virtual environment** and install dependencies:

   ```bash
   python3 -m venv venv
   source venv/bin/activate      # macOS/Linux
   venv\Scripts\activate         # Windows

   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Create a `.env` file** in the project root with the following variables:

   ```
   RPC_URL=<YOUR_BASE_RPC_ENDPOINT>
   REWARDS_SUGAR_ADDRESS=<RewardsSugar_contract_address_on_Base>
   ```

   * `RPC_URL` must point to a Base‐compatible JSON‐RPC node (e.g. Ankr, Alchemy, etc.).
   * `REWARDS_SUGAR_ADDRESS` is the deployed RewardsSugar contract on Base, e.g. `0x…`.

4. **Verify your ABI files** are in `abi/`:

   * `LpSugar.json`
   * `POOL_ABI.json`
   * `RewardsSugar.json`
   * `V2_FACTORY_ABI.json`
   * `V3_FACTORY_ABI.json`

---

## 📑 Data Pipeline & Scripts

Below is the recommended order to run each script. Each step writes a JSON file under `data/`:

### 1. Fetch all Aerodrome pools via Sugar

```bash
python scripts/1_get_sugar_pools.py
```

* **Input:** None
* **Output:**

  * `data/sugar_pools.json`

    * Contains an array of all pools (basic volatile, V3, CL) as returned by LpSugar’s `all(...)`.
* **What it does:**

  1. Connects to LpSugar on Base.
  2. Paginates through `all(limit, offset)` until all pools are fetched.
  3. Saves them to `data/sugar_pools.json`.

---

### 2. Filter “votable” pools (active gauges only)

```bash
python scripts/2_filter_votable_pools.py
```

* **Input:**

  * `data/sugar_pools.json`
* **Output:**

  * `data/votable_pools.json`

    * Subset of pools that have `gauge_alive == true`.
* **What it does:**

  1. Reads `sugar_pools.json`.
  2. Keeps only those entries where `"gauge_alive": true`.
  3. Writes the filtered array to `votable_pools.json`.

---

### 3. Enrich votable pools with human‐readable symbols & token metadata

```bash
python scripts/3_enriched_votable_pools.py
```

* **Input:**

  * `data/votable_pools.json`
* **Output:**

  * `data/enriched_votable_pools.json`

    * Each pool object now has:

      * `symbol`: `"TOKEN0/TOKEN1"` (from ERC-20 calls)
      * `token0`, `token1` (addresses)
      * `decimals`, `liquidity`, `reserve0`, `reserve1`, etc., if pulled from the pool contract
* **What it does:**

  1. Reads `votable_pools.json`.
  2. For each pool:

     * Reads on-chain `token0.symbol()` and `token1.symbol()`.
     * Attempts to read `pool.symbol()` (if available).
     * Reads `decimals()`, reserves (`reserve0`, `reserve1`), etc.
     * Populates a unified `symbol` field and any missing fields.
  3. Saves enriched data to `enriched_votable_pools.json`.

---

### 4. Map Base token addresses → CoinGecko IDs

```bash
python scripts/helper/1_get_coingecko_token_ids.py
```

* **Input:**

  * `data/enriched_votable_pools.json`
* **Output:**

  * `data/token_to_id.json`

    * `{ "0xTokenAddr…": "coingecko-id", … }`
* **What it does:**

  1. Reads all pools from `enriched_votable_pools.json`, extracts unique `token0`/`token1` addresses.
  2. Fetches CoinGecko’s `/coins/list?include_platform=true`, which returns every CoinGecko coin with a `"platforms"` dictionary.
  3. Builds a mapping for any coin whose `"platforms"` contain `"base": "<token_address>"`.
  4. Writes out `{ contract_address: coingecko_id }` to `token_to_id.json`.

---

### 5. Compute live‐epoch fees & bribes in USD (via CoinGecko)

```bash
python scripts/4_live_epoch_fees_with_coingecko.py
```

* **Input:**

  * `data/enriched_votable_pools.json`
  * `data/token_to_id.json`
* **Output:**

  * `data/live_epoch_fees_usd.json`

    ```json
    [
      {
        "pool":         "0xPoolAddress...",
        "symbol":       "TOKEN0/TOKEN1",
        "fee0_amount":  1234500000000000000,
        "fee1_amount":  987650000000000000,
        "fees_usd":     234.56,
        "bribes_usd":   12.34,
        "bribes": [
          {
            "token":        "0xBribeTokenAddr",
            "symbol":       "BRIBSY",
            "amount":       5000000000000000000,
            "amount_token": 5.0,
            "amount_usd":   7.50
          },
          {
            "token":        "0xAnotherBribeToken",
            "symbol":       "ABC",
            "amount":       2000000,
            "amount_token": 2.0,
            "amount_usd":   4.84
          }
        ],
        "total_usd":    246.90
      },
      …
    ]
    ```
* **What it does:**

  1. Reads `enriched_votable_pools.json` to get each pool’s `token0`/`token1`.
  2. Reads `token_to_id.json` to map each token address → CoinGecko ID.
  3. Calls CoinGecko’s `/simple/price?ids={comma-separated-ids}&vs_currencies=usd` in batches of ≲80 IDs at a time (to respect rate limits).
  4. Builds a dictionary `{ contract_address: Decimal(usd_price) }` for each token.
  5. For each pool:

     * Uses Sugar’s `epochsByAddress(1, 0, poolAddress)` to fetch the “live” (current‐epoch) `LpEpoch` struct.
     * Splits `fees[]` into `fee0_amount` (for `token0`) and `fee1_amount` (for `token1`).
     * Converts each raw `feeX_amount` → decimal using `decimals()` and multiplies by the USD price to get `fees_usd`.
     * Iterates `bribes[]`, computes detailed `{ token, symbol, amount, amount_token, amount_usd }` for each bribe token.
     * Sums all bribe USD → `bribes_usd`.
     * Computes `total_usd = fees_usd + bribes_usd`.
     * Stores a JSON object per pool, sorted descending by `total_usd`.
  6. Writes the final array to `live_epoch_fees_usd.json`.

---

## 📖 Usage Summary

Below is a quick “run‐order” checklist. Each step depends on the previous step’s outputs.

```bash
# 0) Set up your environment
pip install -r requirements.txt
cp .env.example .env
# Edit .env: add RPC_URL and REWARDS_SUGAR_ADDRESS

# 1) Fetch all pools
python scripts/1_get_sugar_pools.py
#  -> data/sugar_pools.json

# 2) Filter to active (votable) pools
python scripts/2_filter_votable_pools.py
#  -> data/votable_pools.json

# 3) Enrich votable pools with on‐chain metadata & symbols
python scripts/3_enriched_votable_pools.py
#  -> data/enriched_votable_pools.json

# 4) Map each token to a CoinGecko ID
python scripts/helper/1_get_coingecko_token_ids.py
#  -> data/token_to_id.json

# 5) Compute live epoch‐to‐date fees + bribes in USD
python scripts/4_live_epoch_fees_with_coingecko.py
#  -> data/live_epoch_fees_usd.json
```

At the end of step 5, you have a JSON file describing all votable pools with:

* raw fee amounts (per token)
* USD value of fees (for token0 & token1)
* detailed bribe breakdown (token, human amount, USD value)
* combined `total_usd = fees + bribes`


---

## 📦 requirements.txt

```text
web3==6.x.x
python-dotenv
requests
tqdm
```

