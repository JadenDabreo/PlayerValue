import os
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright

DARKO_URL = "https://apanalytics.shinyapps.io/DARKO/"
output_folder = "DARKO_stats"
os.makedirs(output_folder, exist_ok=True)


def fetch_darko_projections() -> pd.DataFrame:
    """Scrape the 'Current Player Skill Projections' table from DARKO."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Loading DARKO...")
        # Shiny keeps a WebSocket open indefinitely, so networkidle never fires
        page.goto(DARKO_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector("a[data-value='Current Player Skill Projections']", timeout=60000)

        page.click("a[data-value='Current Player Skill Projections']")
        print("Waiting for table...")
        page.wait_for_selector("table.dataTable", timeout=60000)
        page.wait_for_timeout(2000)  # let data populate

        # Set page length to 100 to minimise number of page turns
        length_select = page.query_selector("select[name*='length']")
        if length_select:
            length_select.select_option("100")
            page.wait_for_timeout(1500)

        all_rows = []
        headers = None
        page_num = 1

        while True:
            print(f"  Scraping page {page_num}...")

            if headers is None:
                headers = page.eval_on_selector_all(
                    "table.dataTable thead th",
                    "els => els.map(el => el.innerText.trim())"
                )

            rows = page.eval_on_selector_all(
                "table.dataTable tbody tr",
                "els => els.map(row => Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim()))"
            )
            rows = [r for r in rows if any(cell != "" for cell in r)]
            all_rows.extend(rows)

            next_btn = page.query_selector(".dataTables_paginate .next:not(.disabled)")
            if not next_btn:
                break
            next_btn.click()
            page.wait_for_timeout(1500)
            page_num += 1

        browser.close()

    if not headers or not all_rows:
        raise RuntimeError("No data found — check if the tab name changed on the DARKO site.")

    df = pd.DataFrame(all_rows, columns=headers)
    print(f"  Fetched {len(df)} rows, {len(df.columns)} columns.")
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

df = fetch_darko_projections()
year = datetime.now().year

output_file = os.path.join(output_folder, f"darko_talent_processed_{year}.xlsx")

with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
    df.to_excel(writer, sheet_name="All_Players", index=False)
    if "Team" in df.columns:
        for team in sorted(df["Team"].dropna().unique()):
            team_df = df[df["Team"] == team]
            team_df.to_excel(writer, sheet_name=str(team)[:31], index=False)

print(f"✅ Excel file saved to: {output_file}")
