"""Authoritative normalized snapshot consumed by HA entities, actions and tools."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .cwa_display import (
    DEFAULT_CONDITION_MAX_AGE,
    DEFAULT_CONDITION_POLICY,
    ObservedWeather,
    display_condition,
)
from .cwa_forecast import CwaForecast, to_ha_forecast
from .cwa_observation import StationSelection, observation_condition

UNITS = {
    "temperature": "°C",
    "pressure": "hPa",
    "wind_speed": "m/s",
    "precipitation_today": "mm",
    "humidity": "%",
}


@dataclass(frozen=True)
class ForecastProduct:
    data: CwaForecast
    dataset: str
    fetched_at: datetime
    issued_at: datetime | None = None


@dataclass(frozen=True)
class WeatherSnapshot:
    location: str
    latitude: float | None
    longitude: float | None
    observation: StationSelection
    forecasts: dict[str, ForecastProduct]
    updated_at: datetime
    errors: dict[str, str] = field(default_factory=dict)
    daytime: bool = True
    daylight: dict[str, bool] = field(default_factory=dict)
    condition_policy: str = DEFAULT_CONDITION_POLICY
    condition_max_age_minutes: int = DEFAULT_CONDITION_MAX_AGE
    last_observed_weather: ObservedWeather | None = None

    def current_values(self, now: datetime) -> dict[str, Any]:
        obs = self.observation.observation
        if obs is None or not obs.fresh(now):
            return {}
        values = dict(obs.values)
        condition = observation_condition(values.get("weather", ""), self.daytime)
        if condition:
            values["condition"] = condition
        return values

    def ha_forecast(self, kind: str, now: datetime) -> list[dict]:
        if (product := self.forecasts.get(kind)) is None:
            return []
        return [
            to_ha_forecast(p, kind, is_daytime=self.daylight.get(p.start.isoformat()))
            for p in product.data.periods
            if p.end > now
        ]

    def structured(self, now: datetime, kinds: tuple[str, ...], count: int) -> dict:
        current = {
            "source": "observation",
            "status": self.observation.status,
            "condition": None,
        }
        obs = self.observation.observation
        if obs:
            fresh = obs.fresh(now)
            current.update(
                status=("cached" if obs.dataset in self.errors else "fresh")
                if fresh
                else "stale",
                station={
                    "id": obs.station_id,
                    "name": obs.station_name,
                    "distance_km": self.observation.distance_km,
                },
                dataset=obs.dataset,
                observed_at=obs.observed_at.isoformat(),
                age_seconds=max(0, int((now - obs.observed_at).total_seconds())),
                quality=dict(obs.quality),
            )
            current.update(self.current_values(now))
        forecasts = {}
        for kind in kinds:
            if (product := self.forecasts.get(kind)) is None:
                forecasts[kind] = {"status": "unavailable"}
                continue
            periods = []
            for period in product.data.periods:
                if period.end <= now:
                    continue
                values = to_ha_forecast(
                    period, kind, is_daytime=self.daylight.get(period.start.isoformat())
                )
                row = {k.removeprefix("native_"): v for k, v in values.items()}
                row["end_datetime"] = period.end.isoformat()
                if kind != "hourly":
                    if "temperature" in row:
                        row["temperature_high"] = row.pop("temperature")
                    if "templow" in row:
                        row["temperature_low"] = row.pop("templow")
                    if "temperature" in period.values:
                        row["mean_temperature"] = period.values["temperature"]
                for key in (
                    "uv_index",
                    "max_apparent_temperature",
                    "min_apparent_temperature",
                ):
                    if key in period.values:
                        row[key] = period.values[key]
                periods.append(row)
                if len(periods) >= count:
                    break
            forecasts[kind] = {
                "source": "forecast",
                "dataset": product.dataset,
                "fetched_at": product.fetched_at.isoformat(),
                "status": ("cached" if kind in self.errors else "fresh")
                if periods
                else "stale",
                "periods": periods,
            }
            if product.issued_at:
                forecasts[kind]["issued_at"] = product.issued_at.isoformat()
        return {
            "location": self.location,
            "timezone": "Asia/Taipei",
            "updated_at": self.updated_at.isoformat(),
            "units": dict(UNITS),
            "current": current,
            "display_condition": self.display_condition(now),
            "forecasts": forecasts,
            "errors": dict(self.errors),
        }

    def display_condition(self, now: datetime) -> dict:
        return display_condition(self, now)
