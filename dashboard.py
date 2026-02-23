"""
dashboard.py — NBA Player Contract Value Dashboard
Run with:  streamlit run dashboard.py
Reads the Excel produced by PlayerValue.py (run that first).
"""

import glob
import os
import re
import subprocess
import sys
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
CURRENT_SEASON = "2025-26"

TIER_ORDER = [
    "Elite Bargain", "Great Value", "Good Value",
    "Fair Value", "Overpaid", "Significantly Overpaid",
    "Replacement Level", "No Contract Data",
]
TIER_COLORS = {
    "Elite Bargain":          "#1a7f37",
    "Great Value":            "#2ea44f",
    "Good Value":             "#a2d9a5",
    "Fair Value":             "#f0f0a0",
    "Overpaid":               "#f9c8c8",
    "Significantly Overpaid": "#d73a49",
    "Replacement Level":      "#c8c8c8",
    "No Contract Data":       "#eeeeee",
}
TIER_TEXT_COLORS = {
    "Elite Bargain": "#ffffff", "Great Value": "#ffffff",
    "Significantly Overpaid": "#ffffff",
}

TEAM_SHORT_TO_FULL = {
    "Atlanta": "Atlanta Hawks", "Boston": "Boston Celtics",
    "Brooklyn": "Brooklyn Nets", "Charlotte": "Charlotte Hornets",
    "Chicago": "Chicago Bulls", "Cleveland": "Cleveland Cavaliers",
    "Dallas": "Dallas Mavericks", "Denver": "Denver Nuggets",
    "Detroit": "Detroit Pistons", "Golden State": "Golden State Warriors",
    "Houston": "Houston Rockets", "Indiana": "Indiana Pacers",
    "LA Clippers": "Los Angeles Clippers", "LA Lakers": "Los Angeles Lakers",
    "Memphis": "Memphis Grizzlies", "Miami": "Miami Heat",
    "Milwaukee": "Milwaukee Bucks", "Minnesota": "Minnesota Timberwolves",
    "New Orleans": "New Orleans Pelicans", "New York": "New York Knicks",
    "Oklahoma City": "Oklahoma City Thunder", "Orlando": "Orlando Magic",
    "Philadelphia": "Philadelphia 76ers", "Phoenix": "Phoenix Suns",
    "Portland": "Portland Trail Blazers", "Sacramento": "Sacramento Kings",
    "San Antonio": "San Antonio Spurs", "Toronto": "Toronto Raptors",
    "Utah": "Utah Jazz", "Washington": "Washington Wizards",
}

TIER_ATTAINABILITY = {
    "Elite Bargain":          ("Very Hard",   0.10),
    "Great Value":            ("Hard",        0.25),
    "Good Value":             ("Moderate",    0.50),
    "Fair Value":             ("Likely",      0.70),
    "Overpaid":               ("Very Likely", 0.85),
    "Significantly Overpaid": ("Very Likely", 0.90),
    "Replacement Level":      ("Likely",      0.65),
    "No Contract Data":       ("Unknown",     0.40),
}

ATTAINABILITY_COLORS = {
    "Very Likely": "#1a7f37",
    "Likely":      "#2ea44f",
    "Moderate":    "#f0a500",
    "Hard":        "#e07020",
    "Very Hard":   "#d73a49",
    "Unknown":     "#888888",
}

# Known aliases → canonical name in the dataset.
# Add entries here when a player is commonly searched by a different name.
PLAYER_ALIASES = {
    "Nah'Shon Hyland": "Bones Hyland",
    "Nahshon Hyland":  "Bones Hyland",
}


def _player_options(player_list: list) -> list:
    """Returns the player list with alias entries appended (sorted separately)."""
    extras = sorted(
        alias for alias, canon in PLAYER_ALIASES.items() if canon in player_list
    )
    return player_list + extras


def _resolve_player(name: str) -> str:
    """Resolves an alias to the canonical dataset name."""
    return PLAYER_ALIASES.get(name, name)

