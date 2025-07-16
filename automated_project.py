import geopandas as gpd
from shapely.geometry import box, LineString
import requests
from xml.etree import ElementTree as ET
import csv
import json
import os
import matplotlib.pyplot as plt
from rasterio.transform import from_bounds
from rasterio.features import rasterize
import numpy as np
from skimage.metrics import structural_similarity as ssim
from skimage.color import rgb2gray
from skimage.filters import threshold_otsu
from io import BytesIO
from PIL import Image
from datetime import datetime
import logging

# ------------------ Logging Setup ------------------

logging.basicConfig(
    filename="pipeline_log.txt",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} - {msg}")
    logging.info(msg)

# ------------------ Detection Functions ------------------

def load_map(path, bbox):
    log(f"Loading map: {path}")
    gdf = gpd.read_file(path, bbox=bbox)
    return gdf[gdf.geometry.type == "LineString"]

def exclude_a100(gdf):
    if "name" in gdf.columns:
        gdf = gdf[~gdf["name"].str.contains("A100", na=False)]
    if "ref" in gdf.columns:
        gdf = gdf[~gdf["ref"].str.contains("A100", na=False)]
    return gdf

def detect_new_roads(old_path, new_path, bbox, output_path):
    log(f"Detecting changes: {old_path} ? {new_path}")
    old_map = exclude_a100(load_map(old_path, bbox)).to_crs(epsg=32633)
    new_map = exclude_a100(load_map(new_path, bbox)).to_crs(epsg=32633)
    buffered_old = old_map.copy()
    buffered_old["geometry"] = buffered_old.geometry.buffer(5)
    new_roads = new_map[~new_map.geometry.apply(
        lambda g: any(g.intersects(b) for b in buffered_old.geometry)
    )]
    if not new_roads.empty:
        new_roads.to_crs(epsg=4326).to_file(output_path, driver="GeoJSON")
        log(f"Saved detected roads to {output_path}")
    else:
        log("No new roads detected.")
    return new_roads

# ------------------ Overpass API ------------------

def fetch_construction_from_overpass(minx, miny, maxx, maxy, tag):
    log(f"Querying Overpass API for: {tag}")
    query = f"""
    [out:json][timeout:25];
    way["highway"="construction"]({miny},{minx},{maxy},{maxx});
    out geom;
    """
    try:
        response = requests.get("https://overpass.kumi.systems/api/interpreter", params={"data": query}, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        log(f"Overpass API request failed: {e}")
        return gpd.GeoDataFrame(columns=["geometry"], crs="EPSG:4326")

    data = response.json()
    features = []
    for el in data["elements"]:
        if el["type"] == "way" and "geometry" in el:
            coords = [(pt["lon"], pt["lat"]) for pt in el["geometry"]]
            if len(coords) >= 2:
                line = LineString(coords)
                tags = el.get("tags", {})
                tags["osm_id"] = el["id"]
                features.append({"geometry": line, "properties": tags})
    gdf = gpd.GeoDataFrame([f["properties"] for f in features],
                           geometry=[f["geometry"] for f in features],
                           crs="EPSG:4326")
    log(f"Overpass returned {len(gdf)} constructions.")
    return gdf

# ------------------ Timestamp using Fixed Way IDs ------------------

def get_osm_way_timestamp(way_id):
    url = f"https://api.openstreetmap.org/api/0.6/way/{way_id}/history"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            versions = root.findall("way")
            if versions:
                return versions[0].attrib.get("timestamp")
            else:
                return "No history found"
        else:
            return f"Failed to fetch: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

# ------------------ SSIM ------------------

def render_geojson_to_image(gdf, bounds=None, figsize=(12, 12), dpi=300):
    fig, ax = plt.subplots(figsize=figsize)
    if bounds:
        ax.set_xlim(bounds[0], bounds[2])
        ax.set_ylim(bounds[1], bounds[3])
    gdf.plot(ax=ax, color='black', linewidth=2)
    ax.axis('off')
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=dpi, bbox_inches='tight', pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    return rgb2gray(np.array(img))

def binarize_image(img_gray):
    return (img_gray > threshold_otsu(img_gray)).astype(float)

def run_structural_ssim(file1, file2, output_png="ssim_diff.png"):
    log(f"Computing SSIM: {file1} vs {file2}")
    gdf1 = gpd.read_file(file1)
    gdf2 = gpd.read_file(file2)
    bounds = box(*gdf1.total_bounds).union(box(*gdf2.total_bounds)).bounds
    img1 = binarize_image(render_geojson_to_image(gdf1, bounds))
    img2 = binarize_image(render_geojson_to_image(gdf2, bounds))
    score, _ = ssim(img1, img2, win_size=5, full=True, data_range=1.0)
    plt.imsave(output_png, np.abs(img1 - img2), cmap='hot')
    log(f"SSIM Score: {score:.4f}")
    return round(score, 4)

# ------------------ Patch Export ------------------

def convert_geojson_to_patch(input_geojson, output_json, output_txt):
    log(f"Converting to patch: {input_geojson}")
    try:
        gdf = gpd.read_file(input_geojson)
    except Exception as e:
        log(f"Failed to load GeoJSON: {e}")
        return
    patch = {"patch": {"roads": []}}
    lines = []
    for _, row in gdf.iterrows():
        geometry = row.geometry
        if geometry.geom_type != "LineString":
            continue
        coords = list(geometry.coords)
        props = row.to_dict()
        road_entry = {
            "id": props.get("@id") or props.get("osm_id", "unknown"),
            "geometry": coords,
            "ref": props.get("ref", ""),
            "name": props.get("name", ""),
            "highway": props.get("highway", "")
        }
        patch["patch"]["roads"].append(road_entry)
        lines.append(f"ID: {road_entry['id']} | Ref: {road_entry['ref']} | Name: {road_entry['name']} | Type: {road_entry['highway']} | Points: {len(coords)}")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(patch, f, indent=2)
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"Patch saved: {output_json}, Summary saved: {output_txt}")

# ------------------ Main Pipeline ------------------

def main():
    log(" Starting Full A100 Pipeline")

    minx, miny, maxx, maxy = 13.270, 52.490, 13.310, 52.520
    bbox = box(minx, miny, maxx, maxy)

    detect_new_roads("2016.geojson", "2017.geojson", bbox, "changes_2016_2017.geojson")
    detect_new_roads("2017.geojson", "2020.geojson", bbox, "changes_2017_2020.geojson")

    overpass = fetch_construction_from_overpass(minx, miny, maxx, maxy, "2016 to 2017")
    if not overpass.empty:
        overpass.to_file("overpass_2016_2017.geojson", driver="GeoJSON")

    #  Your fixed way IDs
    way_ids = [26144116, 169762615, 227985279, 407967885, 410233146]
    with open("a100_timestamps.csv", mode="w", newline='', encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Way ID", "First Mapped Timestamp"])
        for wid in way_ids:
            timestamp = get_osm_way_timestamp(wid)
            writer.writerow([wid, timestamp])
            log(f"Way ID: {wid} ? First mapped: {timestamp}")

    run_structural_ssim("2016.geojson", "2017.geojson", "ssim_2016_2017.png")

    convert_geojson_to_patch(
        input_geojson="changes_2016_2017.geojson",
        output_json="patch_2016_2017.json",
        output_txt="patch_2016_2017.txt"
    )

    log(" Pipeline Complete")

if __name__ == "__main__":
    main()
