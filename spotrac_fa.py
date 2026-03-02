"""
spotrac_fa.py
-------------
Fetches 2026 NBA free agent data from Spotrac, including UFA/RFA/option type.

Outputs (in FreeAgents/):
  free_agents_2026.xlsx  — one row per free agent with Player, Pos, Age,
                           Prev Team, Prev AAV, FA Type columns

Usage:
  python spotrac_fa.py

Run order in pipeline: ... → PlayerValue.py → spotrac_fa.py → (dashboard reads both)
"""

import os
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

OUTPUT_DIR = "FreeAgents"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "free_agents_2026.xlsx")
URL = "https://www.spotrac.com/nba/free-agents/available/_/year/2026"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Spotrac name → PlayerValue name when they differ
NAME_ALIASES = {
    "AJ Green":            "A.J. Green",
    "A.J. Lawson":         "AJ Lawson",
    "Bub Carrington":      "Carlton Carrington",
    "Alex Sarr":           "Alexandre Sarr",
    "Nic Claxton":         "Nicolas Claxton",
    "Herb Jones":          "Herbert Jones",
    "KJ Martin":           "Kenyon Martin Jr.",
    "PJ Washington":       "P.J. Washington",
    "GG Jackson":          "Gregory Jackson II",
}

os.makedirs(OUTPUT_DIR, exist_ok=True)


def _simplify_type(raw: str) -> str:
    """Normalize Spotrac FA type to a clean label."""
    raw = raw.strip()
    if raw.startswith("UFA"):
        return "UFA"
    if raw.startswith("RFA"):
        return "RFA"
    if raw.startswith("PLAYER"):
        return "Player Option"
    if raw.startswith("CLUB") or raw.startswith("TEAM"):
        return "Team Option"
    if "Two-Way" in raw or "two-way" in raw.lower():
        return "Two-Way"
    return raw


def fetch_free_agents() -> pd.DataFrame:
    print(f"Fetching: {URL}")
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")

    # Table 1 is the main FA list (Table 0 is recently signed/traded)
    fa_table = None
    for t in tables:
        headers = [th.get_text(strip=True) for th in t.find_all("th")]
        if "Type" in headers and "Prev Team" in headers:
            fa_table = t
            break

    if fa_table is None:
        raise ValueError("Could not find free agents table on page.")

    rows = fa_table.find_all("tr")
    col_headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]
    # Strip count suffix from player header e.g. "Player (229)" → "Player"
    col_headers = [re.sub(r"\s*\(\d+\)$", "", h) for h in col_headers]

    records = []
    for row in rows[1:]:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < len(col_headers):
            continue
        record = dict(zip(col_headers, cols))
        records.append(record)

    df = pd.DataFrame(records)
    if df.empty:
        return df

    # Rename columns for clarity
    df = df.rename(columns={
        "Player":   "Player",
        "Pos":      "Pos",
        "Age":      "Age",
        "YOE":      "YOE",
        "Prev Team": "Prev Team",
        "Prev AAV": "Prev AAV",
        "Type":     "FA Type Raw",
    })

    # Clean numeric columns
    df["Age"] = pd.to_numeric(df["Age"], errors="coerce")
    df["YOE"] = pd.to_numeric(df["YOE"], errors="coerce")
    df["Prev AAV"] = (
        df["Prev AAV"]
        .str.replace(r"[\$,]", "", regex=True)
        .pipe(pd.to_numeric, errors="coerce")
    )

    # Simplify FA type
    df["FA Type"] = df["FA Type Raw"].apply(_simplify_type)

    # Apply name aliases so player names match PlayerValue
    df["Player"] = df["Player"].replace(NAME_ALIASES)

    col_order = ["Player", "Pos", "Age", "YOE", "Prev Team", "Prev AAV", "FA Type", "FA Type Raw"]
    col_order = [c for c in col_order if c in df.columns]
    df = df[col_order]

    return df


if __name__ == "__main__":
    df = fetch_free_agents()
    if df.empty:
        print("No free agent data found.")
    else:
        df.to_excel(OUTPUT_FILE, index=False)
        print(f"\n{len(df)} free agents saved to {OUTPUT_FILE}")
        print("\nFA Type breakdown:")
        print(df["FA Type"].value_counts().to_string())
