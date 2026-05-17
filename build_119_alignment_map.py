from pathlib import Path
import math

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.graph_objects as go


DISTRICT_GEOJSON = Path("data/raw/district_maps/district_map_119_join_ready.geojson")
ENRICHED_ALIGNMENT_CSV = Path("data/dashboard/member_alignment_119_xml_enriched.csv")
SUMMARY_CSV = Path("data/processed/vote_summaries/VoteSummaries_119_xml.csv")
OUTPUT_HTML = Path("docs/assets/member_alignment_map_119.html")

OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)

KEEP_STATE_ABBRS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY",
}


# Map color behavior:
# 0% crossover = strong party color.
# CROSS_PARTY_PURPLE_AT or higher = pulled close to purple.
CROSS_PARTY_PURPLE_AT = 25.0


def get_alignment_score(row):
    republican_pct = row.get("with_republican_pct", np.nan)
    democratic_pct = row.get("with_democratic_pct", np.nan)

    if pd.isna(republican_pct) or pd.isna(democratic_pct):
        return np.nan

    return republican_pct - democratic_pct


def get_cross_party_pct(row):
    party = str(row.get("party", "")).strip()

    if party == "Republican":
        return row.get("with_democratic_pct", np.nan)

    if party == "Democratic":
        return row.get("with_republican_pct", np.nan)

    return np.nan


def get_party_adjusted_visual_score(row):
    """
    Visual map score:
      +100 = party-line Republican / deep red
       0   = high crossover / purple
      -100 = party-line Democrat / deep blue

    This keeps party direction visible while making crossover members less pure red/blue.
    """
    party = str(row.get("party", "")).strip()
    cross_party_pct = row.get("cross_party_pct", np.nan)

    if pd.isna(cross_party_pct):
        return np.nan

    crossover = max(0.0, min(float(cross_party_pct), CROSS_PARTY_PURPLE_AT))
    magnitude = 100.0 * (1.0 - (crossover / CROSS_PARTY_PURPLE_AT))

    if party == "Republican":
        return magnitude

    if party == "Democratic":
        return -magnitude

    return np.nan


def fmt_pct(value):
    if pd.isna(value):
        return "NA"
    return f"{value:.1f}%"


def fmt_num(value):
    if pd.isna(value):
        return "NA"
    return f"{int(value):,}"


def build_stat_card(title, value, subtitle=""):
    subtitle_html = f'<div class="card-subtitle">{subtitle}</div>' if subtitle else ""
    return f"""
    <div class="stat-card">
        <div class="card-title">{title}</div>
        <div class="card-value">{value}</div>
        {subtitle_html}
    </div>
    """


def build_top10_table(df):
    if df.empty:
        return "<p>No ranking data available.</p>"

    display = df.copy().reset_index(drop=True)
    display.index = display.index + 1

    rows = []
    for rank, row in display.iterrows():
        name = row["full_name"] if pd.notna(row["full_name"]) else row["representative"]
        rows.append(
            f"""
            <tr>
                <td>{rank}</td>
                <td>{name}</td>
                <td>{row['party']}</td>
                <td>{row['district_key']}</td>
                <td>{row['cross_party_pct']:.1f}%</td>
                <td>{row['with_republican_pct']:.1f}%</td>
                <td>{row['with_democratic_pct']:.1f}%</td>
                <td>{int(row['votes_cast_on_party_split_roll_calls'])}</td>
            </tr>
            """
        )

    return f"""
    <table class="ranking-table">
        <thead>
            <tr>
                <th>#</th>
                <th>Member</th>
                <th>Party</th>
                <th>District</th>
                <th>Cross-party %</th>
                <th>With R majority</th>
                <th>With D majority</th>
                <th>Votes cast</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    """


def build_party_donut_html(summary_df):
    if summary_df.empty:
        return "<p>No party summary available.</p>"

    color_map = {
        "Republican": "#b2182b",
        "Democratic": "#2166ac",
    }

    fig = go.Figure(
        data=[
            go.Pie(
                labels=summary_df["party"],
                values=summary_df["total_cross_party_votes"],
                hole=0.5,
                sort=False,
                marker=dict(
                    colors=[color_map.get(p, "#7b3294") for p in summary_df["party"]]
                ),
                textinfo="label+percent",
                hovertemplate=(
                    "%{label}<br>"
                    "Share of cross-party votes: %{percent}<br>"
                    "Total cross-party votes: %{value}<extra></extra>"
                ),
            )
        ]
    )

    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=360,
        showlegend=False,
    )

    return fig.to_html(include_plotlyjs=False, full_html=False)



