"""
measurements.py
---------------
Scrapes player physical measurements (height, wingspan, weight, arm length)
from craftednba.com/player-traits/length.

The page is Nuxt.js SSR — all data is embedded in a __NUXT_DATA__ JSON blob,
so no headless browser or API key is required.

Output: Measurements/player_measurements_<year>.xlsx

Run order: DARKO.py → epm.py → Contracts.py → measurements.py → PlayerValue.py
"""

import json
import os
import re
import unicodedata
from datetime import datetime

import pandas as pd
import requests

URL        = "https://craftednba.com/player-traits/length"
OUTPUT_DIR = "Measurements"

# Map craftednba field names → our column names
FIELDS = {
    "player":      "Player",
    "Tm":          "Team_abbr",
    "Pos":         "Position",
    "HeightSocks": "Height_in",
    "Wingspan":    "Wingspan_in",
    "Weight":      "Weight_lbs",
    "Length":      "ArmLength_in",   # wingspan minus height
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── Name normalisation (mirrors PlayerValue.py) ───────────────────────────────
def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = re.sub(r"\s+(jr\.?|sr\.?|ii+|iii+|iv)$", "", name.strip(),
                  flags=re.IGNORECASE)
    return name.lower().strip()


# ── Parser ────────────────────────────────────────────────────────────────────
def parse_nuxt_data(html: str) -> pd.DataFrame:
    """
    Extracts the __NUXT_DATA__ dehydrated-state blob and resolves player
    records.  Nuxt stores the state as a flat JSON array; a sub-array of
    integers at a known position holds the starting index of each player
    record.  Each record is a dict mapping field names → absolute indices
    into the flat array.
    """
    match = re.search(
        r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not match:
        raise RuntimeError("__NUXT_DATA__ script tag not found — page structure may have changed")

    data = json.loads(match.group(1))
    print(f"  __NUXT_DATA__ flat array length: {len(data):,}")

    # Find the array that lists player start indices:
    # it is a list of 400–700 integers, all valid indices into `data`.
    player_indices = None
    for item in data:
        if (
            isinstance(item, list)
            and 400 < len(item) < 800
            and all(isinstance(x, int) for x in item[:20])
        ):
            player_indices = item
            break

    if player_indices is None:
        raise RuntimeError("Could not locate player-index array in __NUXT_DATA__")

    print(f"  Found player index array: {len(player_indices)} entries")

    records = []
    for start_idx in player_indices:
        if start_idx >= len(data):
            continue
        schema = data[start_idx]
        if not isinstance(schema, dict):
            continue

        record = {}
        for src_field, dst_col in FIELDS.items():
            if src_field not in schema:
                continue
            val_idx = schema[src_field]
            if isinstance(val_idx, int) and val_idx < len(data):
                record[dst_col] = data[val_idx]
            else:
                record[dst_col] = None

        if record.get("Player"):
            records.append(record)

    if not records:
        raise RuntimeError("Parsed 0 player records — schema may have changed")

    df = pd.DataFrame(records)

    # Cast numeric columns
    for col in ("Height_in", "Wingspan_in", "Weight_lbs", "ArmLength_in"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Human-readable height / wingspan strings (e.g. 6'3")
    def inches_to_ft(x):
        if pd.isna(x):
            return ""
        ft  = int(x // 12)
        rem = round(x % 12, 1)
        return f"{ft}'{rem}\""

    df["Height_display"]   = df["Height_in"].apply(inches_to_ft)
    df["Wingspan_display"] = df["Wingspan_in"].apply(inches_to_ft)

    # Merge key for cross-source name matching
    df["_key"] = df["Player"].map(normalize_name)

    return df


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> pd.DataFrame:
    print("=" * 55)
    print("Fetching player measurements from craftednba.com...")
    print("=" * 55)

    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    print(f"  Downloaded {len(r.text):,} chars")

    df = parse_nuxt_data(r.text)
    print(f"  Parsed {len(df)} player records  "
          f"({df['Height_in'].notna().sum()} with height, "
          f"{df['Wingspan_in'].notna().sum()} with wingspan)")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, f"player_measurements_{datetime.now().year}.xlsx")
    df.drop(columns=["_key"]).to_excel(out, index=False, sheet_name="Measurements")
    print(f"\n✅ Saved → {out}")
    return df


if __name__ == "__main__":
    main()
