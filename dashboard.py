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

    # Ensure numeric DPM/EPM/WAR
    for col in ("DPM", "O-DPM", "D-DPM", "EPM", "O-EPM", "D-EPM",
                "composite_skill", "WAR", "G", "projected_MP", "USG%", "usage_scalar"):
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

    all_players = ["All Players"] + sorted(df["Player"].dropna().unique().tolist())
    sel_player_sidebar = st.selectbox("Search Player", all_players, index=0)

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
        "**Model**  \n"
        "Skill = DARKO DPM (38%) + EPM (62%)  \n"
        "Usage scalar = √(USG% / 20) → [0.55, 1.00]  \n"
        "Fair salary × usage scalar (role players discounted, stars uncapped)  \n"
        "Market rate: $6M / WAR  \n"
        "Replacement DPM: −2.0  \n"
        "Projected games: 72  \n"
        "**Yr 1**: DARKO DPM Improvement  \n"
        "**Yr 2+**: NBA age curve  \n"
        "(peak ≈ age 27, growth before, decline after)"
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
tab_table, tab_charts, tab_team, tab_player, tab_trade = st.tabs(
    ["📋 Player Table", "📊 Charts", "🏟️ Team Summary", "🔍 Player Detail", "🔄 Trade Targets"]
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
    sel_player = st.selectbox(
        "Type a name to search, then click to select",
        [""] + all_detail_players,
        key="detail_player",
    )

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
# TAB 5 — Trade Targets
# ═══════════════════════════════════════════════════════════════════════════════
with tab_trade:
    st.markdown("#### 🔄 Trade Target Finder")
    st.caption(
        "Select a team to see their offensive/defensive needs and ranked attainable "
        "targets from other teams. Attainability reflects how likely a team is to move "
        "a player based on their contract value tier."
    )

    all_teams_trade = sorted(df["Team"].dropna().unique().tolist())
    trade_team = st.selectbox("Select team to analyze", all_teams_trade, key="trade_team_sel")

    # Load profiles
    profiles = compute_team_profiles(df)

    if trade_team not in profiles.index:
        st.warning("Team profile not available. Ensure PlayerValue.py has been run.")
    else:
        tp = profiles.loc[trade_team]

        # ── Team profile cards ────────────────────────────────────────────────
        st.markdown("##### Team Profile")
        pc1, pc2, pc3, pc4, pc5 = st.columns(5)
        pc1.metric("Offensive Rating",  f"{tp.get('oEFF', '—'):.1f}" if pd.notna(tp.get("oEFF")) else "—",
                   help="Points scored per 100 possessions (oEFF)")
        pc2.metric("Off Rank",          f"#{int(tp.get('oEFF_rank', 0))}" if pd.notna(tp.get("oEFF_rank")) else "—",
                   help="1 = best offense in league")
        pc3.metric("Defensive Rating",  f"{tp.get('dEFF', '—'):.1f}" if pd.notna(tp.get("dEFF")) else "—",
                   help="Points allowed per 100 possessions (dEFF) — lower is better")
        pc4.metric("Def Rank",          f"#{int(tp.get('dEFF_rank', 0))}" if pd.notna(tp.get("dEFF_rank")) else "—",
                   help="1 = best defense in league (lowest dEFF)")
        w = int(tp.get("W", 0)) if pd.notna(tp.get("W")) else "—"
        l = int(tp.get("L", 0)) if pd.notna(tp.get("L")) else "—"
        pc5.metric("Record",            f"{w}–{l}")

        # ── Need badges ───────────────────────────────────────────────────────
        st.markdown("##### Identified Needs")
        badge_html = ""
        for label_key, score_key, color_key, icon in [
            ("Offense",  "off_label",   "off_color",   "🏹"),
            ("Defense",  "def_label",   "def_color",   "🛡️"),
            ("Skill",    "skill_label", "skill_color", "⭐"),
        ]:
            lbl   = tp.get(label_key.lower()[:3] + "_label", "—") if label_key == "Offense" else tp.get(label_key[:3].lower() + "_label", "—")
            color = tp.get(label_key.lower()[:3] + "_color", "#888") if label_key == "Offense" else tp.get(label_key[:3].lower() + "_color", "#888")
            # Use explicit keys
            lbl   = tp.get(f"{'off' if label_key=='Offense' else 'def' if label_key=='Defense' else 'skill'}_label", "—")
            color = tp.get(f"{'off' if label_key=='Offense' else 'def' if label_key=='Defense' else 'skill'}_color", "#888888")
            badge_html += (
                f"<span style='background:{color}; color:white; padding:6px 14px; "
                f"border-radius:20px; font-weight:bold; margin-right:10px; font-size:0.9em'>"
                f"{icon} {label_key}: {lbl}</span>"
            )
        st.markdown(badge_html, unsafe_allow_html=True)
        st.markdown("")

        # ── Build candidate pool ──────────────────────────────────────────────
        min_games = st.slider("Minimum games played", min_value=5, max_value=40, value=15, step=5)
        candidates = df[
            (df["Team"] != trade_team) &
            (df["EPM"].notna()) &
            (df["G"] >= min_games) &
            (~df["value_tier"].isin(["Replacement Level"]))
        ].copy()

        # Attainability
        candidates["attainability_label"]  = candidates["value_tier"].map(
            lambda t: TIER_ATTAINABILITY.get(t, ("Unknown", 0.4))[0]
        )
        candidates["attainability_weight"] = candidates["value_tier"].map(
            lambda t: TIER_ATTAINABILITY.get(t, ("Unknown", 0.4))[1]
        )

        # Fit scores
        candidates["off_fit"]   = candidates["O-EPM"] * 0.6 + candidates["composite_skill"] * 0.4
        candidates["def_fit"]   = candidates["D-EPM"] * 0.6 + candidates["composite_skill"] * 0.4
        candidates["skill_fit"] = candidates["composite_skill"]

        # Final scores
        candidates["off_score"]   = candidates["off_fit"]   * candidates["attainability_weight"]
        candidates["def_score"]   = candidates["def_fit"]   * candidates["attainability_weight"]
        candidates["skill_score"] = candidates["skill_fit"] * candidates["attainability_weight"]

        target_display_cols = ["Player", "Team", "EPM", "O-EPM", "D-EPM",
                               "composite_skill", "salary", "value_tier",
                               "attainability_label"]
        target_display_cols = [c for c in target_display_cols if c in candidates.columns]

        def style_attainability(val):
            color = ATTAINABILITY_COLORS.get(val, "#888888")
            return f"color: {color}; font-weight: bold"

        # ── Sub-tabs ──────────────────────────────────────────────────────────
        sub_off, sub_def, sub_best = st.tabs(
            ["🏹 Offensive Targets", "🛡️ Defensive Targets", "⭐ Best Overall"]
        )

        def render_targets(sub_tab, score_col, tab_label):
            with sub_tab:
                top = (
                    candidates
                    .sort_values(score_col, ascending=False)
                    .head(12)[target_display_cols]
                    .reset_index(drop=True)
                )
                top.index += 1   # 1-based ranking
                _tgt_fmt = {c: "{:.2f}" for c in
                            ("EPM", "O-EPM", "D-EPM", "composite_skill")
                            if c in top.columns}
                styled = (
                    top.style
                    .format(_tgt_fmt, na_rep="—")
                    .applymap(_style_tier,            subset=["value_tier"])
                    .applymap(style_attainability,    subset=["attainability_label"])
                )
                st.dataframe(styled, use_container_width=True)
                st.caption(
                    f"Sorted by {tab_label} fit × attainability. "
                    "Players with no EPM data excluded."
                )

        render_targets(sub_off,  "off_score",   "offensive")
        render_targets(sub_def,  "def_score",   "defensive")
        render_targets(sub_best, "skill_score", "overall skill")

        # ── Salary context ────────────────────────────────────────────────────
        with st.expander("💰 Salary matching context — what this team can offer"):
            own_roster_cols = ["Player", "salary", "value_tier", "WAR", "composite_skill"]
            if "salary__n" in df.columns:
                own_roster_cols.append("salary__n")
            own_roster = (
                df[df["Team"] == trade_team][own_roster_cols]
                .sort_values("salary__n" if "salary__n" in df.columns else "WAR",
                             ascending=False, na_position="last")
                .drop(columns=["salary__n"], errors="ignore")
            )
            _own_fmt = {c: "{:.2f}" for c in ("WAR", "composite_skill") if c in own_roster.columns}
            st.dataframe(
                own_roster.style
                .format(_own_fmt, na_rep="—")
                .applymap(_style_tier, subset=["value_tier"]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "In NBA trades, the acquiring team must send back roughly matching salary. "
                "Use this roster to identify players or packages that could match a target's salary."
            )
