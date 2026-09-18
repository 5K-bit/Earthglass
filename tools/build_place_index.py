"""Build the bundled, attributable GeoNames city index from bounded public downloads."""
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = "https://download.geonames.org/export/dump/cities15000.zip"

def download(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "OBEOS-Earth/0.4 (GeoNames offline city index)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Download exceeds city-index bound")
    return data

def main():
    source = download(URL, 8 * 1024 * 1024)
    countries = {}
    for line in download("https://download.geonames.org/export/dump/countryInfo.txt", 100000).decode("utf-8").splitlines():
        fields = line.split("\t")
        if not line.startswith("#") and len(fields) > 4:
            countries[fields[0]] = fields[4]
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        info = archive.getinfo("cities15000.txt")
        if info.file_size > 32 * 1024 * 1024:
            raise ValueError("Expanded city index is too large")
        raw = archive.read(info).decode("utf-8")
    cities = []
    for line in raw.splitlines():
        f = line.split("\t")
        if len(f) < 19:
            continue
        names = list(dict.fromkeys([f[1], f[2], *f[3].split(",")]))
        cities.append({"id": f[0], "name": f[1], "country": countries.get(f[8], f[8]), "latitude": float(f[4]), "longitude": float(f[5]), "population": int(f[14] or 0), "aliases": [n for n in names if 1 < len(n) <= 100][:24]})
    result = {"attribution": "GeoNames", "license": "https://creativecommons.org/licenses/by/4.0/", "source": URL, "retrieved": datetime.now(timezone.utc).isoformat(), "source_sha256": hashlib.sha256(source).hexdigest(), "cities": cities}
    directory = ROOT / "earthglass/spatial/data"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cities15000.json.gz").write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))
    print(json.dumps({"cities": len(cities), "source_sha256": result["source_sha256"]}))

if __name__ == "__main__":
    main()
