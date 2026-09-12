"""Optional dashboard presentation, separate from authoritative observations."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .cwa_forecast import to_ha_forecast
from .cwa_observation import Observation, observation_condition

if TYPE_CHECKING:
    from .cwa_model import WeatherSnapshot

CONF_CONDITION_POLICY = "condition_policy"
CONF_CONDITION_MAX_AGE = "condition_max_age_minutes"
CONDITION_POLICIES = (
    "strict_observation",
    "last_valid_observation",
    "forecast_fallback",
)
DEFAULT_CONDITION_POLICY = CONDITION_POLICIES[0]
DEFAULT_CONDITION_MAX_AGE = 30
MAX_CONDITION_AGE = 120


def condition_settings(policy, max_age) -> tuple[str, int]:
    """Invalid stored settings fail closed; never enable fallback implicitly."""
    if policy not in CONDITION_POLICIES:
        policy = DEFAULT_CONDITION_POLICY
    if isinstance(max_age, bool):
        max_age = DEFAULT_CONDITION_MAX_AGE
    try:
        minutes = int(max_age)
    except (TypeError, ValueError, OverflowError):
        minutes = DEFAULT_CONDITION_MAX_AGE
    if not 1 <= minutes <= MAX_CONDITION_AGE:
        minutes = DEFAULT_CONDITION_MAX_AGE
    return policy, minutes


@dataclass(frozen=True)
class ObservedWeather:
    station_id: str
    dataset: str
    observed_at: datetime
    weather: str


class ObservationWeatherHistory:
    """One last valid description per selected station, with a hard age bound."""

    def __init__(self):
        self.records: dict[str, ObservedWeather] = {}

    def prune(self, now: datetime):
        self.records = {
            station: record
            for station, record in self.records.items()
            if timedelta(0)
            <= now - record.observed_at
            <= timedelta(minutes=MAX_CONDITION_AGE)
        }

    def remember(self, observations: tuple[Observation, ...], now: datetime):
        self.prune(now)
        for obs in sorted(observations, key=lambda o: (o.observed_at, o.dataset)):
            weather = obs.values.get("weather")
            if (
                not weather
                or observation_condition(weather) is None
                or not timedelta(0)
                <= now - obs.observed_at
                <= timedelta(minutes=MAX_CONDITION_AGE)
            ):
                continue
            previous = self.records.get(obs.station_id)
            if previous is None or previous.observed_at <= obs.observed_at:
                self.records[obs.station_id] = ObservedWeather(
                    obs.station_id, obs.dataset, obs.observed_at, weather
                )


def display_condition(snapshot: "WeatherSnapshot", now: datetime) -> dict:
    """Return explicit provenance; never write values back into the observation."""
    policy, max_age = condition_settings(
        snapshot.condition_policy, snapshot.condition_max_age_minutes
    )
    result = {"condition": None, "source": "unavailable", "policy": policy}
    obs = snapshot.observation.observation
    if obs is None or not obs.fresh(now):
        return result
    current = snapshot.current_values(now)
    if current.get("condition"):
        return {
            **result,
            "condition": current["condition"],
            "source": "observation",
            "station_id": obs.station_id,
            "dataset": obs.dataset,
            "observed_at": obs.observed_at.isoformat(),
            "age_seconds": max(0, int((now - obs.observed_at).total_seconds())),
        }
    if policy == "last_valid_observation":
        record = snapshot.last_observed_weather
        if record and record.station_id == obs.station_id:
            age = now - record.observed_at
            condition = observation_condition(record.weather, snapshot.daytime)
            if condition and timedelta(0) <= age <= timedelta(minutes=max_age):
                return {
                    **result,
                    "condition": condition,
                    "source": "last_observation",
                    "station_id": record.station_id,
                    "dataset": record.dataset,
                    "observed_at": record.observed_at.isoformat(),
                    "age_seconds": int(age.total_seconds()),
                    "weather": record.weather,
                }
    if policy == "forecast_fallback":
        product = snapshot.forecasts.get("hourly")
        if product:
            for period in product.data.periods:
                if period.start <= now < period.end:
                    condition = to_ha_forecast(
                        period, "hourly", is_daytime=snapshot.daytime
                    ).get("condition")
                    if condition:
                        return {
                            **result,
                            "condition": condition,
                            "source": "forecast_fallback",
                            "forecast_type": "hourly",
                            "dataset": product.dataset,
                            "valid_from": period.start.isoformat(),
                            "valid_until": period.end.isoformat(),
                            "fetched_at": product.fetched_at.isoformat(),
                        }
    return result
