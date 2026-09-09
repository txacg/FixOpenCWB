"""CWA F-D0047 parsing, independent of HA and the host timezone."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Literal
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
ForecastType = Literal["hourly", "twice_daily"]


class CwaDataError(ValueError):
    """Invalid CWA data; messages never include raw responses or credentials."""


@dataclass(frozen=True)
class Sample:
    start: datetime
    end: datetime | None
    value: Any


@dataclass(frozen=True)
class ForecastPeriod:
    start: datetime
    end: datetime
    values: dict[str, Any]


@dataclass(frozen=True)
class CwaForecast:
    location_name: str
    latitude: float | None
    longitude: float | None
    forecast_type: ForecastType
    periods: tuple[ForecastPeriod, ...]


def parse_timestamp(value: Any) -> datetime:
    """Offsets are authoritative; documented legacy naive times mean Taipei."""
    if not isinstance(value, str) or len(value.strip()) < 19:
        raise CwaDataError("Missing or invalid forecast timestamp")
    try:
        result = datetime.fromisoformat(value.strip())
    except ValueError:
        raise CwaDataError("Invalid forecast timestamp") from None
    if result.tzinfo is None:
        result = result.replace(tzinfo=TAIPEI)
    return result.astimezone(UTC)


def number(value: Any) -> float | None:
    """Do not interpret a bound, range, or missing marker as a measurement."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) and result not in (-99, -999) else None


def wind_bearing(value: Any) -> float | None:
    directions = {
        "北": 0,
        "北北東": 22.5,
        "東北": 45,
        "東北東": 67.5,
        "東": 90,
        "東南東": 112.5,
        "東南": 135,
        "南南東": 157.5,
        "南": 180,
        "南南西": 202.5,
        "西南": 225,
        "西南西": 247.5,
        "西": 270,
        "西北西": 292.5,
        "西北": 315,
        "北北西": 337.5,
    }
    if isinstance(value, str):
        direction = value.strip().removeprefix("偏").removesuffix("風")
        if direction in directions:
            return directions[direction]
    numeric = number(value)
    return numeric if numeric is not None and 0 <= numeric <= 360 else None


FIELDS = {
    "Temperature": "temperature",
    "MaxTemperature": "max_temperature",
    "MinTemperature": "min_temperature",
    "ApparentTemperature": "apparent_temperature",
    "DewPoint": "dew_point",
    "RelativeHumidity": "humidity",
    "WindSpeed": "wind_speed",
    "WindDirection": "wind_bearing",
    "BeaufortScale": "beaufort_scale",
    "ProbabilityOfPrecipitation": "precipitation_probability",
    "UVIndex": "uv_index",
    "Weather": "weather",
    "WeatherCode": "weather_code",
    "WeatherDescription": "description",
}
# Old value arrays have a documented positional schema. Modern objects do not.
OLD_FIELDS = {
    "T": ("Temperature",),
    "MaxT": ("MaxTemperature",),
    "MinT": ("MinTemperature",),
    "AT": ("ApparentTemperature",),
    "Td": ("DewPoint",),
    "RH": ("RelativeHumidity",),
    "WS": ("WindSpeed", "BeaufortScale"),
    "WD": ("WindDirection",),
    "Wx": ("Weather", "WeatherCode"),
    "UVI": ("UVIndex",),
    "PoP3h": ("ProbabilityOfPrecipitation",),
    "PoP6h": ("ProbabilityOfPrecipitation",),
    "PoP12h": ("ProbabilityOfPrecipitation",),
    "WeatherDescription": ("WeatherDescription",),
}


