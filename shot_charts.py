"""
shot_charts.py
--------------
Fetches per-player shot chart data from the NBA Stats API for the current season.
Uses the nba_api package to pull individual shot coordinates and aggregates them
into zone summaries used by the value dashboard.

Outputs (in ShotCharts/):
  shots_raw_YYYY.xlsx   — one row per shot (coordinates, zone, made/missed)
  shot_zones_YYYY.xlsx  — zone summary per player (% shots + FG% by zone)

Install dependency first:
  pip install nba_api

Usage:
  python shot_charts.py               # fetch only new players (default)
  python shot_charts.py --days 1      # also refresh players whose last game was yesterday or earlier
  python shot_charts.py --days 7      # refresh anyone who might have played in the last week
  python shot_charts.py --refresh-all # re-fetch every player from scratch

Run order in pipeline: ... → PlayerValue.py → shot_charts.py → (dashboard reads both)
"""

import argparse
import glob
import os
import time
from datetime import date, timedelta

import pandas as pd

SEASON     = "2025-26"
OUTPUT_DIR = "ShotCharts"
DELAY      = 1.0   # seconds between requests — NBA API rate-limits aggressively

os.makedirs(OUTPUT_DIR, exist_ok=True)

# PlayerValue name → nba_api name when they differ
NAME_ALIASES = {
    "A.J. Green":         "AJ Green",
    "AJ Lawson":          "A.J. Lawson",
    "Carlton Carrington": "Bub Carrington",
    "Alexandre Sarr":     "Alex Sarr",
    "Nicolas Claxton":    "Nic Claxton",
}

