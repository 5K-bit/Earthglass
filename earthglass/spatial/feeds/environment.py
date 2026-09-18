import csv
import io
from datetime import datetime

from .base import Feed, ProviderSpec, number, timestamp


class EarthquakeFeed(Feed):
    spec = ProviderSpec(
        "usgs",
        "earthquakes",
        "Earthquakes",
        300,
        "USGS worldwide last-day earthquake feed",
        "U.S. Geological Survey",
        license_url="https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
    )
    source_url = "https://earthquake.usgs.gov/"
    endpoint = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    )

    def fetch(self, viewport, now):
        data = self.http.json(self.endpoint, cache_ttl=self.spec.interval_seconds)

        def parse(row):
            point, properties = row["geometry"]["coordinates"], row["properties"]
            return self.observation(
                source_id=row["id"],
                entity_id=f"usgs:{row['id']}",
                position={"latitude": point[1], "longitude": point[0]},
                observed_at=timestamp(properties["time"] / 1000),
                received_at=now,
                properties={
                    "title": properties.get("title"),
                    "magnitude": properties.get("mag"),
                    "depth_m": point[2] * 1000 if len(point) > 2 else None,
                    "place": properties.get("place"),
                },
                source_url=properties.get("url") or self.source_url,
            )

        return self.normalize(data.get("features"), parse)


class FiresFeed(Feed):
    spec = ProviderSpec(
        "firms",
        "fires",
        "Active fires",
        1800,
        "NASA VIIRS near-real-time thermal anomalies in the selected area",
        "NASA FIRMS / VIIRS",
        credential="firms_map_key",
    )
    source_url = "https://firms.modaps.eosdis.nasa.gov/"

    def fetch(self, viewport, now):
        self.bounded(viewport, 30)
        key = self.key()
        area = f"{viewport.west},{viewport.south},{viewport.east},{viewport.north}"
        # Credentials are used only in this request, never in observation provenance.
        text = self.http.text(
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{area}/1"
        )
        rows = list(csv.DictReader(io.StringIO(text)))

        def parse(row):
            lat, lon = float(row["latitude"]), float(row["longitude"])
            time_text = str(row["acq_time"]).zfill(4)
            observed = datetime.fromisoformat(
                row["acq_date"]
                + "T"
                + time_text[:2]
                + ":"
                + time_text[2:]
                + ":00+00:00"
            )
            ident = f"{row.get('satellite', 'VIIRS')}:{lat:.5f}:{lon:.5f}:{observed.isoformat()}"
            return self.observation(
                source_id=ident,
                position={"latitude": lat, "longitude": lon},
                observed_at=observed,
                received_at=now,
                properties={
                    "brightness_k": number(row.get("bright_ti4")),
                    "frp_mw": number(row.get("frp")),
                    "provider_confidence": row.get("confidence"),
                    "satellite": row.get("satellite"),
                    "meaning": "Thermal anomaly; not independently confirmed fire",
                },
            )

        return self.normalize(rows, parse)


class WeatherFeed(Feed):
    spec = ProviderSpec(
        "open_meteo_gfs",
        "weather",
        "Weather (GFS)",
        900,
        "Nine GFS model samples across the selected area; not station observations",
        "Weather data by Open-Meteo.com / NOAA GFS",
        license_url="https://open-meteo.com/en/licence",
    )
    source_url = "https://open-meteo.com/"

    def fetch(self, viewport, now):
        center_lat, center_lon = viewport.center
        height = min(120, viewport.north - viewport.south)
        width = (
            viewport.east - viewport.west
            if viewport.east >= viewport.west
            else 360 + viewport.east - viewport.west
        )
        points = [
            (
                max(-85, min(85, center_lat + y * height / 3)),
                (center_lon + x * width / 3 + 180) % 360 - 180,
            )
            for y in (-1, 0, 1)
            for x in (-1, 0, 1)
        ]
        data = self.http.json(
            "https://api.open-meteo.com/v1/gfs",
            cache_ttl=900,
            params={
                "latitude": ",".join(f"{lat:.2f}" for lat, lon in points),
                "longitude": ",".join(f"{lon:.2f}" for lat, lon in points),
                "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,surface_pressure",
                "hourly": "temperature_2m,precipitation,cloud_cover,wind_speed_10m,wind_direction_10m,surface_pressure",
                "forecast_days": 3,
                "past_days": 1,
                "wind_speed_unit": "ms",
                "timezone": "UTC",
            },
        )
        rows = data if isinstance(data, list) else [data]

        def parse(row):
            current = row.get("current") or {}
            lat, lon = float(row["latitude"]), float(row["longitude"])
            source_time = str(current["time"])
            if not source_time.endswith("Z") and "+" not in source_time:
                source_time += "+00:00"
            return self.observation(
                source_id=f"{lat:.2f}:{lon:.2f}",
                position={"latitude": lat, "longitude": lon},
                observed_at=timestamp(source_time),
                received_at=now,
                kind="predicted",
                properties={
                    "name": f"GFS {lat:.2f}°, {lon:.2f}°",
                    "temperature_c": current.get("temperature_2m"),
                    "humidity_percent": current.get("relative_humidity_2m"),
                    "precipitation_mm": current.get("precipitation"),
                    "weather_code": current.get("weather_code"),
                    "cloud_cover_percent": current.get("cloud_cover"),
                    "pressure_pa": number(current.get("surface_pressure")) * 100 if number(current.get("surface_pressure")) is not None else None,
                    "wind_speed_mps": current.get("wind_speed_10m"),
                    "wind_direction_deg": current.get("wind_direction_10m"),
                    "forecast": forecast_samples(row.get("hourly") or {}),
                    "model": "NOAA GFS via Open-Meteo",
                    "display_radius_m": max(1000, min(1000000, height * 111320 / 7)),
                    "meaning": "Discrete model samples; colored symbols do not imply uniform conditions between samples",
                    "attribution_url": "https://open-meteo.com/",
                },
            )

        return self.normalize(rows, parse)


class TemperatureFeed(WeatherFeed):
    spec = ProviderSpec(
        "open_meteo_temperature",
        "temperature",
        "Temperature",
        900,
        "Nine GFS model temperature samples across the selected area",
        "Weather data by Open-Meteo.com / NOAA GFS",
        license_url="https://open-meteo.com/en/licence",
    )


class WeatherFieldFeed(WeatherFeed):
    def __init__(self,http,credentials=lambda _:None,*,field="wind"):
        super().__init__(http,credentials)
        self.field=field
        self.spec=ProviderSpec("open_meteo_"+field,field,field.replace("_"," ").title(),900,"Nine NOAA GFS samples across the view; discrete model output","Weather data by Open-Meteo.com / NOAA GFS",license_url="https://open-meteo.com/en/licence")

def forecast_samples(hourly):
    fields={"temperature_2m":"temperature_c","precipitation":"precipitation_mm","cloud_cover":"cloud_cover_percent","wind_speed_10m":"wind_speed_mps","wind_direction_10m":"wind_direction_deg","surface_pressure":"pressure_pa"}
    samples=[]
    for index,instant in enumerate(hourly.get("time",[])[:96]):
        time_text=instant if instant.endswith("Z") or "+" in instant else instant+"+00:00"
        sample={"valid_at":timestamp(time_text).isoformat()}
        for source,destination in fields.items():
            values=hourly.get(source) or []
            value=number(values[index]) if index<len(values) else None
            sample[destination]=value*100 if value is not None and source=="surface_pressure" else value
        samples.append(sample)
    return samples
