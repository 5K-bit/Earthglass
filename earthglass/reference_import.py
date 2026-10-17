"""Prepare global Natural Earth label data offline; never runs during rendering."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

LAYERS = {
    "countries": "ne_10m_admin_0_countries",
    "cities": "ne_10m_populated_places",
    "oceans": "ne_10m_geography_marine_polys",
}


def file_record(path: Path) -> dict:
    with path.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": checksum}


def label_feature(record: dict, category: str, point=None):
    values = {str(k).lower(): v for k, v in record.items()}
    name = values.get("name_en") or values.get("name") or values.get("admin")
    if category == "states":
        name = values.get("name") or name
    lon = values.get("label_x", values.get("longitude"))
    lat = values.get("label_y", values.get("latitude"))
    if (lon is None or lat is None) and point is not None:
        lon, lat = point[:2]
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not name or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "name": str(name), "category": category,
            "rank": values.get("scalerank", 10),
            "country": values.get("adm0name") or values.get("admin"),
        },
    }


def prepare(roots: list[Path], output: Path, *, include_us_states: bool = False) -> dict:
    import shapefile  # Optional preparation dependency; not needed to serve maps.
    from shapely.geometry import shape

    features, sources = [], []
    layers = dict(LAYERS)
    if include_us_states:
        layers["states"] = "ne_10m_admin_1_states_provinces"
    for category, stem in layers.items():
        candidates = sorted({p.resolve() for root in roots for p in root.rglob(stem + ".shp")})
        if not candidates:
            raise ValueError(f"Missing required worldwide dataset: {stem}")
        source = candidates[0]
        companions = [source.with_suffix(ext) for ext in (".shp", ".shx", ".dbf", ".prj")]
        if not all(p.is_file() for p in companions):
            raise ValueError(f"Incomplete shapefile: {source.name}")
        crs = companions[-1].read_text(encoding="utf-8")
        if "WGS_1984" not in crs and "WGS 84" not in crs:
            raise ValueError(f"Expected WGS84 geographic coordinates: {source.name}")
        count, rejected = 0, 0
        with shapefile.Reader(str(source), encoding="utf-8") as reader:
            for item in reader.iterShapeRecords():
                record = item.record.as_dict()
                if category == "states" and record.get("adm0_a3") != "USA":
                    continue
                point = item.shape.points[0] if item.shape.shapeType == 1 else None
                if category in {"oceans", "states"} and item.shape.points:
                    geometry = shape(item.shape.__geo_interface__)
                    if not geometry.is_empty:
                        if geometry.geom_type == "MultiPolygon":
                            geometry = max(geometry.geoms, key=lambda polygon: polygon.area)
                        position = geometry.representative_point()
                        point = [position.x, position.y]
                feature = label_feature(record, category, point)
                if feature is None:
                    rejected += 1
                    continue
                feature["id"] = f"{category}:{count}"
                features.append(feature)
                count += 1
        if not count:
            raise ValueError(f"No valid labels in {source.name}; existing package retained")
        sources.append({
            "dataset": stem, "features": count, "rejected": rejected,
            "files": [file_record(p) for p in companions],
        })
    package = {"type": "FeatureCollection", "features": features,
               "metadata": {"schema_version": 1, "coverage": "worldwide",
                            "attribution": "Natural Earth (public domain)",
                            "sources": sources}}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(package, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"features": len(features), "bytes": output.stat().st_size, "sources": sources}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-us-states", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.output, include_us_states=args.include_us_states), indent=2))


if __name__ == "__main__":
    main()
