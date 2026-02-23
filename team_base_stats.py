from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import pandas as pd
import time
import os

# URL
url = "https://www.espn.com/nba/stats/team/_/season/2026/seasontype/2/"

# Headless browser
options = Options()
options.add_argument("--headless")
driver = webdriver.Chrome(options=options)

driver.get(url)
time.sleep(10)  # Wait for dynamic content
tables = pd.read_html(driver.page_source)
driver.quit()

output_folder = "Team_base_stats"
# Combine team names and stats
if len(tables) >= 2:
    team_names = tables[0]  # ['RK', 'Team']
    stats = tables[1]       # ['GP', 'PTS', ..., 'PF']
    
    # Reset RK to 1..N
    team_names['RK'] = range(1, len(team_names) + 1)

    # Merge both tables horizontally
    base_table = pd.concat([team_names, stats], axis=1)

    output_file = os.path.join(output_folder,"espn_nba_team_stats_2026.xlsx")

    # Create Excel writer
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Write the base table (original order)
        base_table.to_excel(writer, index=False, sheet_name="PTS (Default)")

        # Create additional sorted sheets
        exclude_cols = {'PTS', 'GP', 'PF'}
        stat_columns = [col for col in stats.columns if col not in exclude_cols]

        for col in stat_columns:
            sorted_df = base_table.sort_values(by=col, ascending=False).reset_index(drop=True)
            sorted_df['RK'] = range(1, len(sorted_df) + 1)
            sorted_df.to_excel(writer, index=False, sheet_name=col[:31])  # Excel max sheet name length = 31

    print("✅ Excel file created with multiple sheets sorted by each stat.")
else:
    print("❌ Expected 2 tables, but found fewer.")
