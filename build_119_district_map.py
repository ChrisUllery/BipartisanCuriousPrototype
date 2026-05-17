from pathlib import Path

import geopandas as gpd
import plotly.graph_objects as go


DATA_DIR = Path("data")
RAW_MAP_DIR = DATA_DIR / "raw" / "district_maps"
DOCS_ASSETS_DIR = Path("docs") / "assets"

RAW_MAP_DIR.mkdir(parents=True, exist_ok=True)
DOCS_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

CD119_URL = "https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_cd119_500k.zip"

OUTPUT_HTML = DOCS_ASSETS_DIR / "district_map_119.html"

STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR",
    "78": "VI",
}


def main():
    print("Reading 119th Congressional District map from Census...")
    gdf = gpd.read_file(CD119_URL)

    print("Columns:")
    print(gdf.columns.tolist())

    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    gdf = gdf.reset_index(drop=True).copy()
    gdf["map_id"] = gdf.index.astype(str)
    gdf["state_abbr"] = gdf["STATEFP"].astype(str).map(STATE_FIPS_TO_ABBR)
    gdf["district_code"] = gdf["CD119FP"].astype(str).str.zfill(2)
    gdf["district_key"] = gdf["state_abbr"] + "-" + gdf["district_code"]
    gdf["district_label"] = gdf["district_key"] + " ? " + gdf["NAMELSAD"].astype(str)

    gdf["hover_text"] = (
        gdf["district_label"]
        + "<br>GEOID: "
        + gdf["GEOID"].astype(str)
        + "<br>STATEFP: "
        + gdf["STATEFP"].astype(str)
        + "<br>CD119FP: "
        + gdf["CD119FP"].astype(str)
    )

    print("Simplifying geometry...")
    gdf["geometry"] = gdf.geometry.simplify(0.03, preserve_topology=True)

    print(f"District rows: {len(gdf):,}")
    print("Sample:")
    print(gdf[["district_key", "GEOID", "STATEFP", "CD119FP", "NAMELSAD"]].head(10).to_string(index=False))

    geojson_output = RAW_MAP_DIR / "district_map_119_join_ready.geojson"
    gdf[[
        "district_key",
        "state_abbr",
        "district_code",
        "GEOID",
        "STATEFP",
        "CD119FP",
        "NAMELSAD",
        "geometry",
    ]].to_file(geojson_output, driver="GeoJSON")
    print(f"Wrote join-ready GeoJSON: {geojson_output}")

    print("Building GeoJSON...")
    geojson = gdf.set_index("map_id").__geo_interface__

    print("Building map...")
    fig = go.Figure(
        go.Choroplethmap(
            geojson=geojson,
            locations=gdf["map_id"],
            z=[1] * len(gdf),
            featureidkey="id",
            text=gdf["hover_text"],
            hovertemplate="%{text}<extra></extra>",
            colorscale="Blues",
            showscale=False,
            marker_opacity=0.55,
            marker_line_width=0.25,
        )
    )

    fig.update_layout(
        map=dict(
            style="carto-positron",
            center=dict(lat=39.5, lon=-98.35),
            zoom=2.7,
        ),
        height=760,
        margin=dict(r=0, t=40, l=0, b=0),
        title="119th Congressional Districts",
    )

    print("Writing HTML...")
    fig.write_html(
        OUTPUT_HTML,
        include_plotlyjs="cdn",
        full_html=True,
    )

    print(f"Wrote map: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
