"""
PlayerValue.py
--------------
Reads DARKO skill projections, EPM, and contract data from existing Excel files
(produced by DARKO.py, epm.py, and Contracts.py), fetches only minutes played
from Basketball-Reference, then calculates WAR and contract surplus value.

Run order:  DARKO.py → epm.py → Contracts.py → PlayerValue.py

Model
-----f
  Skill is a 50/50 blend of DARKO DPM and EPM (Effective Plus-Minus).
  DARKO is predictive/projection-focused; EPM reflects current-season
  performance. Blending the two smooths noise from either source.
  If EPM is unavailable for a player, DARKO DPM is used alone.

  composite_skill    = 0.5 * DARKO_DPM + 0.5 * EPM   (or DARKO_DPM if no EPM)
  projected_MP       = MP_per_game * EXPECTED_GAMES   (72-game standard season)
  WAR                = (composite_skill - (-2.0)) * projected_MP / (48 * 33.5)
  usage_scalar       = (USG% / 25.0)^2 quadratic, clamped to [0.35, 1.00]
                       Reference is 25% (primary ball-handler). Quadratic means
                       role players at 18% usage are penalised ~50%, not 10%.
                       EPM/DPM are per-possession efficiency metrics — role players at
                       low usage post good efficiency but command lower market salaries.
                       usage_scalar adjusts fair_salary to reflect this market reality.
  fair_salary        = (max(WAR, 0) * $6,000,000 * usage_scalar) + league_minimum
  surplus            = fair_salary - actual_salary   (+ underpaid / - overpaid)
  $/WAR              = actual_salary / max(WAR, 0.01)
"""

import glob
import os
import re
import unicodedata
import pandas as pd
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
BBR_STATS_URL    = "https://www.basketball-reference.com/leagues/NBA_2026_per_game.html"
CURRENT_SEASON   = "2025-26"

REPLACEMENT_DPM     = -2.0        # points/100 below avg ≈ freely replaceable
MARKET_RATE_PER_WIN = 6_000_000   # $/win (approx 2025-26 market: ~$125M cap spend / ~20 WAR)
LEAGUE_MINIMUM      = 1_119_563   # approximate 2025-26 minimum salary
POINTS_PER_WIN      = 33.5        # Pythagorean pts-per-win over full season
EXPECTED_GAMES      = 72          # standard projected season for contract valuation
DPM_IMPROVEMENT_CAP = 1.5         # max single-year DARKO improvement applied (avoid overreacting to noise)
DARKO_WEIGHT        = 0.7         # weight for DARKO DPM in composite skill blend
EPM_WEIGHT          = 0.3         # weight for EPM in composite skill blend
LEAGUE_AVG_USG      = 25.0        # primary ball-handler threshold — players below this are discounted

output_folder = "PlayerValue"
os.makedirs(output_folder, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def normalize_name(name: str) -> str:
    name = unicodedata.normalize("NFD", str(name))
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = re.sub(r"\s+(jr\.?|sr\.?|ii+|iii+|iv)$", "", name.strip(), flags=re.IGNORECASE)
    return name.lower().strip()


def age_dpm_delta(age: float) -> float:
    """
    Expected annual DPM change based on the NBA aging curve.
    Players improve through ~age 26-27, plateau, then decline.
    Based on published aging curve research (peak ≈ 26.5 yrs).
    """
    if pd.isna(age):
        return -0.10   # unknown age → assume mild decline
    if age < 22:
        return  0.30   # rapid development
    if age < 24:
        return  0.15   # continued growth
    if age < 26:
        return  0.05   # approaching peak
    if age < 28:
        return -0.05   # peak / very slight decline
    if age < 30:
        return -0.15   # post-peak decline
    if age < 32:
        return -0.25   # accelerating decline
    if age < 34:
        return -0.35
    return -0.50       # steep decline 34+


def fmt_money(x) -> str:
    if pd.isna(x):
        return ""
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def assign_tier(surplus, war) -> str:
    if pd.isna(war) or war < 0:
        return "Replacement Level"
    if pd.isna(surplus):
        return "No Contract Data"
    if surplus > 20_000_000:
        return "Elite Bargain"
    if surplus > 10_000_000:
        return "Great Value"
    if surplus > 0:
        return "Good Value"
    if surplus > -8_000_000:
        return "Fair Value"
    if surplus > -20_000_000:
        return "Overpaid"
    return "Significantly Overpaid"


# ── Loaders ───────────────────────────────────────────────────────────────────
def load_darko() -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join("DARKO_stats", "darko_talent_processed_*.xlsx")), reverse=True)
    if not files:
        raise FileNotFoundError("No DARKO Excel found in DARKO_stats/. Run DARKO.py first.")
    path = files[0]
    print(f"  DARKO  ← {path}")
    return pd.read_excel(path, sheet_name="All_Players")


