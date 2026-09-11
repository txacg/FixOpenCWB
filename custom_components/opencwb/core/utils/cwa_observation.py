"""Official O-A0001/O-A0003 observations and deterministic station selection."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

from .cwa_forecast import CwaDataError, number, parse_timestamp

MAX_AGE = {"O-A0001-001": timedelta(minutes=90), "O-A0003-001": timedelta(minutes=30)}


@dataclass(frozen=True)
class Observation:
    station_id: str
    station_name: str
    county: str
    town: str
    latitude: float
    longitude: float
    observed_at: datetime
    dataset: str
    values: dict[str, Any]
    quality: dict[str, str]

    def fresh(self, now: datetime) -> bool:
        return -timedelta(minutes=5) <= now - self.observed_at <= MAX_AGE[self.dataset]


@dataclass(frozen=True)
class StationSelection:
    observation: Observation | None
    distance_km: float | None
    status: str


def observation_condition(weather: str, daytime: bool = True) -> str | None:
    """CWA observation descriptions are cloud cover + phenomenon, not Wx codes."""
    if "雷" in weather:
        return "lightning-rainy" if "雨" in weather else "lightning"
    if "雹" in weather or "冰珠" in weather:
        return "hail"
    if "雪" in weather:
        return "snowy-rainy" if "雨" in weather else "snowy"
    if "雨" in weather:
        return "pouring" if "大雨" in weather else "rainy"
    if any(x in weather for x in ("霧", "靄", "霾")):
        return "fog"
    return {
        "晴": "sunny" if daytime else "clear-night",
        "多雲": "partlycloudy",
        "陰": "cloudy",
    }.get(weather)


def _measurement(raw: Any, field: str, quality: dict[str, str]) -> float | None:
    marker = str(raw).strip()
    special = {
        "X": "equipment_error",
        "T": "trace",
        "-99": "missing",
        "-99.0": "missing",
        "-98": "dry_last_6h" if field == "precipitation_today" else "missing",
        "-98.0": "dry_last_6h" if field == "precipitation_today" else "missing",
    }
    if marker in special:
        quality[field] = special[marker]
        return None
    value = number(raw)
    if field == "wind_bearing" and value == 990:
        quality[field] = "variable"
        return None
    if value is None or (field != "temperature" and value < 0):
        quality[field] = "missing"
        return None
    if field == "humidity" and value > 100 or field == "wind_bearing" and value > 360:
        quality[field] = "invalid"
        return None
    return value


def parse_observations(payload: dict, dataset: str) -> tuple[Observation, ...]:
    if (
        dataset not in MAX_AGE
        or not isinstance(payload, dict)
        or payload.get("success") not in (True, "true")
    ):
        raise CwaDataError("Unsuccessful CWA observation response")
    try:
        stations = payload["records"]["Station"]
        if not isinstance(stations, list):
            raise CwaDataError("Invalid observation station list")
        result = []
        for station in stations:
            try:
                geo = station["GeoInfo"]
                coordinates = next(
                    c for c in geo["Coordinates"] if c["CoordinateName"] == "WGS84"
                )
                lat, lon = (
                    number(coordinates["StationLatitude"]),
                    number(coordinates["StationLongitude"]),
                )
                if (
                    lat is None
                    or lon is None
                    or not -90 <= lat <= 90
                    or not -180 <= lon <= 180
                ):
                    continue
                raw_time = station["ObsTime"]["DateTime"]
                if datetime.fromisoformat(raw_time).tzinfo is None:
                    continue
                observed_at = parse_timestamp(raw_time)
                values, quality = {}, {}
                elements = station["WeatherElement"]
                for source, destination in {
                    "AirTemperature": "temperature",
                    "RelativeHumidity": "humidity",
                    "AirPressure": "pressure",
                    "WindDirection": "wind_bearing",
                    "WindSpeed": "wind_speed",
                    "UVIndex": "uv_index",
                }.items():
                    value = _measurement(elements.get(source), destination, quality)
                    if value is not None:
                        values[destination] = value
                rain = _measurement(
                    elements.get("Now", {}).get("Precipitation"),
                    "precipitation_today",
                    quality,
                )
                if rain is not None:
                    values["precipitation_today"] = rain
                gust_info = elements.get("GustInfo", {})
                gust = _measurement(
                    gust_info.get("PeakGustSpeed"), "wind_gust", quality
                )
                if gust is not None:
                    try:
                        gust_time = parse_timestamp(
                            gust_info["Occurred_at"]["DateTime"]
                        )
                    except (CwaDataError, KeyError, TypeError):
                        quality["wind_gust"] = "missing_timestamp"
                    else:
                        if timedelta(0) <= observed_at - gust_time <= timedelta(days=1):
                            values.update(
                                wind_gust=gust, gust_observed_at=gust_time.isoformat()
                            )
                weather = elements.get("Weather")
                if isinstance(weather, str) and observation_condition(weather.strip()):
                    values["weather"] = weather.strip()
                visibility = elements.get("VisibilityDescription")
                if isinstance(visibility, str) and visibility.strip() not in (
                    "",
                    "-99",
                    "-98",
                    "X",
                    "-",
                ):
                    # Descriptions such as >30 or 11-15 are not exact measurements.
                    values["visibility_description"] = visibility.strip()[:30]
                result.append(
                    Observation(
                        str(station["StationId"]),
                        str(station["StationName"]),
                        geo["CountyName"].replace("台", "臺"),
                        geo["TownName"],
                        lat,
                        lon,
                        observed_at,
                        dataset,
                        values,
                        quality,
                    )
                )
            except (KeyError, TypeError, ValueError, StopIteration):
                # One malformed station must not discard all other real stations.
                continue
        if not result:
            raise CwaDataError("No valid CWA observation stations")
        return tuple(result)
    except (KeyError, TypeError):
        raise CwaDataError("Malformed CWA observations") from None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a = (
        sin(radians(lat2 - lat1) / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    )
    return 6371.0088 * 2 * asin(min(1, sqrt(a)))


def select_station(
    observations: tuple[Observation, ...],
    county: str,
    town: str,
    latitude: float,
    longitude: float,
    now: datetime,
) -> StationSelection:
    """Prefer usable temperature, then in-town, then distance; never blend stations."""
    if now.tzinfo is None:
        raise ValueError("Selection time must be timezone-aware")
    nearby = [
        (o, distance_km(latitude, longitude, o.latitude, o.longitude))
        for o in observations
    ]
    nearby = [(o, d) for o, d in nearby if d <= 50]
    fresh = [
        (o, d)
        for o, d in nearby
        if o.fresh(now)
        and any(
            k in o.values for k in ("temperature", "humidity", "pressure", "wind_speed")
        )
    ]
    if not fresh:
        return StationSelection(None, None, "stale" if nearby else "unavailable")
    # Resolve duplicates by station first: same station's most useful/freshest
    # dataset wins. Missing individual fields remain missing on that station.
    best = {}
    for obs, distance in sorted(
        fresh,
        key=lambda row: (
            "temperature" not in row[0].values,
            -row[0].observed_at.timestamp(),
            -len(row[0].values),
            row[0].dataset,
        ),
    ):
        best.setdefault(obs.station_id, (obs, distance))
    obs, distance = min(
        best.values(),
        key=lambda row: (
            "temperature" not in row[0].values,
            not (row[0].county == county and (town == county or row[0].town == town)),
            row[1],
            row[0].station_id,
        ),
    )
    return StationSelection(obs, round(distance, 3), "fresh")
