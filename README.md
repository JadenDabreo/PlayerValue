# NBA Player Contract Value Dashboard

A Streamlit web app that calculates NBA player contract surplus value using a composite skill model built from DARKO DPM and EPM (Effective Plus-Minus). The dashboard ranks players by how underpaid or overpaid they are relative to their on-court impact and classifies every player into a playing style archetype.

---

## How It Works

### Skill Model

Player skill is measured as a weighted blend of two independent plus-minus metrics:

```
composite_skill = (0.5 × DARKO_DPM + 0.8 × EPM) / 1.3
```

- **DARKO DPM** — predictive/projection-focused metric from [apanalytics.shinyapps.io/DARKO](https://apanalytics.shinyapps.io/DARKO/)
- **EPM** — Effective Plus-Minus, current-season performance metric from [dunksandthrees.com/epm](https://dunksandthrees.com/epm)
- If EPM is unavailable for a player, DARKO DPM is used alone

### Contract Valuation

```
projected_MP  = MP_per_game × 72 games
WAR           = (composite_skill − (−2.0)) × projected_MP / (48 × 33.5)
fair_salary   = max(WAR, 0) × $6,000,000 + league_minimum
surplus       = fair_salary − actual_salary
```

Positive surplus = underpaid. Negative surplus = overpaid.

Multi-year contract projections apply the NBA aging curve (peak ≈ age 27, growth before, decline after) to estimate future fair value for each contract year.

---

## Project Structure

```
Tabulate/
├── DARKO.py              # Scrapes DARKO projections via Playwright
├── epm.py                # Scrapes EPM data from dunksandthrees.com
├── contracts.py          # Scrapes contract data from Basketball-Reference
├── team_stats.py         # Scrapes advanced team stats
├── team_base_stats.py    # Scrapes base team stats from ESPN
├── PlayerValue.py        # Core model: merges all data, computes WAR + surplus
├── dashboard.py          # Streamlit dashboard
│
├── DARKO_stats/          # Output from DARKO.py
├── EPM_stats/            # Output from epm.py
├── Contracts/            # Output from contracts.py
├── Team_stats/           # Output from team_stats.py
├── Team_base_stats/      # Output from team_base_stats.py
└── PlayerValue/          # Output from PlayerValue.py (read by dashboard)
```

---

## Setup

### Prerequisites

- Python 3.10+
- pip

### Install dependencies

```bash
pip install streamlit pandas openpyxl plotly requests beautifulsoup4 json5 playwright
playwright install chromium
```

---

## Running the Pipeline

Run scripts in this order. Each step writes Excel files consumed by the next.

### Step 1 — Scrape DARKO projections
```bash
python DARKO.py
```
Outputs to `DARKO_stats/`

### Step 2 — Scrape EPM
```bash
python epm.py
```
Outputs to `EPM_stats/`

### Step 3 — Scrape contracts
```bash
python contracts.py
```
Outputs to `Contracts/`

### Step 4 — (Optional) Update team stats
```bash
python team_stats.py
python team_base_stats.py
```
Outputs to `Team_stats/` and `Team_base_stats/`

### Step 5 — Run the value model
```bash
python PlayerValue.py
```
Fetches per-game minutes from Basketball-Reference, merges all data sources, and writes `PlayerValue/player_value_YYYY.xlsx`.

### Step 6 — Launch the dashboard
```bash
streamlit run dashboard.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Dashboard Features

| Tab | Description |
|-----|-------------|
| **📋 Player Table** | Full sortable table with DPM, EPM, composite skill, WAR, salary, surplus, and value tier |
| **📊 Charts** | Composite Skill vs Salary scatter, WAR vs Surplus scatter, tier distribution bar chart |
| **🏟️ Team Summary** | Team-level surplus value and WAR bar charts + summary table |
| **🔍 Player Detail** | Per-player contract vs fair value chart across all contract years |
| **⚖️ Compare Players** | Side-by-side stat and value comparison between two players |
| **🔬 Similar Players** | Finds the most statistically similar players using style and advanced stats |
| **🎯 Archetypes** | Classifies every player into one or more playing style archetypes (guards/wings/bigs) with distribution charts and peer lookup |

### Sidebar Filters

- **Team** — filter to a single team
- **Search Player** — jump to a specific player
- **Value Tier** — filter by tier(s)
- **Min games played** — exclude injured/DNP players (default: 15 games)
- **Sort By** — surplus, salary, WAR, composite skill, DPM, EPM, $/WAR, or name

### Value Tiers

| Tier | Meaning |
|------|---------|
| Elite Bargain | Severely underpaid relative to impact |
| Great Value | Meaningfully underpaid |
| Good Value | Slightly underpaid |
| Fair Value | Paid close to market rate |
| Overpaid | Paid more than impact warrants |
| Significantly Overpaid | Large negative surplus |
| Replacement Level | Below replacement threshold |
| No Contract Data | No salary info available |

---

## Updating Data

To refresh the dashboard with current-season data, re-run the pipeline from Step 1. The scrapers pull live data; `PlayerValue.py` will overwrite its output with a new dated Excel file, and the dashboard always reads the most recent file in `PlayerValue/`.

---

## Pushing Changes to GitHub

```bash
# Stage specific files you changed
git add dashboard.py PlayerValue.py

# Commit
git commit -m "Your message here"

# Push
git push
```

To push everything including updated data files:

```bash
git add .
git commit -m "Refresh data and update model"
git push
```