def load_contracts() -> pd.DataFrame:
    path = os.path.join("Contracts", "basketball_reference_contracts_with_teams.xlsx")
    if not os.path.exists(path):
        raise FileNotFoundError("No contracts Excel found in Contracts/. Run Contracts.py first.")
    print(f"  Salary ← {path}")
    df = pd.read_excel(path, sheet_name="All Players")

    # Identify all season columns (e.g. "2025-26", "2026-27", ...)
    season_cols = [c for c in df.columns if re.match(r"\d{4}-\d{2}$", c)]
    if not season_cols:
        raise RuntimeError(f"No season salary columns found. Available: {df.columns.tolist()}")

    # Ensure current season is first; fall back gracefully
    if CURRENT_SEASON not in season_cols:
        print(f"  Warning: '{CURRENT_SEASON}' not found, using '{season_cols[0]}' as current")
    current_col = CURRENT_SEASON if CURRENT_SEASON in season_cols else season_cols[0]

    # Parse all season money strings → floats
    for col in season_cols:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(r"[\$,]", "", regex=True),
            errors="coerce"
        )

    print(f"  {df[current_col].notna().sum()} players with salary data | {len(season_cols)} contract years")
    keep = ["Player", current_col] + [c for c in season_cols if c != current_col]
    return df[keep].rename(columns={current_col: "salary"})


def fetch_bbr_pergame() -> pd.DataFrame:
    """Only live fetch needed — no existing script covers minutes played or age."""
    print(f"  Minutes ← {BBR_STATS_URL}")
    df = pd.read_html(BBR_STATS_URL)[0]
    df = df[pd.to_numeric(df["Rk"], errors="coerce").notna()]
    df["G"]   = pd.to_numeric(df["G"],   errors="coerce")
    df["MP"]  = pd.to_numeric(df["MP"],  errors="coerce")
    df["Age"] = pd.to_numeric(df["Age"], errors="coerce")
    # Traded players: BBR lists TOT row first — keep it
    df = df.drop_duplicates(subset="Player", keep="first")
    print(f"  {len(df)} players with minutes/age data")
    return df[["Player", "G", "MP", "Age"]].copy()