def _series(elements: list[dict]) -> dict[str, list[Sample]]:
    series: dict[str, list[Sample]] = {}
    for element in elements:
        name = element.get("ElementName", element.get("elementName"))
        times = element.get("Time", element.get("time", []))
        if not isinstance(times, list):
            raise CwaDataError("Invalid element timeline")
        for row in times:
            if not isinstance(row, dict):
                raise CwaDataError("Invalid forecast sample")
            start = parse_timestamp(
                row.get(
                    "DataTime",
                    row.get("dataTime", row.get("StartTime", row.get("startTime"))),
                )
            )
            raw_end = row.get("EndTime", row.get("endTime"))
            end = parse_timestamp(raw_end) if raw_end is not None else None
            if end is not None and end <= start:
                raise CwaDataError("Invalid forecast interval")
            if name in ("Wx", "天氣現象", "Weather"):
                series.setdefault("weather_timeline", []).append(
                    Sample(start, end, None)
                )
            values = row.get("ElementValue", row.get("elementValue"))
            if values is None:
                continue
            if not isinstance(values, list):
                raise CwaDataError("Invalid element values")
            named = {}
            for index, item in enumerate(values):
                if not isinstance(item, dict):
                    continue
                named.update({key: val for key, val in item.items() if key in FIELDS})
                if "value" in item and index < len(OLD_FIELDS.get(name, ())):
                    named[OLD_FIELDS[name][index]] = item["value"]
            for key, raw in named.items():
                field = FIELDS[key]
                if field in ("weather", "description"):
                    value = (
                        raw.strip() if isinstance(raw, str) and raw.strip() else None
                    )
                elif field == "wind_bearing":
                    value = wind_bearing(raw)
                else:
                    value = number(raw)
                    if (
                        field in ("humidity", "precipitation_probability")
                        and value is not None
                        and not 0 <= value <= 100
                    ):
                        value = None
                    if (
                        field
                        in ("wind_speed", "beaufort_scale", "uv_index", "weather_code")
                        and value is not None
                        and value < 0
                    ):
                        value = None
                series.setdefault(field, []).append(Sample(start, end, value))
    for samples in series.values():
        samples.sort(key=lambda sample: sample.start)
    return series


def _match(samples: list[Sample], start: datetime, end: datetime) -> Sample | None:
    exact = [
        sample for sample in samples if sample.start == start and sample.end == end
    ]
    if not exact:
        exact = [
            sample for sample in samples if sample.start == start and sample.end is None
        ]
    if not exact:
        exact = [
            sample
            for sample in samples
            if sample.end is not None and sample.start <= start and end <= sample.end
        ]
    if len(exact) > 1:
        raise CwaDataError("Ambiguous overlapping forecast values")
    return exact[0] if exact else None


