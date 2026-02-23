import requests
import re
import os
import json5
import pandas as pd
from bs4 import BeautifulSoup

url = "https://dunksandthrees.com/epm"
headers = {
    "User-Agent": "Mozilla/5.0"
}
response = requests.get(url, headers=headers)
html = response.text

soup = BeautifulSoup(html, "html.parser")
script_tags = soup.find_all("script")

stats_data = None
for tag in script_tags:
    if "stats:" in tag.text:
        match = re.search(r'stats\s*:\s*(\[\{.*?\}\])[,}]', tag.text, re.DOTALL)
        if match:
            json_str = match.group(1)
            
            # Replace 'undefined' with 'null' for JSON compatibility
            json_str = json_str.replace("undefined", "null")
            
            # Remove trailing commas before closing brackets/braces
            json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
            
            # Now decode using json5
            stats_data = json5.loads(json_str)
            break



if not stats_data:
    raise ValueError("❌ Could not find or decode 'stats' data in the page.")

df = pd.DataFrame(stats_data)

season = df['season'].unique()
# Drop unwanted columns if present
df = df.drop(columns=['game_dt', 'team_id', 'player_id'], errors='ignore')

output_folder = "EPM_stats"

filename = os.path.join(output_folder, f"epm_players_by_team_{season}.xlsx")
 

with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
    # Write full original data first
    df.to_excel(writer, sheet_name="All Players", index=False)
    
    # Then write one sheet per team_alias
    for team, group in df.groupby('team_alias'):
        sheet_name = team[:31]  # limit sheet name length
        group.to_excel(writer, sheet_name=sheet_name, index=False)


print("✅ Excel file saved with 'All Players' sheet and individual team sheets.")
