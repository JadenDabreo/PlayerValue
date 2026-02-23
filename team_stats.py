import requests
import pandas as pd
import os

url = "https://www.nbastuffer.com/2025-2026-nba-team-stats/"

headers = {"User-Agent": "Mozilla/5.0"}

response = requests.get(url, headers=headers)
response.raise_for_status()

tables = pd.read_html(response.text)
table = tables[0]

output_folder = "Team_stats"

if 'TEAM' in table.columns and 'GP' in table.columns:
    sort_columns = [
        "PPG", "oPPG", "pDIFF", "PACE", "oEFF", "dEFF", "eDIFF", 
        "SoS", "rSoS", "SAR", "CONS", "A4F", "W", "L", 
        "WIN%", "eWIN%", "pWIN%", "ACH"
    ]

    output_file = os.path.join(output_folder, "nba_2025_2026_team_stats_sorted_with_rank_filled.xlsx")
    with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
        table.to_excel(writer, sheet_name="Original", index=False)

        for col in sort_columns:
            if col in table.columns:
                sorted_df = table.sort_values(by=col, ascending=False).reset_index(drop=True)
                sorted_df['RANK'] = sorted_df.index + 1
                sheet_name = col[:31]
                sorted_df.to_excel(writer, sheet_name=sheet_name, index=False)
            else:
                print(f"Column '{col}' not found. Skipping sheet for this column.")

    print(f"Excel file created: {output_file}")
else:
    print("Desired table not found.")
