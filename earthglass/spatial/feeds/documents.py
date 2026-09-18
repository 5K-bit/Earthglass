"""Non-spatial products use the same scheduler, health and public HTTP boundary."""

import json
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

from ..network import ProviderError
from .base import Feed, ProviderSpec

IMAGERY_PRODUCTS = {
    "true_color": (
        "VIIRS_SNPP_CorrectedReflectance_TrueColor",
        "True color",
        "NASA GIBS / VIIRS S-NPP",
    ),
    "goes_clouds": (
        "GOES-East_ABI_GeoColor",
        "GOES East clouds / GeoColor",
        "NOAA GOES ABI via NASA GIBS",
    ),
    "infrared": (
        "GOES-East_ABI_Band13_Clean_Infrared",
        "GOES East infrared",
        "NOAA GOES ABI via NASA GIBS",
    ),
    "water_vapor": (
        "MODIS_Terra_Water_Vapor_5km_Day",
        "Water vapor",
        "NASA GIBS / MODIS Terra",
    ),
    "aerosols": ("MODIS_Terra_Aerosol", "Aerosols", "NASA GIBS / MODIS Terra"),
    "snow_ice": (
        "MODIS_Terra_NDSI_Snow_Cover",
        "Snow and ice",
        "NASA GIBS / MODIS Terra",
    ),
    "vegetation": (
        "MODIS_Terra_NDVI_8Day",
        "Vegetation / NDVI",
        "NASA GIBS / MODIS Terra",
    ),
    "sea_surface": (
        "MODIS_Aqua_L2_Sea_Surface_Temp_Day",
        "Sea surface temperature",
        "NASA GIBS / MODIS Aqua",
    ),
}


