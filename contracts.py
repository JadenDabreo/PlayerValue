import pandas as pd
import os 

url = "https://www.basketball-reference.com/contracts/players.html"

df = pd.read_html(url, header=[0,1])[0]

def flatten_columns(cols):
    flat_cols = []
    for col in cols:
        if "Unnamed" in str(col[0]):
            flat_cols.append(str(col[1]).strip())
        else:
            if str(col[1]).strip() != '':
                flat_cols.append(str(col[1]).strip())
            else:
                flat_cols.append(str(col[0]).strip())
    return flat_cols

df.columns = flatten_columns(df.columns)

season_cols = [col for col in df.columns if col not in ['Rk', 'Player', 'Tm', 'Guaranteed']]

if '2024-25' in season_cols:
    season_cols.remove('2024-25')

for col in season_cols:
    df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[\$,]', '', regex=True), errors='coerce')

df['Guaranteed'] = pd.to_numeric(df['Guaranteed'].astype(str).str.replace(r'[\$,]', '', regex=True), errors='coerce')

df = df[df['Rk'].apply(lambda x: str(x).isdigit())]
df['Rk'] = df['Rk'].astype(int)

df['years'] = df[season_cols].notnull().sum(axis=1)

df['aav'] = df[season_cols].sum(axis=1) / df['years']

money_cols = season_cols + ['Guaranteed', 'aav']

def money_format(x):
    if pd.isna(x):
        return ''
    return f"${x:,.0f}"

for col in money_cols:
    if col in df.columns:
        df[col] = df[col].apply(money_format)

# Prepare Excel writer
teams_sorted = sorted(df['Tm'].dropna().unique())

output_folder = "Contracts"
output_file = os.path.join(output_folder, "basketball_reference_contracts_with_teams.xlsx")

if '2024-25' in df.columns:
    df.drop(columns=['2024-25'], inplace=True)

with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
    df.to_excel(writer, index=False, sheet_name='All Players')
    
    for team in teams_sorted:
        team_df = df[df['Tm'] == team]
        safe_team_name = team[:31]
        team_df.to_excel(writer, index=False, sheet_name=safe_team_name)

print(f"✅ Saved main sheet and {len(df['Tm'].unique())} team sheets to '{output_file}'.")