# Zone labels as returned by the NBA API
ZONES = [
    ("restricted_area", ["Restricted Area"]),
    ("paint_nonra",     ["In The Paint (Non-RA)"]),
    ("midrange",        ["Mid-Range"]),
    ("corner3",         ["Left Corner 3", "Right Corner 3"]),
    ("above_break3",    ["Above the Break 3"]),
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_player_id(name: str):
    """Map a player name to their NBA Stats player ID. Returns None if not found."""
    from nba_api.stats.static import players as nba_players
    results = nba_players.find_players_by_full_name(name)
    if not results:
        # Try partial match on last name
        parts = name.strip().split()
        if parts:
            results = nba_players.find_players_by_last_name(parts[-1])
            # Filter by first name prefix
            if len(parts) > 1:
                results = [p for p in results
                           if p["full_name"].lower().startswith(parts[0].lower())]
    if not results:
        return None
    active = [p for p in results if p.get("is_active")]
    return (active or results)[0]["id"]


def _fetch_shots(player_id: int, season: str = SEASON) -> pd.DataFrame:
    """Fetch all FGA records for one player. Returns empty DataFrame on error."""
    from nba_api.stats.endpoints import shotchartdetail
    try:
        chart = shotchartdetail.ShotChartDetail(
            team_id=0,
            player_id=player_id,
            season_nullable=season,
            season_type_all_star="Regular Season",
            context_measure_simple="FGA",
        )
        return chart.get_data_frames()[0]
    except Exception as exc:
        print(f"      API error: {exc}")
        return pd.DataFrame()


def _zone_summary(player: str, shots: pd.DataFrame) -> dict:
    """Compute per-zone FGA%, FGM, FGA, FG% from raw shot rows."""
    total = len(shots)
    row = {"Player": player, "total_fga": total}
    for key, labels in ZONES:
        mask      = shots["SHOT_ZONE_BASIC"].isin(labels)
        zone_df   = shots[mask]
        n         = len(zone_df)
        made      = int(zone_df["SHOT_MADE_FLAG"].sum()) if n else 0
        row[f"pct_{key}"]    = round(n / total, 4) if total else 0.0
        row[f"fga_{key}"]    = n
        row[f"fgm_{key}"]    = made
        row[f"fg_pct_{key}"] = round(made / n, 4) if n else 0.0
    return row


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch NBA shot chart data")
    parser.add_argument(
        "--days", type=int, default=0,
        help="Re-fetch players whose last recorded game is this many days ago or more. "
             "E.g. --days 1 refreshes anyone who played yesterday or earlier today."
    )
    parser.add_argument(
        "--refresh-all", action="store_true",
        help="Re-fetch every player from scratch (ignores existing data)."
    )
    args = parser.parse_args()

    # Load player list from the latest PlayerValue output
    pv_files = sorted(
        glob.glob(os.path.join("PlayerValue", "player_value_*.xlsx")), reverse=True
    )
    if not pv_files:
        raise FileNotFoundError("Run PlayerValue.py first — no player_value_*.xlsx found.")

    player_df = pd.read_excel(pv_files[0], sheet_name="Value Summary")
    players   = player_df["Player"].dropna().unique().tolist()

    raw_path  = os.path.join(OUTPUT_DIR, f"shots_raw_{SEASON.replace('-','_')}.xlsx")
    zone_path = os.path.join(OUTPUT_DIR, f"shot_zones_{SEASON.replace('-','_')}.xlsx")

    # Load already-fetched data
    done_players  = set()
    existing_raw  = pd.DataFrame()
    existing_zones = pd.DataFrame()

    if not args.refresh_all and os.path.exists(raw_path):
        existing_raw  = pd.read_excel(raw_path)
        done_players  = set(existing_raw["Player"].unique())
        if os.path.exists(zone_path):
            existing_zones = pd.read_excel(zone_path)

    # ── Staleness check: re-fetch players with outdated game data ─────────────
    stale_players = set()
    if args.days > 0 and not args.refresh_all and not existing_raw.empty:
        cutoff = date.today() - timedelta(days=args.days)
        if "GAME_DATE" in existing_raw.columns:
            last_game = (
                existing_raw.groupby("Player")["GAME_DATE"]
                .max()
                .apply(lambda d: pd.to_datetime(d, errors="coerce").date() if pd.notna(d) else None)
            )
            stale_players = {
                p for p, d in last_game.items()
                if d is not None and d <= cutoff
            }
            if stale_players:
                print(f"Stale players (last game on or before {cutoff}): {len(stale_players)}")
                # Remove stale players from done_players so they get re-fetched
                done_players -= stale_players
                # Strip their old rows from the existing data
                existing_raw   = existing_raw[~existing_raw["Player"].isin(stale_players)]
                if not existing_zones.empty:
                    existing_zones = existing_zones[~existing_zones["Player"].isin(stale_players)]

    new_players = [p for p in players if p not in done_players]

    mode_note = ""
    if args.refresh_all:
        mode_note = "  (mode: full refresh)"
    elif args.days > 0:
        mode_note = f"  (mode: refresh players with games on or before {date.today() - timedelta(days=args.days)})"

    print(f"Total players in model : {len(players)}{mode_note}")
    print(f"Already have shot data : {len(done_players)}")
    if stale_players:
        print(f"Refreshing stale       : {len(stale_players)}")
    print(f"Need to fetch          : {len(new_players)}")

    if not new_players:
        print("\nAll players already have shot data — nothing to do.")
        print("Tip: use --days 1 to refresh players who played recently.")
        exit(0)

    print(f"Estimated time: ~{len(new_players) * DELAY / 60:.0f} minutes\n")

    all_shots = [existing_raw] if not existing_raw.empty else []
    zone_rows = existing_zones.to_dict("records") if not existing_zones.empty else []
    fetched   = 0

    for i, name in enumerate(new_players):
        lookup_name = NAME_ALIASES.get(name, name)
        pid = _get_player_id(lookup_name)
        if pid is None:
            print(f"  [{i+1}/{len(new_players)}] {name} — ID not found, skipping")
            continue

        shots = _fetch_shots(pid)
        time.sleep(DELAY)

        if shots.empty:
            print(f"  [{i+1}/{len(new_players)}] {name} — no shots returned")
            continue

        shots["Player"] = name
        keep_cols = [c for c in
                     ["Player", "GAME_DATE", "LOC_X", "LOC_Y", "SHOT_MADE_FLAG",
                      "SHOT_ZONE_BASIC", "SHOT_ZONE_AREA",
                      "SHOT_DISTANCE", "ACTION_TYPE"]
                     if c in shots.columns]
        all_shots.append(shots[keep_cols])
        zone_rows.append(_zone_summary(name, shots))
        fetched += 1

        print(f"  [{i+1}/{len(new_players)}] {name} — {len(shots)} shots")

        # Checkpoint every 50 new players so a crash doesn't lose everything
        if fetched % 50 == 0:
            _raw_save  = pd.concat(all_shots,  ignore_index=True)
            _zone_save = pd.DataFrame(zone_rows)
            _raw_save.to_excel(raw_path,  index=False)
            _zone_save.to_excel(zone_path, index=False)
            print(f"  ── checkpoint saved ({fetched} new players) ──")

    # Only write files if something new was actually added
    if fetched == 0:
        print("\nNo new shot data fetched — files unchanged.")
    else:
        raw_df = pd.concat(all_shots, ignore_index=True)
        raw_df.to_excel(raw_path, index=False)
        print(f"\nRaw shots → {raw_path}  ({len(raw_df):,} rows, {fetched} players updated)")

        zone_df = pd.DataFrame(zone_rows)
        zone_df.to_excel(zone_path, index=False)
        print(f"Zone summary → {zone_path}  ({len(zone_df)} players total)")

    print("\nDone. Re-run PlayerValue.py to merge zone data into the dashboard.")