class DocumentFeed(Feed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._document = {}
        self._document_lock = threading.Lock()

    def configure_cache(self, directory):
        super().configure_cache(directory)
        self.document_path = Path(directory) / (self.spec.id + "-document.json")
        try:
            if self.document_path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Oversized cached document")
            value = json.loads(self.document_path.read_text(encoding="utf-8"))
            if value.get("provider") != self.spec.id:
                raise ValueError("Wrong cached provider")
            self._document = value
        except (OSError, ValueError, TypeError):
            pass

    def save_document(self, data, now):
        value = {
            "provider": self.spec.id,
            "retrieved_at": now.isoformat(),
            "data": data,
        }
        with self._document_lock:
            self._document = value
        if getattr(self, "document_path", None):
            self.document_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.document_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
            temporary.replace(self.document_path)

    def document(self):
        with self._document_lock:
            return json.loads(json.dumps(self._document))


class ImageryFeed(DocumentFeed):
    spec = ProviderSpec(
        "nasa_gibs",
        "imagery",
        "NASA / NOAA imagery",
        1800,
        "Curated GIBS layers; GOES East regional coverage; source cadence and missing frames apply",
        "NASA GIBS / NOAA GOES",
    )
    source_url = "https://www.earthdata.nasa.gov/eosdis/science-system-description/eosdis-standard-products/global-imagery-browse-services"
    endpoint = (
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml"
    )

    def configure_cache(self, directory):
        super().configure_cache(directory)
        if not self._document:
            try:
                self._document = json.loads(
                    (
                        Path(__file__).resolve().parents[1]
                        / "data"
                        / "imagery-catalog.json"
                    ).read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                pass

    def fetch(self, viewport, now):
        self.rejected = 0
        xml = self.http.text(self.endpoint)
        root = ET.fromstring(xml)
        ns = {
            "w": "http://www.opengis.net/wmts/1.0",
            "o": "http://www.opengis.net/ows/1.1",
        }
        by_id = {
            item.findtext("o:Identifier", namespaces=ns): item
            for item in root.findall(".//w:Layer", ns)
        }
        products = []
        for key, (ident, label, attribution) in IMAGERY_PRODUCTS.items():
            element = by_id.get(ident)
            if element is None:
                self.rejected += 1
                products.append(
                    {
                        "id": key,
                        "label": label,
                        "available": False,
                        "attribution": attribution,
                    }
                )
                continue
            matrix = element.findtext(
                "w:TileMatrixSetLink/w:TileMatrixSet", namespaces=ns
            )
            level = int(matrix.rsplit("Level", 1)[-1])
            format_ = element.findtext("w:Format", namespaces=ns)
            if not 0 <= level <= 12 or format_ not in {"image/png", "image/jpeg"}:
                continue
            products.append(
                {
                    "id": key,
                    "source_layer": ident,
                    "label": label,
                    "available": True,
                    "attribution": attribution,
                    "matrix_set": matrix,
                    "maximum_level": level,
                    "extension": "png" if format_ == "image/png" else "jpeg",
                    "default_time": element.findtext(
                        "w:Dimension/w:Default", namespaces=ns
                    ),
                    "time_ranges": [
                        e.text for e in element.findall("w:Dimension/w:Value", ns)
                    ][-500:],
                    "provider": "NOAA GOES via NASA GIBS"
                    if key in {"goes_clouds", "infrared"}
                    else "NASA GIBS",
                    "source_url": self.endpoint,
                }
            )
        if not any(item["available"] for item in products):
            raise ProviderError(
                "imagery_metadata", "No supported imagery products were advertised"
            )
        self.save_document(products, now)
        return []


class SpaceWeatherFeed(DocumentFeed):
    spec = ProviderSpec(
        "noaa_swpc",
        "space_weather",
        "Space weather",
        300,
        "Global indices and upstream solar-wind readings; these do not identify a surface location",
        "NOAA Space Weather Prediction Center",
    )
    source_url = "https://www.swpc.noaa.gov/"
    endpoints = {
        "kp": "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
        "geomagnetic": "https://services.swpc.noaa.gov/products/noaa-scales.json",
        "solar_wind": "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json",
        "alerts": "https://services.swpc.noaa.gov/products/alerts.json",
    }

    def fetch(self, viewport, now):
        old = self.document().get("data", {})
        data = {}
        failures = 0
        for name, url in self.endpoints.items():
            try:
                rows = self.http.json(url, cache_ttl=300)
                if name == "geomagnetic":
                    current = rows.get("0") if isinstance(rows, dict) else None
                    if not isinstance(current, dict) or not isinstance(
                        current.get("G"), dict
                    ):
                        raise ProviderError(
                            "invalid_schema", "NOAA geomagnetic scale is missing"
                        )
                    scale = str(current["G"].get("Scale"))
                    if scale not in {"0", "1", "2", "3", "4", "5"}:
                        raise ProviderError(
                            "invalid_schema", "NOAA geomagnetic scale is unavailable"
                        )
                    rows = [
                        {
                            "scale": int(scale),
                            "text": str(current["G"].get("Text") or "unknown"),
                            "time_tag": str(current.get("DateStamp", ""))
                            + "T"
                            + str(current.get("TimeStamp", ""))
                            + "Z",
                            "meaning": "Latest NOAA reported geomagnetic storm scale",
                        }
                    ]
                if not isinstance(rows, list):
                    raise ProviderError("invalid_schema", "SWPC product is not a list")
                if rows and isinstance(rows[0], list):
                    keys = rows[0]
                    rows = [dict(zip(keys, row)) for row in rows[1:]]
                if name == "solar_wind":
                    rows = [
                        {
                            **r,
                            "speed": r.get("proton_speed"),
                            "density": r.get("proton_density"),
                            "temperature": r.get("proton_temperature"),
                        }
                        for r in rows
                        if isinstance(r, dict) and r.get("active") is True
                    ]
                rows = rows[-2000:] if name != "alerts" else rows[:100]
                data[name] = {
                    "records": rows,
                    "retrieved_at": now.isoformat(),
                    "source_url": url,
                    "cached": False,
                }
            except ProviderError:
                failures += 1
                data[name] = {
                    **old.get(
                        name, {"records": [], "source_url": url, "retrieved_at": None}
                    ),
                    "cached": True,
                }
        if failures == len(self.endpoints):
            raise ProviderError(
                "upstream_unavailable", "NOAA space-weather products are unavailable"
            )
        self.rejected = failures
        self.save_document(data, now)
        return []