def load_epm() -> pd.DataFrame:
    """Load EPM (Effective Plus-Minus) from the Excel produced by epm.py."""
    files = sorted(glob.glob(os.path.join("EPM_stats", "epm_players_by_team_*.xlsx")), reverse=True)
    if not files:
        print("  Warning: No EPM Excel found in EPM_stats/. Run epm.py first. Using DARKO DPM only.")
        return pd.DataFrame()
    path = files[0]
    print(f"  EPM    ← {path}")
    df = pd.read_excel(path, sheet_name="All Players")
    # tot = total EPM, off = offensive EPM, def = defensive EPM, p_usg = actual-season usage rate
    want_cols = {"player_name", "tot", "off", "def"} | ({"p_usg"} if "p_usg" in df.columns else set())
    df = df[[c for c in df.columns if c in want_cols]].copy()
    rename = {"player_name": "Player", "tot": "EPM", "off": "O-EPM", "def": "D-EPM", "p_usg": "epm_usg"}
    df = df.rename(columns=rename)
    for col in ("EPM", "O-EPM", "D-EPM"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "epm_usg" in df.columns:
        df["epm_usg"] = pd.to_numeric(df["epm_usg"], errors="coerce")
        # EPM stores usage as a decimal (0–1); convert to percentage points if needed
        if df["epm_usg"].dropna().max() <= 1.0:
            df["epm_usg"] = df["epm_usg"] * 100
    print(f"  {df['EPM'].notna().sum()} players with EPM data")
    return df


# ── Main ──────────────────────────────────────────────────────────────────────
print("=" * 55)
print("Loading data...")
print("=" * 55)

darko     = load_darko()
contracts = load_contracts()
bbr_stats = fetch_bbr_pergame()
epm_data  = load_epm()

# Identify future season columns from contracts (all except "salary" = current)
future_season_cols = [c for c in contracts.columns if re.match(r"\d{4}-\d{2}$", c)]

# Normalize names for cross-source matching
for df_ in (darko, contracts, bbr_stats):
    df_["_key"] = df_["Player"].map(normalize_name)

# Deduplicate each source on _key — traded players or scraping artifacts
# can produce multiple rows; keep the first (highest-minutes for BBR, first
# listed for DARKO/contracts which are already sorted by relevance).
darko     = darko.drop_duplicates(subset="_key", keep="first")
contracts = contracts.drop_duplicates(subset="_key", keep="first")
bbr_stats = bbr_stats.drop_duplicates(subset="_key", keep="first")

# Merge: DARKO is the spine
merged = darko.merge(bbr_stats[["_key", "G", "MP", "Age"]], on="_key", how="left")
merged = merged.merge(contracts[["_key", "salary"] + future_season_cols], on="_key", how="left")

# Merge EPM data if available
if not epm_data.empty:
    epm_data["_key"] = epm_data["Player"].map(normalize_name)
    epm_data = epm_data.drop_duplicates(subset="_key", keep="first")
    epm_merge_cols = ["_key", "EPM", "O-EPM", "D-EPM"]
    if "epm_usg" in epm_data.columns:
        epm_merge_cols.append("epm_usg")
    merged = merged.merge(epm_data[epm_merge_cols], on="_key", how="left")
    epm_matched = merged["EPM"].notna().sum()
    print(f"  EPM matched to {epm_matched} / {len(merged)} players")
    # Prefer EPM's actual-season USG% over DARKO's projected USG%
    if "epm_usg" in merged.columns:
        darko_usg = "USG%" if "USG%" in merged.columns else None
        if darko_usg:
            # DARKO may store USG% as strings ("20.5%" or "0.205") — convert first
            darko_usg_numeric = pd.to_numeric(
                merged[darko_usg].astype(str).str.rstrip("%"), errors="coerce"
            )
            merged["USG%"] = merged["epm_usg"].fillna(darko_usg_numeric)
        else:
            merged["USG%"] = merged["epm_usg"]
        merged.drop(columns=["epm_usg"], inplace=True)
        # Final safety: ensure numeric and convert 0-1 decimal to percentage if needed
        merged["USG%"] = pd.to_numeric(merged["USG%"], errors="coerce")
        if merged["USG%"].dropna().max() <= 1.0:
            merged["USG%"] = merged["USG%"] * 100
        print(f"  USG%: {merged['USG%'].notna().sum()} players (EPM actual-season, DARKO fallback)")
else:
    merged["EPM"]   = float("nan")
    merged["O-EPM"] = float("nan")
    merged["D-EPM"] = float("nan")

merged.drop(columns="_key", inplace=True)

# Final safety dedup — catches any fan-out from many-to-many key collisions
before = len(merged)
merged = merged.drop_duplicates(subset="Player", keep="first")
if len(merged) < before:
    print(f"  Removed {before - len(merged)} duplicate player rows after merge")

# ── Value model (keep numeric until after sort) ───────────────────────────────
merged["G"]   = merged["G"].fillna(0).astype(int)
merged["MP"]  = merged["MP"].fillna(0)
merged["Age"] = pd.to_numeric(merged["Age"], errors="coerce")
merged["actual_MP"]    = (merged["G"] * merged["MP"]).round(0)
merged["projected_MP"] = (merged["MP"] * EXPECTED_GAMES).round(0)

# Trajectory label from DARKO's own improvement signal
merged["trajectory"] = merged["DPM Improvement"].apply(
    lambda x: "Trending Up" if pd.notna(x) and x > 0.3
    else ("Trending Down" if pd.notna(x) and x < -0.3
    else "Stable")
)

# ── Composite skill: weighted blend of DARKO DPM and EPM ─────────────────────
# Weights are normalized so the result is always a proper weighted average,
# regardless of what the raw weight values sum to.
# If EPM is missing for a player, fall back to DARKO DPM alone.
_total_weight = DARKO_WEIGHT + EPM_WEIGHT
has_epm = merged["EPM"].notna()
merged["composite_skill"] = merged["DPM"].copy()   # default: DARKO only
merged.loc[has_epm, "composite_skill"] = (
    (DARKO_WEIGHT * merged.loc[has_epm, "DPM"] +
     EPM_WEIGHT   * merged.loc[has_epm, "EPM"]) / _total_weight
).round(3)
merged["epm_used"] = has_epm   # flag so readers know which players had EPM

n_blended = has_epm.sum()
n_darko_only = (~has_epm).sum()
print(f"  Composite skill: {n_blended} players blended (DARKO+EPM), "
      f"{n_darko_only} DARKO-only (no EPM match)")

# WAR = (composite_skill above replacement) × projected_possessions / points_per_win
# = (composite_skill + 2) * projected_MP / (48 * 33.5)
merged["WAR"] = (
    (merged["composite_skill"] - REPLACEMENT_DPM) * merged["projected_MP"] / (48 * POINTS_PER_WIN)
).round(2)

# ── Usage-based market-value adjustment ──────────────────────────────────────
# EPM/DPM measure per-possession quality, not volume. A role player at 10% USG
# posting good efficiency would never command a star's salary on the open market.
# We apply a usage scalar to fair_salary only — WAR and composite_skill stay pure.
#   scalar = sqrt(USG% / 25) → clamped to [0.55, 1.00]
#   Reference is 25% (primary ball-handler threshold).
#   Square root gives a gentler curve — role players aren't over-penalized.
#   10% USG → ×0.55 (floor)  |  15% → ×0.77  |  18% → ×0.85  |  22% → ×0.94  |  25%+ → ×1.00
has_usg = merged["USG%"].notna() if "USG%" in merged.columns else pd.Series(False, index=merged.index)
usage_scalar = pd.Series(1.0, index=merged.index)
if has_usg.any():
    usage_scalar[has_usg] = (
        (merged.loc[has_usg, "USG%"] / LEAGUE_AVG_USG)
        .clip(lower=0.0, upper=1.0)
        .apply(lambda x: x ** 0.5)     # sqrt — gentler curve for low-usage players
        .clip(lower=0.55, upper=1.0)   # floor at 0.55, never inflate above 1.0
    )
merged["usage_scalar"] = usage_scalar.round(3)

merged["fair_salary"] = (
    merged["WAR"].clip(lower=0) * MARKET_RATE_PER_WIN * merged["usage_scalar"] + LEAGUE_MINIMUM
).round(0)

merged["surplus"] = (merged["fair_salary"] - merged["salary"]).round(0)
merged["$/WAR"]   = (merged["salary"] / merged["WAR"].clip(lower=0.01)).round(0)

merged["value_tier"] = merged.apply(lambda r: assign_tier(r["surplus"], r["WAR"]), axis=1)

# ── Multi-year contract outlook ───────────────────────────────────────────────
# Year 1: use DARKO's own DPM Improvement (its built-in predictive signal).
# Years 2+: chain year-by-year using the NBA age-based aging curve.
#   Young players get positive deltas; veterans get negative ones.
#   Chaining means year-3 starts from year-2's projected DPM, not current DPM.

# Start multi-year projections from composite_skill (blended DARKO+EPM baseline),
# then apply DARKO's trajectory signal / aging curve from that point forward.
projected_dpm = merged["composite_skill"].copy()   # carries forward each iteration

for i, yr_col in enumerate(future_season_cols, start=1):
    if i == 1:
        # Year 1: DARKO's own trajectory signal (capped to avoid noise amplification)
        annual_delta = merged["DPM Improvement"].clip(
            lower=-DPM_IMPROVEMENT_CAP, upper=DPM_IMPROVEMENT_CAP
        ).fillna(0)
    else:
        # Years 2+: age-based curve applied at player's projected age that year
        age_at_year = merged["Age"] + (i - 1)
        annual_delta = age_at_year.apply(age_dpm_delta)

    projected_dpm = (projected_dpm + annual_delta).clip(lower=-6, upper=10)

    projected_war = (
        (projected_dpm - REPLACEMENT_DPM) * merged["projected_MP"] / (48 * POINTS_PER_WIN)
    ).clip(lower=0)
    projected_fair = (
        projected_war * MARKET_RATE_PER_WIN * merged["usage_scalar"] + LEAGUE_MINIMUM
    ).round(0)
    projected_surplus = (projected_fair - merged[yr_col]).round(0)

    merged[f"surplus_{yr_col}"] = projected_surplus
    merged[f"outlook_{yr_col}"] = projected_surplus.apply(
        lambda s: "Underpaid" if pd.notna(s) and s > 5_000_000
        else ("Overpaid" if pd.notna(s) and s < -8_000_000
        else ("Fair" if pd.notna(s) else ""))
    )

# Sort best surplus first — before money columns become strings
merged = merged.sort_values("surplus", ascending=False, na_position="last")

# ── Tier summary ──────────────────────────────────────────────────────────────
tier_order = [
    "Elite Bargain", "Great Value", "Good Value",
    "Fair Value", "Overpaid", "Significantly Overpaid",
    "Replacement Level", "No Contract Data",
]
tier_summary = (
    merged["value_tier"].value_counts()
    .reindex(tier_order).dropna()
    .reset_index()
)
tier_summary.columns = ["Tier", "Player Count"]

print("\nValue tier breakdown:")
print(tier_summary.to_string(index=False))

# ── Format money columns for display ─────────────────────────────────────────
money_cols = (["salary", "fair_salary", "surplus", "$/WAR"]
              + future_season_cols
              + [f"surplus_{c}" for c in future_season_cols])
for col in money_cols:
    if col in merged.columns:
        merged[col] = merged[col].apply(fmt_money)

# ── Write Excel ───────────────────────────────────────────────────────────────
year = datetime.now().year
output_file = os.path.join(output_folder, f"player_value_{year}.xlsx")

# Core value columns — EPM columns inserted after DARKO DPM columns
value_cols = [
    "Player", "Team", "Age",
    "DPM", "O-DPM", "D-DPM", "DPM Improvement", "trajectory",
    "EPM", "O-EPM", "D-EPM",
    "composite_skill", "epm_used",
    "USG%", "usage_scalar", "G", "projected_MP", "WAR",
    "salary", "fair_salary", "surplus", "$/WAR", "value_tier",
]
value_cols = [c for c in value_cols if c in merged.columns]

# Future-year outlook columns (surplus + label for each remaining contract year)
outlook_cols = []
for yr_col in future_season_cols:
    for prefix in (f"surplus_{yr_col}", f"outlook_{yr_col}", yr_col):
        if prefix in merged.columns:
            outlook_cols.append(prefix)

summary_cols = value_cols + outlook_cols

tier_formats_cfg = {
    "Elite Bargain":          {"bg_color": "#1a7f37", "font_color": "#ffffff", "bold": True},
    "Great Value":            {"bg_color": "#2ea44f", "font_color": "#ffffff"},
    "Good Value":             {"bg_color": "#a2d9a5"},
    "Fair Value":             {"bg_color": "#ffffcc"},
    "Overpaid":               {"bg_color": "#f9c8c8"},
    "Significantly Overpaid": {"bg_color": "#d73a49", "font_color": "#ffffff", "bold": True},
    "Replacement Level":      {"bg_color": "#e8e8e8", "font_color": "#666666"},
    "No Contract Data":       {"bg_color": "#ffffff", "font_color": "#aaaaaa", "italic": True},
}

with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
    wb = writer.book
    tier_fmts = {k: wb.add_format(v) for k, v in tier_formats_cfg.items()}
    tier_col_idx = summary_cols.index("value_tier")

    # Value Summary (colour-coded tiers, auto-width)
    merged[summary_cols].to_excel(writer, sheet_name="Value Summary", index=False)
    ws = writer.sheets["Value Summary"]
    for row_idx, tier in enumerate(merged["value_tier"], start=1):
        if tier in tier_fmts:
            ws.write(row_idx, tier_col_idx, tier, tier_fmts[tier])
    for i, col in enumerate(summary_cols):
        ws.set_column(i, i, min(merged[col].astype(str).map(len).max() + 2, 30))

    # Full data
    merged.to_excel(writer, sheet_name="All Players (Full)", index=False)

    # Tier summary
    tier_summary.to_excel(writer, sheet_name="Tier Summary", index=False)

    # Per-team sheets
    for team in sorted(merged["Team"].dropna().unique()):
        merged[merged["Team"] == team][summary_cols].to_excel(
            writer, sheet_name=str(team)[:31], index=False
        )

n_with_salary = merged["salary"].apply(bool).sum()
print(f"\n✅ Saved to: {output_file}")
print(f"   {len(merged)} players | {n_with_salary} with salary | {len(merged) - n_with_salary} without")
