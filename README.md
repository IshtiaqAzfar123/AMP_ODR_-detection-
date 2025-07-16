# 🛰️ Automated Change Detection Pipeline

This project performs automated change detection and analysis using satellite imagery from three different years (2016, 2017, and 2020). The process includes detecting changes between different year pairs, timestamp analysis from OpenStreetMap (OSM), SSIM computation, and detailed logging.

---

## 📂 Input Files

The pipeline expects **three image files** as input:

- `input_2016.<ext>`
- `input_2017.<ext>`
- `input_2020.<ext>`

Supported formats typically include `.tif`, `.png`, or `.jpg`.

---

## 🔁 Pipeline Workflow

The pipeline proceeds in the following steps:

### 1. **Change Detection: 2016 → 2017**
- Compares the 2016 and 2017 input images.
- Generates a **detected change image** for this interval.
- **Output:** `detected_2016_2017.<ext>`

### 2. **Change Detection: 2017 → 2020**
- Compares the 2017 and 2020 input images.
- Generates a **detected change image** for this interval.
- **Output:** `detected_2017_2020.<ext>`

### 3. **OSM Timestamp Extraction**
- Extracts OSM version timestamps related to detected changes (typically from GeoJSON or Overpass API).
- **Output:** `osm_timestamps.csv`

### 4. **SSIM Calculation**
- Computes Structural Similarity Index (SSIM) to quantify visual differences.
- Saves results as annotated images.
- **Output:** `ssim_2016_2017.png`, `ssim_2017_2020.png`

### 5. **Logging**
- All pipeline events, messages, and timestamps are recorded.
- **Output:** `pipeline_log.txt`

### 6. **XODR generation**
- XODR generation was created automatically, It's actually made manually.

---

## 📦 Output Summary

| Output File                  | Description                                        |
|-----------------------------|----------------------------------------------------|
| `detected_2016_2017.<ext>`  | Change map from 2016 to 2017                       |
| `detected_2017_2020.<ext>`  | Change map from 2017 to 2020                       |
| `osm_timestamps.csv`        | Extracted OSM versioning timestamps                |
| `ssim_*.png`                | Structural similarity maps                         |
| `pipeline_log.txt`          | Full execution log with timestamps and events      |

---

## 🛠️ Execution

To run the program:

```bash
python run_pipeline.py --input2016 path/to/2016.geojson --input2017 path/to/2017.geojson --input2020 path/to/2020.geojson
