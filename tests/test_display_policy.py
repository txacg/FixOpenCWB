from dataclasses import replace
from datetime import timedelta

import pytest
from core.utils.cwa_display import (
    ObservationWeatherHistory,
    ObservedWeather,
    condition_settings,
)
from core.utils.cwa_forecast import CwaForecast, ForecastPeriod
from core.utils.cwa_model import ForecastProduct
from core.utils.cwa_observation import StationSelection
from test_model import snapshot
from test_observation import NOW, select
from test_observation_weather import parse_weather


def model(policy="strict_observation", raw="-99", age=30):
    obs = parse_weather(raw)
    period = ForecastPeriod(
        NOW - timedelta(minutes=10), NOW + timedelta(minutes=20), {"weather_code": 8}
    )
    product = ForecastProduct(
        CwaForecast("永和區", 25.01, 121.51, "hourly", (period,)), "F-D0047-069", NOW
    )
    return replace(
        snapshot(),
        observation=select([obs]),
        forecasts={"hourly": product},
        condition_policy=policy,
        condition_max_age_minutes=age,
        last_observed_weather=ObservedWeather(
            obs.station_id, obs.dataset, NOW - timedelta(minutes=20), "多雲"
        ),
    )


@pytest.mark.parametrize(
    "policy,condition,source",
    [
        ("strict_observation", None, "unavailable"),
        ("last_valid_observation", "partlycloudy", "last_observation"),
        ("forecast_fallback", "rainy", "forecast_fallback"),
    ],
)
@pytest.mark.parametrize("raw", ["-99", "特殊天氣描述"])
def test_policies_never_change_authoritative_observation(
    policy, condition, source, raw
):
    value = model(policy, raw)
    current_before = dict(value.observation.observation.values)
    result = value.structured(NOW, (), 1)
    assert (
        result["current"]
        == model("strict_observation", raw).structured(NOW, (), 1)["current"]
    )
    assert result["current"]["source"] == "observation"
    assert result["current"]["condition"] is None
    assert result["current"]["temperature"] == 25.6
    assert result["display_condition"]["condition"] == condition
    assert result["display_condition"]["source"] == source
    assert value.observation.observation.values == current_before
    if raw == "-99":
        assert result["current"]["quality"]["weather"] == "missing"
    else:
        assert result["current"]["weather"] == raw
        assert result["current"]["quality"]["condition"] == "unmapped"


@pytest.mark.parametrize(
    "policy", ["strict_observation", "last_valid_observation", "forecast_fallback"]
)
def test_real_condition_always_wins(policy):
    result = model(policy, "晴").display_condition(NOW)
    assert result["source"] == "observation" and result["condition"] == "sunny"


def test_history_provenance_and_configurable_age():
    value = model("last_valid_observation")
    shown = value.display_condition(NOW)
    assert shown["station_id"] == "C0AH10"
    assert shown["age_seconds"] == 1200
    assert shown["observed_at"] == (NOW - timedelta(minutes=20)).isoformat()
    assert (
        model("last_valid_observation", age=10).display_condition(NOW)["condition"]
        is None
    )
    assert (
        value.display_condition(NOW + timedelta(minutes=10))["condition"]
        == "partlycloudy"
    )
    assert (
        value.display_condition(NOW + timedelta(minutes=10, microseconds=1))[
            "condition"
        ]
        is None
    )


def test_history_rejects_other_station_future_and_unmapped_records():
    value = model("last_valid_observation")
    for record in (
        replace(value.last_observed_weather, station_id="466920"),
        replace(value.last_observed_weather, observed_at=NOW + timedelta(seconds=1)),
        replace(value.last_observed_weather, weather="特殊天氣描述"),
    ):
        assert (
            replace(value, last_observed_weather=record).display_condition(NOW)[
                "condition"
            ]
            is None
        )


def test_forecast_provenance_requires_interval_containing_now():
    value = model("forecast_fallback")
    shown = value.display_condition(NOW)
    assert shown["forecast_type"] == "hourly" and shown["dataset"] == "F-D0047-069"
    assert shown["valid_from"] == (NOW - timedelta(minutes=10)).isoformat()
    assert shown["valid_until"] == (NOW + timedelta(minutes=20)).isoformat()
    assert value.display_condition(NOW - timedelta(minutes=11))["condition"] is None
    assert value.display_condition(NOW + timedelta(minutes=20))["condition"] is None
    assert replace(value, forecasts={}).display_condition(NOW)["condition"] is None
    product = value.forecasts["hourly"]
    unknown = replace(
        product,
        data=replace(
            product.data,
            periods=(replace(product.data.periods[0], values={"weather_code": 999}),),
        ),
    )
    assert (
        replace(value, forecasts={"hourly": unknown}).display_condition(NOW)[
            "condition"
        ]
        is None
    )


@pytest.mark.parametrize("policy", ["last_valid_observation", "forecast_fallback"])
def test_fallback_requires_a_fresh_selected_observation(policy):
    value = model(policy)
    assert (
        replace(
            value, observation=StationSelection(None, None, "unavailable")
        ).display_condition(NOW)["condition"]
        is None
    )
    assert value.display_condition(NOW + timedelta(hours=3))["condition"] is None


def test_history_is_bounded_does_not_extend_age_or_replace_with_missing():
    history = ObservationWeatherHistory()
    valid = parse_weather("晴")
    history.remember((valid,), NOW)
    record = history.records[valid.station_id]
    history.remember(
        (parse_weather("-99"), parse_weather("特殊天氣描述")),
        NOW + timedelta(minutes=10),
    )
    assert history.records[valid.station_id] is record
    history.remember((valid,), NOW + timedelta(minutes=20))
    assert history.records[valid.station_id].observed_at == valid.observed_at
    older = replace(
        valid,
        observed_at=valid.observed_at - timedelta(minutes=1),
        values={"weather": "陰"},
    )
    history.remember((older,), NOW)
    assert history.records[valid.station_id].weather == "晴"
    history.prune(NOW + timedelta(hours=3))
    assert history.records == {}
    future = replace(valid, observed_at=NOW + timedelta(minutes=1))
    history.remember((future,), NOW)
    assert history.records == {}
    assert ObservationWeatherHistory().records == {}


@pytest.mark.parametrize("bad", [None, -1, 0, 121, "bad", float("inf"), True])
def test_invalid_stored_policy_settings_fail_safe(bad):
    assert condition_settings("invalid", bad) == ("strict_observation", 30)
