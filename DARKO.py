import os
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright

DARKO_URL    = "https://www.darko.app/"
output_folder = "DARKO_stats"
os.makedirs(output_folder, exist_ok=True)

# The new darko.app uses "Off"/"Def" where PlayerValue.py expects "O-DPM"/"D-DPM"
COLUMN_RENAMES = {
    "Off": "O-DPM",
    "Def": "D-DPM",
}


def fetch_darko_projections() -> pd.DataFrame:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_page()

        print("Loading DARKO...")
        page.goto(DARKO_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_selector("table", timeout=30000)
        page.wait_for_timeout(2000)

        print("Downloading CSV...")
        with page.expect_download(timeout=30000) as dl_info:
            # Try text match first; fall back to any button/link with "csv" in text
            btn = (
                page.get_by_text("Download CSV", exact=True).first
                or page.locator("button, a").filter(has_text="CSV").first
            )
            btn.click()

        download = dl_info.value
        df = pd.read_csv(download.path())
        browser.close()

    print(f"  Raw columns : {list(df.columns)}")
    print(f"  Rows fetched: {len(df)}")

    df = df.rename(columns=COLUMN_RENAMES)

    # Split combined "Player & Team" column if the CSV merges them
    if "Player" not in df.columns and "Player & Team" in df.columns:
        split = df["Player & Team"].str.rsplit(" ", n=1, expand=True)
        df["Player"] = split[0]
        df["Team"]   = split[1]
        df.drop(columns=["Player & Team"], inplace=True)

    # DPM Improvement is no longer on the new site; PlayerValue.py defaults to 0
    if "DPM Improvement" not in df.columns:
        df["DPM Improvement"] = float("nan")

    return df


# ── Main ──────────────────────────────────────────────────────────────────────

df   = fetch_darko_projections()
year = datetime.now().year

output_file = os.path.join(output_folder, f"darko_talent_processed_{year}.xlsx")

with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
    df.to_excel(writer, sheet_name="All_Players", index=False)
    if "Team" in df.columns:
        for team in sorted(df["Team"].dropna().unique()):
            team_df = df[df["Team"] == team]
            team_df.to_excel(writer, sheet_name=str(team)[:31], index=False)

print(f"✅ Saved → {output_file}")
print(f"   Final columns: {list(df.columns)}")