def parse_forecast(
    payload: dict, location_name: str, forecast_type: ForecastType
) -> CwaForecast:
    """Match points exactly and intervals by coverage, never by array index."""
    if forecast_type not in ("hourly", "twice_daily"):
        raise CwaDataError("Unsupported forecast type; daily is not implemented")
    if not isinstance(payload, dict) or payload.get("success") not in (True, "true"):
        raise CwaDataError("CWA response was not successful")
    try:
        records = payload["records"]
        groups = records.get("Locations", records.get("locations", []))
        locations = [
            loc
            for group in groups
            for loc in group.get("Location", group.get("location", []))
            if loc.get("LocationName", loc.get("locationName", "")).replace("台", "臺")
            == location_name.replace("台", "臺")
        ]
        if len(locations) != 1:
            raise CwaDataError(
                "Requested location missing or ambiguous in CWA response"
            )
        location = locations[0]
        series = _series(
            location.get("WeatherElement", location.get("weatherElement", []))
        )
    except (KeyError, TypeError, AttributeError):
        raise CwaDataError("Malformed CWA forecast structure") from None
    weather = series.get("weather_timeline", [])
    if not weather:
        raise CwaDataError("Missing weather timeline")
    anchors = (
        weather
        if forecast_type == "twice_daily"
        else series.get("temperature", []) or weather
    )
    periods = []
    for index, anchor in enumerate(anchors):
        end = anchor.end
        if end is None:
            containing = [
                sample.end
                for sample in weather
                if sample.end and sample.start <= anchor.start < sample.end
            ]
            candidates = containing + (
                [anchors[index + 1].start] if index + 1 < len(anchors) else []
            )
            if not candidates:
                raise CwaDataError("Point forecast has no validity boundary")
            end = min(candidates)
        if forecast_type == "twice_daily":
            local = anchor.start.astimezone(TAIPEI)
            if end - anchor.start != timedelta(hours=12) or (
                local.hour,
                local.minute,
                local.second,
            ) not in ((6, 0, 0), (18, 0, 0)):
                raise CwaDataError("Expected a CWA 06-18 or 18-06 forecast interval")
        if end <= anchor.start:
            raise CwaDataError("Duplicate or invalid forecast boundary")
        values = {}
        for field, samples in series.items():
            sample = _match(samples, anchor.start, end)
            if sample is None or sample.value is None:
                continue
            # A three-hour probability must not become an hourly probability.
            if field == "precipitation_probability" and (
                sample.start != anchor.start or sample.end != end
            ):
                continue
            values[field] = sample.value
        periods.append(ForecastPeriod(anchor.start, end, values))
    if not periods:
        raise CwaDataError("Empty forecast")
    return CwaForecast(
        location_name,
        number(location.get("Latitude", location.get("lat"))),
        number(location.get("Longitude", location.get("lon"))),
        forecast_type,
        tuple(periods),
    )


def select_current(data: CwaForecast, now: datetime) -> ForecastPeriod | None:
    """Select a valid prediction without removing it from forecast output."""
    if now.tzinfo is None:
        raise ValueError("Current time must be timezone-aware")
    return next(
        (period for period in data.periods if period.start <= now < period.end), None
    )


def condition_for_code(
    code: float | None, is_daytime: bool | None = None
) -> str | None:
    """CWA WeatherIcon.js codes mapped to supported HA conditions."""
    if code == 1:
        return "clear-night" if is_daytime is False else "sunny"
    if code in (2, 3, 4):
        return "partlycloudy"
    if code in (5, 6, 7):
        return "cloudy"
    if code in (15, 16, 17, 18, 21, 22, 33, 34, 35, 36, 41):
        return "lightning-rainy"
    if code in (8, 9, 10, 11, 12, 13, 14, 19, 20, 29, 30, 31, 32, 38, 39):
        return "rainy"
    if code in (24, 25, 26, 27, 28):
        return "fog"
    if code in (23, 37):
        return "snowy-rainy"
    if code == 42:
        return "snowy"
    return None


def to_ha_forecast(
    period: ForecastPeriod,
    forecast_type: ForecastType,
    *,
    is_daytime: bool | None = None,
) -> dict[str, Any]:
    """Export only sourced native values; HA performs unit conversion."""
    values = period.values
    result: dict[str, Any] = {"datetime": period.start.astimezone(UTC).isoformat()}
    if forecast_type == "twice_daily":
        is_daytime = period.start.astimezone(TAIPEI).hour == 6
        result["is_daytime"] = is_daytime
        temperature = values.get("max_temperature", values.get("temperature"))
        if "min_temperature" in values:
            result["native_templow"] = values["min_temperature"]
    elif forecast_type == "hourly":
        temperature = values.get("temperature")
    else:
        raise CwaDataError("Unsupported forecast type")
    if temperature is not None:
        result["native_temperature"] = temperature
    condition = condition_for_code(values.get("weather_code"), is_daytime)
    if condition is not None:
        result["condition"] = condition
    for source, destination in {
        "apparent_temperature": "native_apparent_temperature",
        "humidity": "humidity",
        "wind_speed": "native_wind_speed",
        "wind_bearing": "wind_bearing",
        "precipitation_probability": "precipitation_probability",
    }.items():
        if source in values:
            result[destination] = values[source]
    return result
