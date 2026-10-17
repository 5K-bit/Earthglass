"""Convert local Natural Earth boundary shapefiles to a compact offline package."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from earthglass.reference_import import file_record


def prepare(root: Path, output: Path, *, include_us_states: bool = False):
    import shapefile
    from shapely.geometry import shape, mapping
    features, sources = [], []
    datasets = [("ne_10m_admin_0_boundary_lines_land", False),
                ("ne_10m_admin_0_boundary_lines_disputed_areas", True)]
    if include_us_states:
        datasets.append(("ne_10m_admin_1_states_provinces", False))
    for stem, disputed in datasets:
        state_layer = stem == "ne_10m_admin_1_states_provinces"
        paths = sorted(root.rglob(stem + ".shp"))
        if not paths:
            raise ValueError(f"Missing dataset: {stem}")
        path = paths[0]
        files = [path.with_suffix(ext) for ext in (".shp", ".shx", ".dbf", ".prj")]
        if not all(p.is_file() for p in files):
            raise ValueError(f"Incomplete dataset: {stem}")
        if "WGS_1984" not in files[-1].read_text():
            raise ValueError("Expected geographic WGS84")
        count = 0
        with shapefile.Reader(str(path), encoding="utf-8") as reader:
            for item in reader.iterShapeRecords():
                record = item.record.as_dict()
                if state_layer and record.get("adm0_a3") != "USA":
                    continue
                geometry = shape(item.shape.__geo_interface__)
                if geometry.is_empty:
                    continue
                if state_layer:
                    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                        raise ValueError("Expected state polygons")
                    geometry = geometry.boundary
                if geometry.geom_type not in {"LineString", "MultiLineString"}:
                    raise ValueError("Expected boundary lines")
                features.append({"type": "Feature", "id": f"{stem}:{count}",
                    "geometry": mapping(geometry.simplify(0.02, preserve_topology=True)),
                    "properties": {"disputed": disputed,
                        "classification": "us_state" if state_layer else record.get("featurecla", "boundary"),
                        "name": record.get("name", "") if state_layer else ""}})
                count += 1
        if not count:
            raise ValueError(f"Empty dataset: {stem}")
        sources.append({"dataset": stem, "features": count, "files": [file_record(p) for p in files]})
    data = {"type": "FeatureCollection", "features": features,
            "metadata": {"coverage": "worldwide land borders" + (" and US state outlines" if include_us_states else ""), "simplification_degrees": 0.02,
                "attribution": "Natural Earth (public domain)", "sources": sources}}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, separators=(",", ":"), allow_nan=False)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"features": len(features), "bytes": output.stat().st_size}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-us-states", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.output, include_us_states=args.include_us_states)))