def main():
    print("Reading district GeoJSON...")
    districts = gpd.read_file(DISTRICT_GEOJSON)
    districts = districts[districts["state_abbr"].isin(KEEP_STATE_ABBRS)].copy()

    print("Reading enriched XML alignment...")
    members = pd.read_csv(ENRICHED_ALIGNMENT_CSV)

    print("Reading XML vote summaries...")
    summaries = pd.read_csv(SUMMARY_CSV)

    members = members[members["district_key"].notna()].copy()
    members["district_key"] = members["district_key"].astype(str).str.strip()
    members["alignment_score"] = members.apply(get_alignment_score, axis=1)
    members["cross_party_pct"] = members.apply(get_cross_party_pct, axis=1)
    members["party_adjusted_visual_score"] = members.apply(get_party_adjusted_visual_score, axis=1)

    # Keep one row per current district
    members = members.sort_values(
        ["district_key", "votes_cast_on_party_split_roll_calls"],
        ascending=[True, False],
    ).drop_duplicates(subset=["district_key"], keep="first")

    keep_cols = [
        "district_key",
        "bioguide_id",
        "representative",
        "full_name",
        "party",
        "state_abbr",
        "district",
        "official_url",
        "with_republican_pct",
        "with_democratic_pct",
        "alignment_score",
        "cross_party_pct",
        "party_adjusted_visual_score",
        "Republican Majority",
        "Democratic Majority",
        "Not Voting",
        "Present",
        "Neither",
        "party_split_roll_calls",
        "votes_cast_on_party_split_roll_calls",
        "missed_party_split_votes_pct",
    ]
    members = members[[c for c in keep_cols if c in members.columns]].copy()

    merged = districts.merge(
        members,
        on="district_key",
        how="left",
        suffixes=("", "_member"),
    )

    matched = merged["representative"].notna().sum()
    unmatched = len(merged) - matched

    print(f"District rows: {len(merged):,}")
    print(f"Districts with matched member stats: {matched:,}")
    print(f"Districts without matched member stats: {unmatched:,}")

    merged = merged.reset_index(drop=True)
    merged["map_id"] = merged.index.astype(str)

    merged["hover_text"] = (
        "<b>" + merged["district_key"].fillna("") + "</b>"
        + "<br>Member: " + merged["representative"].fillna("No matched member")
        + "<br>Full name: " + merged["full_name"].fillna("")
        + "<br>Party: " + merged["party"].fillna("")
        + "<br>Alignment score: " + merged["alignment_score"].round(1).astype(str).replace("nan", "NA")
        + "<br>With Republican majority: " + merged["with_republican_pct"].round(1).astype(str).replace("nan", "NA") + "%"
        + "<br>With Democratic majority: " + merged["with_democratic_pct"].round(1).astype(str).replace("nan", "NA") + "%"
        + "<br>Cross-party voting: " + merged["cross_party_pct"].round(1).astype(str).replace("nan", "NA") + "%"
        + "<br>Map color score: " + merged["party_adjusted_visual_score"].round(1).astype(str).replace("nan", "NA")
        + "<br>Votes cast on party-split roll calls: "
        + merged["votes_cast_on_party_split_roll_calls"].fillna(0).astype(int).astype(str)
        + "<br>Missed party-split votes: "
        + merged["missed_party_split_votes_pct"].round(1).astype(str).replace("nan", "NA") + "%"
    )

    print("Simplifying geometry for browser performance...")
    merged["geometry"] = merged.geometry.simplify(0.02, preserve_topology=True)

    print("Building GeoJSON...")
    geojson = merged.set_index("map_id").__geo_interface__

    # Party-adjusted visual scale.
    # The sign shows party direction. The magnitude fades toward purple as crossover rises.
    max_abs_score = 100

    print(
        f"Using party-adjusted crossover color scale: "
        f"0% crossover = full party color; {CROSS_PARTY_PURPLE_AT:.0f}%+ crossover = near purple"
    )

    fig = go.Figure(
        go.Choroplethmap(
            geojson=geojson,
            locations=merged["map_id"],
            z=merged["party_adjusted_visual_score"],
            featureidkey="id",
            text=merged["hover_text"],
            hovertemplate="%{text}<extra></extra>",
            colorscale=[
                [0.00, "#2166ac"],  # strong Democratic / party-line blue
                [0.25, "#67a9cf"],  # lighter blue
                [0.50, "#b8a0d9"],  # lavender / crossover center
                [0.75, "#ef8a9a"],  # lighter red
                [1.00, "#b2182b"],  # strong Republican / party-line red
            ],
            zmin=-max_abs_score,
            zmax=max_abs_score,
            zmid=0,
            colorbar=dict(title="D line ? purple ? R line"),
            marker_opacity=0.82,
            marker_line_width=0.25,
            marker_line_color="white",
        )
    )

    fig.update_layout(
        map=dict(
            style="carto-positron",
            center=dict(lat=38.5, lon=-96.5),
            zoom=3.0,
        ),
        height=700,
        margin=dict(r=0, t=10, l=0, b=0),
    )

    map_html = fig.to_html(include_plotlyjs="cdn", full_html=False)

    # Dashboard stats
    party_split_roll_calls = summaries[
        summaries["rep_position"].isin(["yea", "nay"])
        & summaries["dem_position"].isin(["yea", "nay"])
        & (summaries["rep_position"] != summaries["dem_position"])
    ].shape[0]

    current_members = members.copy()
    avg_votes_cast = current_members[
        current_members["party"].isin(["Republican", "Democratic"])
        & current_members["votes_cast_on_party_split_roll_calls"].notna()
    ]["votes_cast_on_party_split_roll_calls"].mean()

    min_qualifying_votes = max(25, avg_votes_cast / 2)

    ranked_members = current_members[
        current_members["party"].isin(["Republican", "Democratic"])
        & current_members["cross_party_pct"].notna()
        & (current_members["votes_cast_on_party_split_roll_calls"] >= min_qualifying_votes)
    ].copy()

    ranked_members = ranked_members.sort_values(
        ["cross_party_pct", "votes_cast_on_party_split_roll_calls"],
        ascending=[False, False],
    )

    most_bipartisan = ranked_members.iloc[0] if not ranked_members.empty else None

    rep_ranked = ranked_members[ranked_members["party"] == "Republican"].copy()
    dem_ranked = ranked_members[ranked_members["party"] == "Democratic"].copy()

    most_bipartisan_rep = rep_ranked.iloc[0] if not rep_ranked.empty else None
    most_bipartisan_dem = dem_ranked.iloc[0] if not dem_ranked.empty else None

    median_cross_party = ranked_members["cross_party_pct"].median() if not ranked_members.empty else np.nan

    top10 = ranked_members.head(10).copy()
    top10_table_html = build_top10_table(top10)

    ranked_members["cross_party_votes"] = ranked_members.apply(
        lambda r: r["Democratic Majority"] if r["party"] == "Republican" else r["Republican Majority"],
        axis=1,
    )

    party_summary = (
        ranked_members.groupby("party")
        .agg(
            members=("party", "size"),
            avg_cross_party_pct=("cross_party_pct", "mean"),
            median_cross_party_pct=("cross_party_pct", "median"),
            total_cross_party_votes=("cross_party_votes", "sum"),
            avg_votes_cast=("votes_cast_on_party_split_roll_calls", "mean"),
        )
        .reset_index()
    )

    party_summary_html = ""
    party_donut_html = ""

    if not party_summary.empty:
        party_donut_html = build_party_donut_html(party_summary)

        party_summary_sorted = party_summary.sort_values("avg_cross_party_pct", ascending=False).reset_index(drop=True)
        higher_party = party_summary_sorted.iloc[0]
        lower_party = party_summary_sorted.iloc[1] if len(party_summary_sorted) > 1 else None

        comparison_line = ""
        if lower_party is not None:
            gap = higher_party["avg_cross_party_pct"] - lower_party["avg_cross_party_pct"]
            comparison_line = (
                f"<p><strong>{higher_party['party']}</strong> currently has the higher average cross-party voting rate "
                f"among qualified current members: <strong>{higher_party['avg_cross_party_pct']:.1f}%</strong>, "
                f"compared with <strong>{lower_party['avg_cross_party_pct']:.1f}%</strong> for {lower_party['party'].lower()} members. "
                f"That is a gap of <strong>{gap:.1f} percentage points</strong>.</p>"
            )

        rows = []
        for _, row in party_summary.iterrows():
            rows.append(
                f"""
                <tr>
                    <td>{row['party']}</td>
                    <td>{int(row['members'])}</td>
                    <td>{row['avg_cross_party_pct']:.1f}%</td>
                    <td>{row['median_cross_party_pct']:.1f}%</td>
                    <td>{int(row['total_cross_party_votes'])}</td>
                </tr>
                """
            )

        party_summary_html = f"""
        <div class="section-card">
            <h2>Which party crosses party lines more often?</h2>
            {comparison_line}
            <div class="two-col">
                <div>
                    <table class="ranking-table">
                        <thead>
                            <tr>
                                <th>Party</th>
                                <th>Qualified members</th>
                                <th>Average cross-party %</th>
                                <th>Median cross-party %</th>
                                <th>Total cross-party votes</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(rows)}
                        </tbody>
                    </table>
                    <div class="small-note">
                        Average and median cross-party percentages are usually the best way to answer which party is more likely to cross party lines.
                        The donut chart at right shows each party's share of all cross-party votes cast by qualified current members.
                    </div>
                </div>
                <div class="chart-box">
                    {party_donut_html}
                </div>
            </div>
        </div>
        """

    cards_html = ""
    cards_html += build_stat_card(
        "Party-split roll calls analyzed",
        f"{party_split_roll_calls:,}",
        "Only votes where the Republican and Democratic majorities were on opposite sides.",
    )
    cards_html += build_stat_card(
        "Districts with current member matches",
        f"{matched:,}",
        f"{unmatched} districts still unmatched in the current map build.",
    )
    cards_html += build_stat_card(
        "Median cross-party voting rate",
        fmt_pct(median_cross_party),
        f"Among current members with at least {min_qualifying_votes:.0f} qualifying votes cast, equal to half the average or 25, whichever is higher.",
    )

    if most_bipartisan is not None:
        mb_name = most_bipartisan["full_name"] if pd.notna(most_bipartisan["full_name"]) else most_bipartisan["representative"]
        cards_html += build_stat_card(
            "Most bipartisan current member",
            mb_name,
            f"{most_bipartisan['district_key']} ? {most_bipartisan['party']} ? Cross-party voting {most_bipartisan['cross_party_pct']:.1f}%",
        )

    highlight_html = ""
    if most_bipartisan_rep is not None or most_bipartisan_dem is not None:
        rep_line = ""
        dem_line = ""

        if most_bipartisan_rep is not None:
            rep_name = most_bipartisan_rep["full_name"] if pd.notna(most_bipartisan_rep["full_name"]) else most_bipartisan_rep["representative"]
            rep_line = f"<li><strong>Most bipartisan Republican:</strong> {rep_name} ({most_bipartisan_rep['district_key']}) ? {most_bipartisan_rep['cross_party_pct']:.1f}% cross-party voting.</li>"

        if most_bipartisan_dem is not None:
            dem_name = most_bipartisan_dem["full_name"] if pd.notna(most_bipartisan_dem["full_name"]) else most_bipartisan_dem["representative"]
            dem_line = f"<li><strong>Most bipartisan Democrat:</strong> {dem_name} ({most_bipartisan_dem['district_key']}) ? {most_bipartisan_dem['cross_party_pct']:.1f}% cross-party voting.</li>"

        highlight_html = f"""
        <div class="section-card">
            <h2>Quick takeaways</h2>
            <ul class="bullets">
                {rep_line}
                {dem_line}
                <li><strong>How to read the map:</strong> red districts are Republican-held, blue districts are Democratic-held, and districts become more purple as their member crosses party lines more often.</li>
                <li><strong>Why the colors look stronger now:</strong> the scale is based on the central observed range in the current Congress, using the 5th and 95th percentiles instead of a fixed -100 to +100 range. That makes real variation inside this Congress easier to see without letting outliers control the map.</li>
            </ul>
        </div>
        """

    methodology_html = """
    <div class="section-card">
        <h2>Methodology</h2>
        <p>
            This map uses only <strong>party-split roll calls</strong> ? votes where the Republican majority
            and Democratic majority were on opposite sides. That filters out neutral votes where both parties
            mostly agreed.
        </p>
        <p>
            Each district is colored by an <strong>alignment score</strong>:
        </p>
        <ul class="bullets">
            <li><strong>Red districts</strong> are represented by Republicans; <strong>blue districts</strong> are represented by Democrats.</li>
            <li>More saturated red or blue means the member stayed closer to their party majority on party-split roll calls.</li>
            <li>Districts move toward <strong>purple</strong> as the member crosses party lines more often.</li>
            <li>In this prototype, members at roughly <strong>{CROSS_PARTY_PURPLE_AT:.0f}%</strong> cross-party voting or higher are pulled close to purple.</li>
        </ul>
        <p>
            The bipartisan ranking below is based on <strong>cross-party voting percentage</strong>:
            for Republicans, that means the share of qualifying votes cast with the Democratic majority;
            for Democrats, it means the share cast with the Republican majority.
        </p>
    </div>
    """

    html = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>119th Congress Voting Alignment Map</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            margin: 0;
            font-family: Arial, sans-serif;
            background: #f5f7fb;
            color: #1f2937;
        }}
        .page {{
            max-width: 1500px;
            margin: 0 auto;
            padding: 24px;
        }}
        h1 {{
            margin: 0 0 8px 0;
            font-size: 34px;
        }}
        h2 {{
            margin-top: 0;
        }}
        .intro {{
            font-size: 16px;
            line-height: 1.5;
            color: #475569;
            margin-bottom: 18px;
            max-width: 1000px;
        }}
        .map-panel, .section-card {{
            background: #ffffff;
            border: 1px solid #d8dee9;
            border-radius: 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .map-panel {{
            padding: 18px;
            margin-bottom: 20px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: #ffffff;
            border: 1px solid #d8dee9;
            border-radius: 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            padding: 16px;
        }}
        .card-title {{
            font-size: 14px;
            color: #64748b;
            margin-bottom: 8px;
        }}
        .card-value {{
            font-size: 28px;
            font-weight: bold;
            line-height: 1.2;
            margin-bottom: 6px;
        }}
        .card-subtitle {{
            font-size: 13px;
            color: #475569;
            line-height: 1.4;
        }}
        .section-card {{
            padding: 18px;
            margin-bottom: 20px;
        }}
        .bullets {{
            margin-top: 10px;
            padding-left: 20px;
            line-height: 1.6;
        }}
        .ranking-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        .ranking-table th, .ranking-table td {{
            border-bottom: 1px solid #e5e7eb;
            padding: 10px 8px;
            text-align: left;
            vertical-align: top;
        }}
        .ranking-table th {{
            background: #f8fafc;
        }}
        .small-note {{
            font-size: 13px;
            color: #64748b;
            margin-top: 10px;
        }}
        .two-col {{
            display: grid;
            grid-template-columns: 1.4fr 0.9fr;
            gap: 20px;
            align-items: start;
        }}
        .chart-box {{
            background: #f8fafc;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 10px;
        }}
        @media (max-width: 980px) {{
            .two-col {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="page">
        <h1>119th Congress: Party-line voting and crossover behavior</h1>
        <div class="intro">
            This map shows how members of the current House delegation behaved on votes where the two parties were meaningfully split.
            It is designed to compare <strong>formal party identity</strong> with <strong>actual voting behavior</strong>.
        </div>

        <div class="map-panel">
            {map_html}
        </div>

        <div class="stats-grid">
            {cards_html}
        </div>

        {highlight_html}

        <div class="section-card">
            <h2>Ten most bipartisan current members</h2>
            <p>
                Ranked by how often they voted with the opposite party's majority on qualifying party-split roll calls.
                To reduce noise, this ranking only includes current members who cast at least <strong>{min_qualifying_votes:.0f}</strong> qualifying votes, equal to half the average or 25, whichever is higher.
            </p>
            {top10_table_html}
            <div class="small-note">
                Cross-party % means voting with the other party's majority: Republicans with the Democratic majority, or Democrats with the Republican majority.
            </div>
        </div>

        {party_summary_html}

        {methodology_html}
    </div>
</body>
</html>
"""

    print("Writing HTML...")
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote map dashboard: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
