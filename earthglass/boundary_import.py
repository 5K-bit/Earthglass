"""Convert local Natural Earth boundary shapefiles to a compact offline package."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from earthglass.reference_import import file_record


def prepare(root: Path, output: Path):
    import shapefile
    from shapely.geometry import shape, mapping
    features, sources = [], []
    for stem, disputed in (("ne_10m_admin_0_boundary_lines_land", False),
                           ("ne_10m_admin_0_boundary_lines_disputed_areas", True)):
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
                geometry = shape(item.shape.__geo_interface__)
                if geometry.is_empty:
                    continue
                if geometry.geom_type not in {"LineString", "MultiLineString"}:
                    raise ValueError("Expected boundary lines")
                features.append({"type": "Feature", "id": f"{stem}:{count}",
                    "geometry": mapping(geometry.simplify(0.02, preserve_topology=True)),
                    "properties": {"disputed": disputed,
                        "classification": item.record.as_dict().get("featurecla", "boundary")}})
                count += 1
        if not count:
            raise ValueError(f"Empty dataset: {stem}")
        sources.append({"dataset": stem, "features": count, "files": [file_record(p) for p in files]})
    data = {"type": "FeatureCollection", "features": features,
            "metadata": {"coverage": "worldwide land borders", "simplification_degrees": 0.02,
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
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.output)))