st.set_page_config(
    page_title="NBA Contract Value",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_money(s) -> float:
    if pd.isna(s) or str(s).strip() in ("", "nan"):
        return float("nan")
    return float(str(s).replace("$", "").replace(",", "").replace("-", "-").strip())


def money_str(v) -> str:
    if pd.isna(v):
        return "—"
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _norm(name: str) -> str:
    """Lightweight name normaliser for measurement merge (mirrors measurements.py)."""
    import unicodedata as _ud
    if not isinstance(name, str):
        return ""
    name = _ud.normalize("NFD", name)
    name = "".join(c for c in name if _ud.category(c) != "Mn")
    name = re.sub(r"\s+(jr\.?|sr\.?|ii+|iii+|iv)$", "", name.strip(), flags=re.IGNORECASE)
    return name.lower().strip()


# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    files = sorted(glob.glob(os.path.join("PlayerValue", "player_value_*.xlsx")), reverse=True)
    if not files:
        return None, None, None
    path = files[0]
    df       = pd.read_excel(path, sheet_name="Value Summary")
    tier_df  = pd.read_excel(path, sheet_name="Tier Summary")
    full_df  = pd.read_excel(path, sheet_name="All Players (Full)")

    # Detect future season columns
    future_cols = sorted([c for c in df.columns if re.match(r"\d{4}-\d{2}$", c)])

    # Parse all money columns to numeric (_num suffix)
    money_re = re.compile(r"^\$|^-\$")
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(5)
        if sample.apply(lambda x: bool(money_re.match(x))).any():
            df[f"{col}__n"] = df[col].apply(parse_money)

    # Ensure numeric DPM/EPM/WAR/style stats
    for col in ("DPM", "O-DPM", "D-DPM", "EPM", "O-EPM", "D-EPM",
                "composite_skill", "WAR", "G", "projected_MP", "USG%", "usage_scalar",
                "PTS", "TRB", "AST", "STL", "BLK", "TOV", "3PA", "3P%", "FTA", "FT%"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Round skill/rating columns to 2 decimal places for clean display
    for col in ("DPM", "O-DPM", "D-DPM", "DPM Improvement",
                "EPM", "O-EPM", "D-EPM", "composite_skill", "WAR", "USG%", "usage_scalar"):
        if col in df.columns:
            df[col] = df[col].round(2)

    # Age as whole number
    if "Age" in df.columns:
        df["Age"] = pd.to_numeric(df["Age"], errors="coerce").round(0).astype("Int64")

    # ── Merge physical measurements if available ──────────────────────────────
    meas_files = sorted(
        glob.glob(os.path.join("Measurements", "player_measurements_*.xlsx")), reverse=True
    )
    if meas_files:
        meas = pd.read_excel(meas_files[0], sheet_name="Measurements")
        for col in ("Height_in", "Wingspan_in", "Weight_lbs", "ArmLength_in"):
            if col in meas.columns:
                meas[col] = pd.to_numeric(meas[col], errors="coerce")
        meas["_key"] = meas["Player"].apply(_norm)
        df["_key"]   = df["Player"].apply(_norm)
        meas_keep = ["_key"] + [c for c in
                     ("Height_in", "Wingspan_in", "Weight_lbs", "ArmLength_in",
                      "Height_display", "Wingspan_display", "Position")
                     if c in meas.columns]
        df = df.merge(meas[meas_keep].drop_duplicates("_key"), on="_key", how="left")
        df.drop(columns=["_key"], inplace=True)

    return df, tier_df, future_cols


@st.cache_data
def load_team_stats():
    path = os.path.join("Team_stats", "nba_2025_2026_team_stats_sorted_with_rank_filled.xlsx")
    if not os.path.exists(path):
        return None
    ts = pd.read_excel(path, sheet_name="Original")
    ts["Team_full"] = ts["TEAM"].map(TEAM_SHORT_TO_FULL)
    keep = ["Team_full", "oEFF", "dEFF", "eDIFF", "PACE", "PPG", "oPPG", "W", "L"]
    ts = ts[[c for c in keep if c in ts.columns]].dropna(subset=["Team_full"])
    for col in ("oEFF", "dEFF", "eDIFF", "PPG", "oPPG"):
        ts[col] = pd.to_numeric(ts[col], errors="coerce")
    # Ranks: oEFF rank 1 = best offense; dEFF rank 1 = best defense (lowest allowed)
    ts["oEFF_rank"] = ts["oEFF"].rank(ascending=False).astype(int)
    ts["dEFF_rank"] = ts["dEFF"].rank(ascending=True).astype(int)   # low dEFF = good
    ts["net_rank"]  = ts["eDIFF"].rank(ascending=False).astype(int)
    return ts.set_index("Team_full")


def compute_team_profiles(player_df):
    ts = load_team_stats()
    results = []
    for team, grp in player_df.groupby("Team"):
        # Weight by projected minutes — use top 8 contributors
        top8 = grp.nlargest(8, "projected_MP")
        total_mp = top8["projected_MP"].sum()
        def wavg(col):
            s = top8[col]
            w = top8["projected_MP"]
            valid = s.notna() & w.notna()
            if valid.sum() == 0:
                return float("nan")
            return (s[valid] * w[valid]).sum() / w[valid].sum()

        row = {
            "Team":         team,
            "w_composite":  wavg("composite_skill"),
            "w_o_epm":      wavg("O-EPM"),
            "w_d_epm":      wavg("D-EPM"),
            "w_dpm":        wavg("DPM"),
            "total_war":    grp["WAR"].sum(),
            "n_players":    len(grp),
        }
        if "salary__n" in player_df.columns:
            row["total_salary"] = grp["salary__n"].sum()
        results.append(row)

    profiles = pd.DataFrame(results).set_index("Team")

    # Ranks within player-derived stats
    profiles["composite_rank"] = profiles["w_composite"].rank(ascending=False).astype(int)
    profiles["o_epm_rank"]     = profiles["w_o_epm"].rank(ascending=False).astype(int)
    profiles["d_epm_rank"]     = profiles["w_d_epm"].rank(ascending=False).astype(int)

    # Merge team-level efficiency stats
    if ts is not None:
        profiles = profiles.join(ts[["oEFF", "dEFF", "eDIFF", "oEFF_rank", "dEFF_rank", "W", "L"]], how="left")

    # Need scores 0–10: higher = more need
    n = len(profiles)
    denom = max(n - 1, 1)
    profiles["off_need"] = (
        ((profiles["oEFF_rank"] - 1) / denom) * 7 +
        ((profiles["o_epm_rank"] - 1) / denom) * 3
    ).clip(0, 10).round(1)
    profiles["def_need"] = (
        ((n - profiles["dEFF_rank"]) / denom) * 7 +   # high dEFF rank = bad defense
        ((profiles["d_epm_rank"] - 1) / denom) * 3
    ).clip(0, 10).round(1)
    profiles["skill_need"] = (
        ((profiles["composite_rank"] - 1) / denom) * 10
    ).clip(0, 10).round(1)

    def need_label(score):
        if score >= 6:  return ("High",   "#d73a49")
        if score >= 4:  return ("Medium", "#f0a500")
        return              ("Low",    "#1a7f37")

    profiles["off_label"],   profiles["off_color"]   = zip(*profiles["off_need"].map(need_label))
    profiles["def_label"],   profiles["def_color"]   = zip(*profiles["def_need"].map(need_label))
    profiles["skill_label"], profiles["skill_color"] = zip(*profiles["skill_need"].map(need_label))
    return profiles


df, tier_df, future_cols = load_data()

if df is None:
    st.error("No data found. Run `PlayerValue.py` first to generate data.")
    st.stop()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏀 NBA Contract Value")
    st.markdown("---")

    teams = ["All Teams"] + sorted(df["Team"].dropna().unique().tolist())
    sel_team = st.selectbox("Team", teams)

    _base_players = sorted(df["Player"].dropna().unique().tolist())
    all_players = ["All Players"] + _player_options(_base_players)
    sel_player_sidebar_raw = st.selectbox("Search Player", all_players, index=0)
    sel_player_sidebar = _resolve_player(sel_player_sidebar_raw)

    avail_tiers = [t for t in TIER_ORDER if t in df["value_tier"].values]
    sel_tiers = st.multiselect("Value Tier", avail_tiers, default=avail_tiers)

    min_g_sidebar = st.slider("Min games played", min_value=0, max_value=40, value=15, step=5,
                              help="Hide players who haven't played enough games this season")

    sort_options = {
        "Surplus (best first)":       ("surplus__n",       False),
        "Salary (highest)":           ("salary__n",         False),
        "WAR (highest)":              ("WAR",               False),
        "Composite Skill (highest)":  ("composite_skill",   False),
        "DPM (highest)":              ("DPM",               False),
        "EPM (highest)":              ("EPM",               False),
        "$/WAR (lowest)":             ("$/WAR__n",          True),
        "Name (A→Z)":                 ("Player",            True),
    }
    sort_label = st.selectbox("Sort By", list(sort_options.keys()))
    sort_col, sort_asc = sort_options[sort_label]

    st.markdown("---")
    st.caption(
        "**WAR (Wins Above Replacement)**  \n"
        "Measures how many wins a player adds over a freely available "
        "replacement-level player across a full season. It combines predictive "
        "and descriptive advanced metrics, adjusted for role and usage, to "
        "estimate a player's true market value.  \n\n"
        "Multi-year projections account for DARKO's trajectory signal in year 1 "
        "and the NBA aging curve thereafter."
    )

    st.markdown("---")
    # ── Data freshness ────────────────────────────────────────────────────────
    darko_files = sorted(
        glob.glob(os.path.join("DARKO_stats", "darko_talent_processed_*.xlsx")), reverse=True
    )
    if darko_files:
        mtime = os.path.getmtime(darko_files[0])
        st.caption(
            f"**DARKO last updated:**  \n"
            f"{datetime.fromtimestamp(mtime).strftime('%b %d, %Y  %I:%M %p')}"
        )
    else:
        st.caption("**DARKO:** no data file found — run `DARKO.py` first")

    if st.button("🔄 Refresh DARKO Data",
                 help="Re-scrapes DARKO projections (~1-2 min) then rebuilds player values."):
        py = sys.executable
        cwd = os.path.dirname(os.path.abspath(__file__))

        with st.spinner("Scraping DARKO projections…"):
            r1 = subprocess.run([py, "DARKO.py"], capture_output=True, text=True, cwd=cwd)
        if r1.returncode != 0:
            st.error(f"DARKO scrape failed:\n```\n{r1.stderr[-2000:]}\n```")
            st.stop()

        with st.spinner("Rebuilding player values…"):
            r2 = subprocess.run([py, "PlayerValue.py"], capture_output=True, text=True, cwd=cwd)
        if r2.returncode != 0:
            st.error(f"PlayerValue rebuild failed:\n```\n{r2.stderr[-2000:]}\n```")
            st.stop()

        st.cache_data.clear()
        st.success("✅ Data refreshed!")
        st.rerun()

    st.markdown("---")
    # ── Physical measurements freshness ───────────────────────────────────────
    meas_files_sb = sorted(
        glob.glob(os.path.join("Measurements", "player_measurements_*.xlsx")), reverse=True
    )
    if meas_files_sb:
        mtime_m = os.path.getmtime(meas_files_sb[0])
        st.caption(
            f"**Measurements last updated:**  \n"
            f"{datetime.fromtimestamp(mtime_m).strftime('%b %d, %Y  %I:%M %p')}"
        )
    else:
        st.caption("**Measurements:** not fetched yet — click below to load")

    if st.button("📏 Refresh Measurements",
                 help="Fetches height, wingspan & weight from craftednba.com (~10 sec)."):
        py  = sys.executable
        cwd = os.path.dirname(os.path.abspath(__file__))
        with st.spinner("Fetching player measurements…"):
            rm = subprocess.run([py, "measurements.py"], capture_output=True, text=True, cwd=cwd)
        if rm.returncode != 0:
            st.error(f"Measurements fetch failed:\n```\n{rm.stderr[-2000:]}\n```")
        else:
            st.cache_data.clear()
            st.success("✅ Measurements updated!")
            st.rerun()

# ── Filter ────────────────────────────────────────────────────────────────────
filt = df.copy()
if sel_team != "All Teams":
    filt = filt[filt["Team"] == sel_team]
if sel_player_sidebar != "All Players":
    filt = filt[filt["Player"] == sel_player_sidebar]
if sel_tiers:
    filt = filt[filt["value_tier"].isin(sel_tiers)]
if min_g_sidebar > 0:
    filt = filt[filt["G"] >= min_g_sidebar]
if sort_col in filt.columns:
    filt = filt.sort_values(sort_col, ascending=sort_asc, na_position="last")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 🏀 NBA Player Contract Value Dashboard")
tc = df["value_tier"].value_counts()
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Elite Bargain",   int(tc.get("Elite Bargain", 0)))
c2.metric("Great Value",     int(tc.get("Great Value", 0)))
c3.metric("Good Value",      int(tc.get("Good Value", 0)))
c4.metric("Fair Value",      int(tc.get("Fair Value", 0)))
c5.metric("Overpaid",        int(tc.get("Overpaid", 0) + tc.get("Significantly Overpaid", 0)))
c6.metric("Replacement",     int(tc.get("Replacement Level", 0)))

st.markdown("---")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_table, tab_charts, tab_team, tab_player, tab_compare, tab_similar = st.tabs(
    ["📋 Player Table", "📊 Charts", "🏟️ Team Summary", "🔍 Player Detail",
     "⚖️ Compare Players", "🔬 Similar Players"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Player Table
# ═══════════════════════════════════════════════════════════════════════════════
with tab_table:
    display_cols = [
        "Player", "Team", "Age", "DPM", "EPM", "composite_skill",
        "DPM Improvement", "trajectory",
        "O-DPM", "D-DPM", "O-EPM", "D-EPM",
        "USG%", "usage_scalar", "G", "projected_MP", "WAR",
        "salary", "fair_salary", "surplus", "$/WAR", "value_tier",
    ]
    display_cols = [c for c in display_cols if c in filt.columns]

    def _style_tier(val):
        bg = TIER_COLORS.get(val, "#ffffff")
        fg = TIER_TEXT_COLORS.get(val, "#000000")
        return f"background-color: {bg}; color: {fg}; font-weight: bold"

    def _style_surplus(val):
        n = parse_money(val)
        if pd.isna(n):
            return ""
        return "color: #1a7f37; font-weight: bold" if n > 0 else "color: #c0392b; font-weight: bold"

    def _style_trajectory(val):
        if val == "Trending Up":
            return "color: #1a7f37; font-weight: bold"
        if val == "Trending Down":
            return "color: #c0392b; font-weight: bold"
        return "color: #888888"

    _float_fmt = {c: "{:.2f}" for c in
                  ("DPM", "O-DPM", "D-DPM", "DPM Improvement",
                   "EPM", "O-EPM", "D-EPM", "composite_skill", "WAR", "USG%", "usage_scalar")
                  if c in display_cols}
    _int_fmt   = {c: "{:.0f}" for c in ("G", "projected_MP") if c in display_cols}
    styled = (
        filt[display_cols]
        .style
        .format({**_float_fmt, **_int_fmt}, na_rep="—")
        .applymap(_style_tier,        subset=["value_tier"])
        .applymap(_style_surplus,     subset=["surplus"])
        .applymap(_style_trajectory,  subset=["trajectory"] if "trajectory" in display_cols else [])
    )

    st.dataframe(styled, use_container_width=True, height=500)
    st.caption(f"Showing **{len(filt)}** of **{len(df)}** players")

    # Future contract years table (only if player has future years)
    if future_cols:
        st.markdown("#### Future Contract Years")
        future_display = ["Player", "Team", "DPM", "value_tier"] + future_cols
        future_outlook = [f"outlook_{c}" for c in future_cols if f"outlook_{c}" in filt.columns]
        future_display = [c for c in future_display + future_outlook if c in filt.columns]
        has_future = filt[future_cols].notna().any(axis=1)
        st.dataframe(filt.loc[has_future, future_display], use_container_width=True, height=300)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Charts
# ═══════════════════════════════════════════════════════════════════════════════
with tab_charts:
    chart_data = filt[filt["salary__n"].notna() & filt["composite_skill"].notna()].copy()

    col_l, col_r = st.columns(2)

    # Scatter: Composite Skill vs Salary
    with col_l:
        st.markdown("##### Composite Skill vs Contract Salary")
        if not chart_data.empty:
            fig = px.scatter(
                chart_data,
                x="composite_skill",
                y="salary__n",
                color="value_tier",
                color_discrete_map=TIER_COLORS,
                category_orders={"value_tier": TIER_ORDER},
                size=chart_data["WAR"].clip(lower=0.5),
                size_max=22,
                hover_name="Player",
                hover_data={
                    "Team": True, "DPM": ":.2f", "EPM": ":.2f", "WAR": ":.2f",
                    "salary": True, "surplus": True,
                    "salary__n": False,
                },
                labels={"salary__n": "Salary ($)", "composite_skill": "Composite Skill (DARKO+EPM)"},
            )
            fig.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.4)
            fig.update_yaxes(tickformat="$,.0f")
            fig.update_layout(height=420, legend_title="Tier", margin=dict(t=10))
            st.plotly_chart(fig, use_container_width=True)

    # Scatter: WAR vs Surplus
    with col_r:
        st.markdown("##### WAR vs Surplus Value")
        if not chart_data.empty:
            fig2 = px.scatter(
                chart_data,
                x="WAR",
                y="surplus__n",
                color="value_tier",
                color_discrete_map=TIER_COLORS,
                category_orders={"value_tier": TIER_ORDER},
                size=chart_data["salary__n"].clip(lower=1_000_000),
                size_max=22,
                hover_name="Player",
                hover_data={
                    "Team": True, "DPM": ":.1f",
                    "salary": True, "surplus": True,
                    "surplus__n": False,
                },
                labels={"surplus__n": "Surplus ($)", "WAR": "WAR"},
            )
            fig2.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4)
            fig2.update_yaxes(tickformat="$,.0f")
            fig2.update_layout(height=420, legend_title="Tier", margin=dict(t=10))
            st.plotly_chart(fig2, use_container_width=True)

    # Tier distribution bar
    st.markdown("##### Value Tier Distribution (filtered)")
    tier_counts = (
        filt["value_tier"]
        .value_counts()
        .reindex(TIER_ORDER)
        .dropna()
        .reset_index()
    )
    tier_counts.columns = ["Tier", "Count"]
    fig3 = px.bar(
        tier_counts, x="Tier", y="Count",
        color="Tier",
        color_discrete_map=TIER_COLORS,
        category_orders={"Tier": TIER_ORDER},
    )
    fig3.update_layout(showlegend=False, height=300, margin=dict(t=10))
    st.plotly_chart(fig3, use_container_width=True)

    # ── Contract vs Fair Market Value bar chart ───────────────────────────────
    st.markdown("---")
    st.markdown("##### Contract Salary vs Fair Market Value")

    bar_pool = chart_data[
        chart_data["fair_salary__n"].notna() & chart_data["salary__n"].notna()
    ].copy()

    ctrl_l, ctrl_r = st.columns([1, 3])
    with ctrl_l:
        show_n   = st.slider("Players to show", min_value=10, max_value=40,
                             value=20, step=5, key="chart_bar_n")
        bar_mode = st.radio("View", ["Top Bargains", "Most Overpaid"],
                            key="chart_bar_mode")

    if bar_mode == "Top Bargains":
        bar_subset = bar_pool.nlargest(show_n, "surplus__n").sort_values(
            "surplus__n", ascending=True
        )
        bar_title = f"Top {show_n} Most Underpaid Players"
        fair_color = "#2ea44f"
    else:
        bar_subset = bar_pool.nsmallest(show_n, "surplus__n").sort_values(
            "surplus__n", ascending=False
        )
        bar_title = f"Top {show_n} Most Overpaid Players"
        fair_color = "#d73a49"

    if not bar_subset.empty:
        fig_contract = go.Figure()
        fig_contract.add_trace(go.Bar(
            name="Actual Salary",
            y=bar_subset["Player"],
            x=bar_subset["salary__n"],
            orientation="h",
            marker_color="#4a90d9",
            text=[money_str(v) for v in bar_subset["salary__n"]],
            textposition="inside",
            insidetextanchor="middle",
            hovertemplate="%{y}<br>Actual: %{x:$,.0f}<extra></extra>",
        ))
        fig_contract.add_trace(go.Bar(
            name="Fair Market Value",
            y=bar_subset["Player"],
            x=bar_subset["fair_salary__n"],
            orientation="h",
            marker_color=fair_color,
            text=[money_str(v) for v in bar_subset["fair_salary__n"]],
            textposition="inside",
            insidetextanchor="middle",
            hovertemplate="%{y}<br>Fair Value: %{x:$,.0f}<extra></extra>",
        ))
        fig_contract.update_layout(
            barmode="group",
            title=bar_title,
            xaxis_tickformat="$,.0f",
            xaxis_title="Amount ($)",
            height=max(460, show_n * 30),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            margin=dict(t=50, b=20),
        )
        with ctrl_r:
            st.plotly_chart(fig_contract, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Team Summary
# ═══════════════════════════════════════════════════════════════════════════════
with tab_team:
    team_data = df[df["salary__n"].notna()].copy()
    team_summary = (
        team_data.groupby("Team")
        .agg(
            Players=("Player", "count"),
            Total_Salary=("salary__n", "sum"),
            Total_WAR=("WAR", "sum"),
            Avg_DPM=("DPM", "mean"),
            Total_Surplus=("surplus__n", "sum"),
        )
        .round({"Total_WAR": 1, "Avg_DPM": 2, "Total_Surplus": 0})
        .sort_values("Total_Surplus", ascending=False)
        .reset_index()
    )
    team_summary["Total_Salary_fmt"] = team_summary["Total_Salary"].apply(money_str)
    team_summary["Total_Surplus_fmt"] = team_summary["Total_Surplus"].apply(money_str)

    col_tl, col_tr = st.columns(2)

    with col_tl:
        st.markdown("##### Team Surplus Value")
        fig_t1 = px.bar(
            team_summary.sort_values("Total_Surplus"),
            x="Total_Surplus", y="Team",
            orientation="h",
            color="Total_Surplus",
            color_continuous_scale=["#d73a49", "#ffffcc", "#1a7f37"],
            labels={"Total_Surplus": "Total Surplus ($)"},
            hover_data={"Total_Salary_fmt": True, "Total_WAR": True},
        )
        fig_t1.update_xaxes(tickformat="$,.0f")
        fig_t1.update_layout(height=600, showlegend=False,
                              coloraxis_showscale=False, margin=dict(t=10))
        st.plotly_chart(fig_t1, use_container_width=True)

    with col_tr:
        st.markdown("##### Total Team WAR")
        fig_t2 = px.bar(
            team_summary.sort_values("Total_WAR"),
            x="Total_WAR", y="Team",
            orientation="h",
            color="Total_WAR",
            color_continuous_scale=["#f9c8c8", "#a2d9a5", "#1a7f37"],
            labels={"Total_WAR": "Total WAR"},
        )
        fig_t2.update_layout(height=600, showlegend=False,
                              coloraxis_showscale=False, margin=dict(t=10))
        st.plotly_chart(fig_t2, use_container_width=True)

    st.markdown("##### Full Team Summary Table")
    display_team = team_summary[
        ["Team", "Players", "Total_Salary_fmt", "Total_WAR", "Avg_DPM", "Total_Surplus_fmt"]
    ].rename(columns={
        "Total_Salary_fmt": "Total Salary", "Total_WAR": "Team WAR",
        "Avg_DPM": "Avg DPM", "Total_Surplus_fmt": "Total Surplus",
    })
    st.dataframe(display_team, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Player Detail
# ═══════════════════════════════════════════════════════════════════════════════
with tab_player:
    all_detail_players = sorted(df["Player"].dropna().unique().tolist())
    sel_player_raw = st.selectbox(
        "Type a name to search, then click to select",
        [""] + _player_options(all_detail_players),
        key="detail_player",
    )
    sel_player = _resolve_player(sel_player_raw)

    if not sel_player:
        st.info("Start typing a player name in the box above.")
    else:
        row = df[df["Player"] == sel_player].iloc[0]
        tier = row.get("value_tier", "")
        tier_bg = TIER_COLORS.get(tier, "#eeeeee")
        tier_fg = TIER_TEXT_COLORS.get(tier, "#000000")

        # Header row
        st.markdown(
            f"### {sel_player} &nbsp; "
            f"<span style='background:{tier_bg}; color:{tier_fg}; padding:4px 12px; "
            f"border-radius:6px; font-size:0.85em'>{tier}</span>",
            unsafe_allow_html=True,
        )

        # Key metrics — row 1: skill signals
        m1, m2, m3, m4, m5 = st.columns(5)
        dpm_imp = row.get("DPM Improvement")
        comp    = row.get("composite_skill")
        m1.metric("DARKO DPM",   f"{row.get('DPM', '—'):.2f}"  if pd.notna(row.get("DPM"))  else "—")
        m2.metric("EPM",         f"{row.get('EPM', '—'):.2f}"  if pd.notna(row.get("EPM"))  else "—")
        m3.metric("Composite",   f"{comp:.2f}"                  if pd.notna(comp)             else "—",
                  help="Weighted blend of DARKO DPM and EPM used for WAR/salary model")
        m4.metric("DPM Trend",   f"{dpm_imp:+.2f}" if pd.notna(dpm_imp) else "—",
                  delta=f"{dpm_imp:+.2f}" if pd.notna(dpm_imp) else None,
                  delta_color="normal")
        m5.metric("WAR",         f"{row.get('WAR', '—'):.2f}"  if pd.notna(row.get("WAR"))  else "—")

        # Row 2: split offense/defense + game info
        m6, m7, m8, m9, m10 = st.columns(5)
        m6.metric("O-DPM",  f"{row.get('O-DPM', '—'):.2f}"  if pd.notna(row.get("O-DPM"))  else "—")
        m7.metric("D-DPM",  f"{row.get('D-DPM', '—'):.2f}"  if pd.notna(row.get("D-DPM"))  else "—")
        m8.metric("O-EPM",  f"{row.get('O-EPM', '—'):.2f}"  if pd.notna(row.get("O-EPM"))  else "—")
        m9.metric("D-EPM",  f"{row.get('D-EPM', '—'):.2f}"  if pd.notna(row.get("D-EPM"))  else "—")
        m10.metric("Age / G", f"{int(row.get('Age', 0))} / {int(row.get('G', 0))}"
                   if pd.notna(row.get("Age")) else f"— / {int(row.get('G', 0))}")

        st.markdown("---")

        # Contract vs fair value — current + future years
        seasons, actual_vals, fair_vals, outlooks = [], [], [], []

        # Current season
        sal_now  = parse_money(row.get("salary"))
        fair_now = parse_money(row.get("fair_salary"))
        if pd.notna(sal_now):
            seasons.append(f"{CURRENT_SEASON} ▶")
            actual_vals.append(sal_now)
            fair_vals.append(fair_now if pd.notna(fair_now) else 0)
            outlooks.append(tier)

        # Future seasons
        for yr_col in future_cols:
            actual = parse_money(row.get(yr_col))
            surplus_n = parse_money(row.get(f"surplus_{yr_col}"))
            if pd.notna(actual):
                fair_yr = actual + surplus_n if pd.notna(surplus_n) else float("nan")
                seasons.append(yr_col)
                actual_vals.append(actual)
                fair_vals.append(fair_yr if pd.notna(fair_yr) else 0)
                outlooks.append(row.get(f"outlook_{yr_col}", ""))

        if seasons:
            st.markdown("##### Contract Salary vs Projected Fair Market Value")

            fig_p = go.Figure()
            fig_p.add_trace(go.Bar(
                name="Actual Salary",
                x=seasons, y=actual_vals,
                marker_color="#4a90d9",
                text=[money_str(v) for v in actual_vals],
                textposition="outside",
            ))
            fig_p.add_trace(go.Bar(
                name="Fair Market Value",
                x=seasons, y=fair_vals,
                marker_color="#2ea44f",
                text=[money_str(v) for v in fair_vals],
                textposition="outside",
            ))

            # Annotate each season with its outlook label
            for i, (s, o) in enumerate(zip(seasons, outlooks)):
                if not o:
                    continue
                if "Underpaid" in o or "Bargain" in o or "Value" in o:
                    ann_color = "#1a7f37"
                elif "Overpaid" in o:
                    ann_color = "#d73a49"
                else:
                    ann_color = "#888888"
                fig_p.add_annotation(
                    x=s, y=max(actual_vals[i], fair_vals[i]) * 1.12,
                    text=o, showarrow=False,
                    font=dict(size=10, color=ann_color, family="Arial"),
                )

            fig_p.update_layout(
                barmode="group",
                yaxis_tickformat="$,.0f",
                xaxis_title="Season",
                yaxis_title="Amount ($)",
                height=380,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                margin=dict(t=40, b=20),
            )
            st.plotly_chart(fig_p, use_container_width=True)

            # Surplus per season line
            if len(seasons) > 1:
                surplus_vals = [f - a for f, a in zip(fair_vals, actual_vals)]
                fig_s = go.Figure()
                bar_colors = ["#1a7f37" if v >= 0 else "#d73a49" for v in surplus_vals]
                fig_s.add_trace(go.Bar(
                    x=seasons, y=surplus_vals,
                    marker_color=bar_colors,
                    text=[money_str(v) for v in surplus_vals],
                    textposition="outside",
                    name="Surplus",
                ))
                fig_s.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
                fig_s.update_layout(
                    title="Surplus per Season (green = underpaid, red = overpaid)",
                    yaxis_tickformat="$,.0f",
                    height=280,
                    margin=dict(t=40, b=20),
                    showlegend=False,
                )
                st.plotly_chart(fig_s, use_container_width=True)
        else:
            st.info("No contract data available for this player.")

        # Raw stats expander
        with st.expander("Full DARKO + EPM stats"):
            darko_cols = [c for c in df.columns if c not in
                          ("salary", "fair_salary", "surplus", "$/WAR", "value_tier")
                          and not c.endswith("__n") and not c.startswith("surplus_")
                          and not c.startswith("outlook_") and c not in future_cols]
            st.dataframe(
                pd.DataFrame([row[darko_cols]]).reset_index(drop=True),
                use_container_width=True,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Player Comparison
# ═══════════════════════════════════════════════════════════════════════════════
with tab_compare:
    st.markdown("#### ⚖️ Player Comparison")

    all_cmp_players = sorted(df["Player"].dropna().unique().tolist())
    _cmp_options = [""] + _player_options(all_cmp_players)
    sel_a_col, sel_b_col = st.columns(2)
    with sel_a_col:
        player_a = _resolve_player(st.selectbox("Player A", _cmp_options, key="cmp_a"))
    with sel_b_col:
        player_b = _resolve_player(st.selectbox("Player B", _cmp_options, key="cmp_b"))

    if not player_a or not player_b:
        st.info("Select two players above to compare.")
    elif player_a == player_b:
        st.warning("Select two different players to compare.")
    else:
        row_a = df[df["Player"] == player_a].iloc[0]
        row_b = df[df["Player"] == player_b].iloc[0]

        # ── Player header cards ───────────────────────────────────────────────
        def player_header(row, name):
            tier    = row.get("value_tier", "")
            bg      = TIER_COLORS.get(tier, "#eeeeee")
            fg      = TIER_TEXT_COLORS.get(tier, "#000000")
            team    = row.get("Team", "—")
            age     = int(row.get("Age")) if pd.notna(row.get("Age")) else "—"
            salary  = money_str(parse_money(row.get("salary")))
            st.markdown(
                f"<div style='background:#f6f8fa; border-radius:10px; padding:14px 18px;'>"
                f"<h3 style='margin:0'>{name}</h3>"
                f"<span style='background:{bg}; color:{fg}; padding:3px 10px; "
                f"border-radius:12px; font-size:0.8em; font-weight:bold'>{tier}</span>"
                f"&nbsp; <span style='color:#555; font-size:0.9em'>{team} · Age {age} · {salary}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        hdr_a, hdr_b = st.columns(2)
        with hdr_a:
            player_header(row_a, player_a)
        with hdr_b:
            player_header(row_b, player_b)

        st.markdown("---")

        # ── Side-by-side stat comparison ──────────────────────────────────────
        st.markdown("##### Skill & Contract Stats")

        COMPARE_STATS = [
            ("DARKO DPM",  "DPM",            ":.2f", True),
            ("EPM",        "EPM",            ":.2f", True),
            ("Composite",  "composite_skill",":.2f", True),
            ("WAR",        "WAR",            ":.2f", True),
            ("O-DPM",      "O-DPM",          ":.2f", True),
            ("D-DPM",      "D-DPM",          ":.2f", True),
            ("O-EPM",      "O-EPM",          ":.2f", True),
            ("D-EPM",      "D-EPM",          ":.2f", True),
            ("USG%",       "USG%",           ":.1f", True),
            ("Usage Scalar","usage_scalar",  ":.2f", True),
            ("Games",      "G",              ":.0f", True),
            ("Proj. MP",   "projected_MP",   ":.0f", True),
        ]

        # Header row
        lbl_col, a_col, b_col = st.columns([2, 2, 2])
        lbl_col.markdown("**Stat**")
        a_col.markdown(f"**{player_a}**")
        b_col.markdown(f"**{player_b}**")

        for label, col, fmt, higher_better in COMPARE_STATS:
            if col not in df.columns:
                continue
            va = row_a.get(col)
            vb = row_b.get(col)
            if pd.isna(va) and pd.isna(vb):
                continue

            va_f = float(va) if pd.notna(va) else None
            vb_f = float(vb) if pd.notna(vb) else None
            a_str = (f"{va_f:{fmt[1:]}}") if va_f is not None else "—"
            b_str = (f"{vb_f:{fmt[1:]}}") if vb_f is not None else "—"

            # Highlight the better value green
            if va_f is not None and vb_f is not None:
                a_wins = va_f > vb_f if higher_better else va_f < vb_f
                a_style = "color:#1a7f37; font-weight:bold" if a_wins else "color:#555"
                b_style = "color:#1a7f37; font-weight:bold" if not a_wins else "color:#555"
            else:
                a_style = b_style = "color:#555"

            lc, ac, bc = st.columns([2, 2, 2])
            lc.markdown(f"<span style='color:#888; font-size:0.9em'>{label}</span>",
                        unsafe_allow_html=True)
            ac.markdown(f"<span style='{a_style}'>{a_str}</span>", unsafe_allow_html=True)
            bc.markdown(f"<span style='{b_style}'>{b_str}</span>", unsafe_allow_html=True)

        st.markdown("---")

        # ── Radar chart ───────────────────────────────────────────────────────
        st.markdown("##### Skill Profile Radar")

        radar_cols = ["composite_skill", "O-EPM", "D-EPM", "O-DPM", "D-DPM", "WAR"]
        radar_cols = [c for c in radar_cols if c in df.columns]
        radar_labels = {
            "composite_skill": "Composite", "WAR": "WAR",
            "O-EPM": "Off EPM", "D-EPM": "Def EPM",
            "O-DPM": "Off DPM", "D-DPM": "Def DPM",
        }

        def pct_score(series, value):
            """Percentile rank 0–10."""
            if pd.isna(value):
                return 5.0
            valid = series.dropna()
            return (valid < float(value)).sum() / max(len(valid), 1) * 10

        labels_r = [radar_labels.get(c, c) for c in radar_cols]
        scores_a = [pct_score(df[c], row_a.get(c)) for c in radar_cols]
        scores_b = [pct_score(df[c], row_b.get(c)) for c in radar_cols]

        fig_radar = go.Figure()
        for name, scores, color in [
            (player_a, scores_a, "#4a90d9"),
            (player_b, scores_b, "#2ea44f"),
        ]:
            fig_radar.add_trace(go.Scatterpolar(
                r=scores + [scores[0]],
                theta=labels_r + [labels_r[0]],
                fill="toself",
                name=name,
                line_color=color,
                opacity=0.65,
            ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 10],
                                       tickvals=[2, 4, 6, 8, 10],
                                       ticktext=["20%", "40%", "60%", "80%", "100%"])),
            showlegend=True,
            height=400,
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig_radar, use_container_width=True)

        st.markdown("---")

        # ── Current-year salary vs fair value ─────────────────────────────────
        st.markdown("##### Current Season: Salary vs Fair Market Value")

        sal_a  = parse_money(row_a.get("salary"))
        sal_b  = parse_money(row_b.get("salary"))
        fair_a = parse_money(row_a.get("fair_salary"))
        fair_b = parse_money(row_b.get("fair_salary"))
        surp_a = parse_money(row_a.get("surplus"))
        surp_b = parse_money(row_b.get("surplus"))

        bar_players = [n for n, s in [(player_a, sal_a), (player_b, sal_b)] if pd.notna(s)]
        bar_actuals = [s for s in [sal_a, sal_b] if pd.notna(s)]
        bar_fairs   = [f for _, f, s in [(player_a, fair_a, sal_a), (player_b, fair_b, sal_b)]
                       if pd.notna(s)]

        if bar_players:
            fig_sal = go.Figure()
            fig_sal.add_trace(go.Bar(
                name="Actual Salary", x=bar_players, y=bar_actuals,
                marker_color="#4a90d9",
                text=[money_str(v) for v in bar_actuals], textposition="outside",
            ))
            fig_sal.add_trace(go.Bar(
                name="Fair Market Value", x=bar_players, y=bar_fairs,
                marker_color="#2ea44f",
                text=[money_str(v) for v in bar_fairs], textposition="outside",
            ))
            fig_sal.update_layout(
                barmode="group", yaxis_tickformat="$,.0f",
                height=340, margin=dict(t=40, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            )
            st.plotly_chart(fig_sal, use_container_width=True)

        # ── Multi-year surplus trajectory ─────────────────────────────────────
        if future_cols:
            def surplus_series(row):
                xs, ys = [], []
                s = parse_money(row.get("surplus"))
                if pd.notna(s):
                    xs.append(f"{CURRENT_SEASON} ▶")
                    ys.append(s)
                for yr in future_cols:
                    if pd.notna(parse_money(row.get(yr))):
                        sv = parse_money(row.get(f"surplus_{yr}"))
                        xs.append(yr)
                        ys.append(sv if pd.notna(sv) else None)
                return xs, ys

            xs_a, ys_a = surplus_series(row_a)
            xs_b, ys_b = surplus_series(row_b)

            if len(xs_a) > 1 or len(xs_b) > 1:
                st.markdown("##### Contract Surplus Trajectory")
                fig_traj = go.Figure()
                for name, xs, ys, color in [
                    (player_a, xs_a, ys_a, "#4a90d9"),
                    (player_b, xs_b, ys_b, "#2ea44f"),
                ]:
                    if xs:
                        fig_traj.add_trace(go.Scatter(
                            x=xs, y=ys,
                            mode="lines+markers",
                            name=name,
                            line=dict(color=color, width=2),
                            marker=dict(size=8),
                            hovertemplate="%{x}: %{y:$,.0f}<extra>" + name + "</extra>",
                        ))
                fig_traj.add_hline(y=0, line_dash="dash", line_color="gray",
                                   opacity=0.5, annotation_text="Break even")
                fig_traj.update_layout(
                    yaxis_tickformat="$,.0f",
                    yaxis_title="Surplus (positive = underpaid)",
                    height=320,
                    margin=dict(t=20, b=20),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                )
                st.plotly_chart(fig_traj, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — Similar Players
# ═══════════════════════════════════════════════════════════════════════════════

# Feature definitions: (column, display label, default weight)
# Style stats (traditional box score) get highest weights — they capture HOW a player
# plays (3-pt specialist, slasher, playmaker, rim-protector) which advanced metrics flatten.
_SIM_FEATURES = [
    # Playing-style indicators — most important for "same type of player" matching
    ("3PA",            "3pt Attempts", 3.0),   # 3-pt specialists vs interior scorers
    ("AST",            "Assists",      2.5),   # playmakers vs off-ball players
    ("TRB",            "Rebounds",     2.5),   # bigs vs wings
    ("FTA",            "FT Attempts",  2.0),   # slashers vs jump-shooters
    ("BLK",            "Blocks",       2.0),   # rim-protectors vs perimeter defenders
    ("3P%",            "3pt %",        1.5),   # shooting quality
    ("STL",            "Steals",       1.5),   # perimeter D
    ("PTS",            "Points",       1.2),   # scoring role
    ("TOV",            "Turnovers",    1.0),   # playmaking / ball-security
    ("FT%",            "FT %",         0.8),   # shooting touch
    # Physical measurements
    ("Height_in",      "Height",       2.0),
    ("Wingspan_in",    "Wingspan",     2.0),
    ("Weight_lbs",     "Weight",       1.2),
    ("ArmLength_in",   "Arm Length",   1.0),
    # Advanced metrics (secondary — skill quality on top of role)
    ("O-DPM",          "Off DPM",      1.5),
    ("D-DPM",          "Def DPM",      1.5),
    ("O-EPM",          "Off EPM",      1.5),
    ("D-EPM",          "Def EPM",      1.5),
    ("USG%",           "Usage %",      1.2),
    ("composite_skill","Composite",    1.0),
    ("WAR",            "WAR",          0.6),
    ("Age",            "Age",          0.3),
]


def find_similar_players(source_df, target_name, feature_weights, n=8):
    """
    Returns the top-N most similar players to target_name using weighted
    Euclidean distance on z-score-normalized features.
    Missing values are imputed to the column mean before normalisation.
    """
    avail = [(col, lbl, w) for col, lbl, w in feature_weights if col in source_df.columns]
    if not avail:
        return pd.DataFrame()

    cols   = [col for col, _, _ in avail]
    weights = [w   for _, _,  w in avail]

    pool   = source_df[source_df["Player"] != target_name].copy()
    target = source_df[source_df["Player"] == target_name]
    if target.empty or pool.empty:
        return pd.DataFrame()

    target_row = target.iloc[0]

    # Numeric conversion + mean imputation
    # Cast to float64 explicitly — Age is Int64 (nullable) which rejects float fillna
    all_vals  = source_df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    col_means = all_vals.mean()
    col_stds  = all_vals.std().replace(0, 1)

    pool_num  = pool[cols].apply(pd.to_numeric, errors="coerce").astype(float).fillna(col_means)
    tgt_num   = (pd.to_numeric(pd.Series({c: target_row.get(c) for c in cols}), errors="coerce")
                 .astype(float).fillna(col_means))

    # Z-score normalise
    pool_z = (pool_num - col_means) / col_stds
    tgt_z  = (tgt_num  - col_means) / col_stds

    # Weighted Euclidean distance
    w_series  = pd.Series(dict(zip(cols, weights)))
    distances = ((pool_z - tgt_z) ** 2).mul(w_series).sum(axis=1).pow(0.5)

    pool = pool.copy()
    pool["_dist"] = distances.values
    # Similarity score 0–100 (100 = perfect match)
    max_d = distances.max() if distances.max() > 0 else 1
    pool["_similarity"] = ((1 - pool["_dist"] / max_d) * 100).round(1)

    return pool.nsmallest(n, "_dist").reset_index(drop=True)


with tab_similar:
    st.markdown("#### 🔬 Find Similar Players")
    st.caption(
        "Similarity blends playing-style stats (3PA, assists, rebounds, drives, blocks) "
        "with physical measurements and advanced ratings. A 3-point specialist matches "
        "other shooters; a slashing big matches other interior scorers. Adjust weights below."
    )

    sim_search_col, sim_n_col = st.columns([3, 1])
    with sim_search_col:
        all_sim_players = sorted(df["Player"].dropna().unique().tolist())
        sim_target = _resolve_player(
            st.selectbox("Search player", [""] + _player_options(all_sim_players), key="sim_target")
        )
    with sim_n_col:
        sim_n = st.slider("Results", min_value=5, max_value=15, value=8, key="sim_n")

    # Weight controls in an expander so they don't clutter the default view
    with st.expander("⚙️ Adjust similarity weights", expanded=False):
        st.caption("Higher weight = this dimension matters more for matching.")
        weight_cols = st.columns(4)
        custom_weights = []
        visible_features = [(col, lbl, dw) for col, lbl, dw in _SIM_FEATURES
                            if col in df.columns]
        for i, (col, lbl, default_w) in enumerate(visible_features):
            with weight_cols[i % 4]:
                w = st.slider(lbl, min_value=0.0, max_value=3.0,
                              value=float(default_w), step=0.1,
                              key=f"sim_w_{col}")
                custom_weights.append((col, lbl, w))

    if not sim_target:
        st.info("Type a player name above to find their statistical twins.")
    else:
        active_weights = custom_weights if custom_weights else visible_features
        target_row_sim = df[df["Player"] == sim_target]
        if target_row_sim.empty:
            st.error(f"Player '{sim_target}' not found in data.")
        else:
            target_row_sim = target_row_sim.iloc[0]
            similar = find_similar_players(df, sim_target, active_weights, n=sim_n)

            if similar.empty:
                st.warning("Not enough data to compute similarity.")
            else:
                # ── Target player card ────────────────────────────────────────
                tier_t  = target_row_sim.get("value_tier", "")
                bg_t    = TIER_COLORS.get(tier_t, "#eeeeee")
                fg_t    = TIER_TEXT_COLORS.get(tier_t, "#000000")
                ht_disp = target_row_sim.get("Height_display", "")
                ws_disp = target_row_sim.get("Wingspan_display", "")
                wt      = target_row_sim.get("Weight_lbs")
                # Guard against NaN — measurements missing for this player
                ht_disp = ht_disp if isinstance(ht_disp, str) else ""
                ws_disp = ws_disp if isinstance(ws_disp, str) else ""
                phys_str = "  ·  ".join(filter(None, [
                    ht_disp,
                    f"{ws_disp} WS" if ws_disp else "",
                    f"{int(wt)} lbs" if pd.notna(wt) else "",
                ]))
                # Traditional stat summary for the card
                def _stat(col, fmt="{:.1f}"):
                    v = target_row_sim.get(col)
                    return fmt.format(v) if pd.notna(v) else "—"

                style_line = (
                    f"{_stat('PTS')} PTS · {_stat('TRB')} REB · {_stat('AST')} AST · "
                    f"{_stat('STL')} STL · {_stat('BLK')} BLK · "
                    f"{_stat('3PA')} 3PA ({_stat('3P%', '{:.1%}')} 3P%)"
                )
                st.markdown(
                    f"<div style='background:#f6f8fa; border-radius:10px; padding:12px 16px; "
                    f"margin-bottom:12px'>"
                    f"<strong style='font-size:1.1em'>{sim_target}</strong> &nbsp;"
                    f"<span style='background:{bg_t}; color:{fg_t}; padding:2px 9px; "
                    f"border-radius:10px; font-size:0.8em'>{tier_t}</span> &nbsp;"
                    f"<span style='color:#555; font-size:0.9em'>"
                    f"{target_row_sim.get('Team','—')} · "
                    f"Age {int(target_row_sim.get('Age')) if pd.notna(target_row_sim.get('Age')) else '—'}"
                    + (f" · {phys_str}" if phys_str else "") +
                    f"</span><br>"
                    f"<span style='color:#444; font-size:0.85em'>"
                    f"{style_line}"
                    f" &nbsp;|&nbsp; Composite {target_row_sim.get('composite_skill','—'):.2f}"
                    f" · WAR {target_row_sim.get('WAR','—'):.2f}"
                    f"</span></div>",
                    unsafe_allow_html=True,
                )

                # ── Similarity results table ──────────────────────────────────
                st.markdown("##### Most Similar Players")
                sim_display_cols = [
                    "Player", "Team", "Age",
                    "Height_display", "Wingspan_display", "Weight_lbs",
                    # Traditional style stats
                    "PTS", "TRB", "AST", "STL", "BLK",
                    "3PA", "3P%", "FTA",
                    # Advanced
                    "composite_skill", "USG%", "WAR",
                    "salary", "value_tier", "_similarity",
                ]
                sim_display_cols = [c for c in sim_display_cols if c in similar.columns]

                sim_fmt = {c: "{:.1f}" for c in
                           ("PTS", "TRB", "AST", "STL", "BLK", "TOV",
                            "3PA", "FTA", "USG%") if c in sim_display_cols}
                sim_fmt.update({c: "{:.2f}" for c in
                                ("O-DPM", "D-DPM", "O-EPM", "D-EPM",
                                 "composite_skill", "WAR") if c in sim_display_cols})
                # Percentage stats are stored as decimals (0.374 = 37.4%)
                sim_fmt.update({c: "{:.1%}" for c in
                                ("3P%", "FT%") if c in sim_display_cols})
                sim_fmt["Weight_lbs"]  = "{:.2f}"
                sim_fmt["_similarity"] = "{:.2f}%"

                col_renames = {
                    "_similarity":    "Similarity",
                    "composite_skill":"Composite",
                    "Height_display": "Height",
                    "Wingspan_display":"Wingspan",
                    "Weight_lbs":     "Weight (lbs)",
                }
                # Remap format keys to post-rename names so .format() finds them
                sim_fmt = {col_renames.get(k, k): v for k, v in sim_fmt.items()}

                def _sim_bar(val):
                    color = "#1a7f37" if val >= 80 else "#2ea44f" if val >= 65 else "#f0a500"
                    return f"background: linear-gradient(90deg, {color}22 {val:.0f}%, transparent {val:.0f}%)"

                styled_sim = (
                    similar[sim_display_cols]
                    .rename(columns=col_renames)
                    .style
                    .format(sim_fmt, na_rep="—")
                    .applymap(_style_tier, subset=["value_tier"])
                    .applymap(_sim_bar,    subset=["Similarity"])
                )
                st.dataframe(styled_sim, use_container_width=True,
                             height=min(380, (sim_n + 1) * 38))

                # ── Radar charts: target vs top match ────────────────────────
                st.markdown("---")
                top_match = similar.iloc[0]["Player"]
                top_sim   = similar.iloc[0]["_similarity"]
                st.markdown(f"##### Profile: {sim_target} vs Top Match — {top_match} "
                            f"({top_sim:.1f}% similar)")

                def _pct(series, val):
                    if pd.isna(val):
                        return 5.0
                    valid = series.dropna()
                    return (valid < float(val)).sum() / max(len(valid), 1) * 10

                top_row = df[df["Player"] == top_match].iloc[0]

                rad_col_a, rad_col_b = st.columns(2)

                # — Style radar (traditional per-game stats) —
                style_radar_cols = ["3PA", "AST", "TRB", "BLK", "STL", "FTA", "PTS"]
                style_radar_cols = [c for c in style_radar_cols if c in df.columns]
                style_radar_lbls = {
                    "3PA": "3pt Att", "AST": "Assists", "TRB": "Rebounds",
                    "BLK": "Blocks",  "STL": "Steals",  "FTA": "FT Att",
                    "PTS": "Points",
                }
                if style_radar_cols:
                    sl = [style_radar_lbls.get(c, c) for c in style_radar_cols]
                    st_target = [_pct(df[c], target_row_sim.get(c)) for c in style_radar_cols]
                    st_top    = [_pct(df[c], top_row.get(c))        for c in style_radar_cols]
                    fig_style = go.Figure()
                    for name, scores, color in [
                        (sim_target, st_target, "#4a90d9"),
                        (top_match,  st_top,    "#2ea44f"),
                    ]:
                        fig_style.add_trace(go.Scatterpolar(
                            r=scores + [scores[0]],
                            theta=sl + [sl[0]],
                            fill="toself", name=name,
                            line_color=color, opacity=0.65,
                        ))
                    fig_style.update_layout(
                        title=dict(text="Style Profile", x=0.5, font=dict(size=13)),
                        polar=dict(radialaxis=dict(
                            visible=True, range=[0, 10],
                            tickvals=[2, 4, 6, 8, 10],
                            ticktext=["20%", "40%", "60%", "80%", "100%"],
                        )),
                        showlegend=True, height=400, margin=dict(t=40, b=20),
                    )
                    with rad_col_a:
                        st.plotly_chart(fig_style, use_container_width=True)

                # — Advanced radar (DPM/EPM/WAR) —
                adv_radar_cols = ["composite_skill", "O-EPM", "D-EPM", "O-DPM", "D-DPM", "WAR"]
                adv_radar_cols = [c for c in adv_radar_cols if c in df.columns]
                adv_radar_lbls = {
                    "composite_skill": "Composite", "WAR": "WAR",
                    "O-EPM": "Off EPM", "D-EPM": "Def EPM",
                    "O-DPM": "Off DPM", "D-DPM": "Def DPM",
                }
                if adv_radar_cols:
                    al = [adv_radar_lbls.get(c, c) for c in adv_radar_cols]
                    r_target = [_pct(df[c], target_row_sim.get(c)) for c in adv_radar_cols]
                    r_top    = [_pct(df[c], top_row.get(c))        for c in adv_radar_cols]
                    fig_sim_radar = go.Figure()
                    for name, scores, color in [
                        (sim_target, r_target, "#4a90d9"),
                        (top_match,  r_top,    "#2ea44f"),
                    ]:
                        fig_sim_radar.add_trace(go.Scatterpolar(
                            r=scores + [scores[0]],
                            theta=al + [al[0]],
                            fill="toself", name=name,
                            line_color=color, opacity=0.65,
                        ))
                    fig_sim_radar.update_layout(
                        title=dict(text="Advanced Metrics", x=0.5, font=dict(size=13)),
                        polar=dict(radialaxis=dict(
                            visible=True, range=[0, 10],
                            tickvals=[2, 4, 6, 8, 10],
                            ticktext=["20%", "40%", "60%", "80%", "100%"],
                        )),
                        showlegend=True, height=400, margin=dict(t=40, b=20),
                    )
                    with rad_col_b:
                        st.plotly_chart(fig_sim_radar, use_container_width=True)

                # ── Similarity score bar chart ────────────────────────────────
                st.markdown("---")
                st.markdown("##### Similarity Scores")
                fig_scores = go.Figure(go.Bar(
                    x=similar["_similarity"],
                    y=similar["Player"],
                    orientation="h",
                    marker_color=[
                        "#1a7f37" if v >= 80 else "#2ea44f" if v >= 65 else "#f0a500"
                        for v in similar["_similarity"]
                    ],
                    text=[f"{v:.1f}%" for v in similar["_similarity"]],
                    textposition="outside",
                ))
                fig_scores.update_layout(
                    xaxis=dict(title="Similarity (%)", range=[0, 105]),
                    height=max(300, sim_n * 36),
                    margin=dict(t=10, b=20),
                )
                st.plotly_chart(fig_scores, use_container_width=True)
