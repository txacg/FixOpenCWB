"""Observation Weather semantics, based on CWA schema appendix 2 and live data."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from core.utils.cwa_model import WeatherSnapshot
from core.utils.cwa_observation import observation_condition, parse_observations
from test_observation import NOW, observations, payload, select


# Appendix 2: cloud cover + phenomenon, including frozen precipitation + thunder.
@pytest.mark.parametrize("cloud", ["晴", "多雲", "陰"])
@pytest.mark.parametrize(
    "suffix,expected",
    [
        ("有霾", "fog"),
        ("有靄", "fog"),
        ("有霧", "fog"),
        ("有閃電", "lightning"),
        ("有雷聲", "lightning"),
        ("有雷", "lightning"),
        ("有雨", "rainy"),
        ("有陣雨", "rainy"),
        ("有雨雪", "snowy-rainy"),
        ("陣雨雪", "snowy-rainy"),
        ("有大雪", "snowy"),
        ("有雪珠", "snowy"),
        ("有雷雪", "snowy"),
        ("有冰珠", "hail"),
        ("有雹", "hail"),
        ("有雷雹", "hail"),
        ("大雷雹", "hail"),
        ("有雷雨", "lightning-rainy"),
        ("大雷雨", "lightning-rainy"),
    ],
)
def test_documented_compounds(cloud, suffix, expected):
    assert observation_condition(cloud + suffix) == expected


@pytest.mark.parametrize(
    "raw,day,night",
    [
        ("晴", "sunny", "clear-night"),
        ("多雲", "partlycloudy", "partlycloudy"),
        ("陰", "cloudy", "cloudy"),
        (" 晴 \u3000有閃電 ", "lightning", "lightning"),
    ],
)
def test_simple_descriptions_and_formatting(raw, day, night):
    assert observation_condition(raw) == day
    assert observation_condition(raw, False) == night


def parse_weather(raw):
    data = payload()
    data["records"]["Station"] = [
        next(s for s in data["records"]["Station"] if s["StationId"] == "C0AH10")
    ]
    data["records"]["Station"][0]["WeatherElement"]["Weather"] = raw
    return parse_observations(data, "O-A0001-001")[0]


@pytest.mark.parametrize("raw", ["特殊天氣描述", "晴但沒有雨", "陰有雨及未知現象"])
def test_unknown_valid_raw_survives_without_substring_guessing(raw):
    obs = parse_weather(raw)
    assert obs.values["weather"] == raw
    assert obs.quality["condition"] == "unmapped"
    model = WeatherSnapshot("新北市永和區", 25.01, 121.51, select([obs]), {}, NOW)
    current = model.structured(NOW, (), 1)["current"]
    assert current["weather"] == raw and "condition" not in current
    assert current["source"] == "observation"
    assert current["station"]["id"] == "C0AH10"
    assert current["observed_at"] == obs.observed_at.isoformat()


@pytest.mark.parametrize(
    "raw,status",
    [
        (None, "missing"),
        ("", "missing"),
        (" ", "missing"),
        ("-", "missing"),
        ("--", "missing"),
        ("-99", "missing"),
        ("-99.00", "missing"),
        (-99, "missing"),
        ("-98", "missing"),
        ("X", "equipment_error"),
        ("T", "invalid"),
        (True, "invalid"),
        ("0", "invalid"),
        ({}, "invalid"),
    ],
)
def test_missing_and_special_weather_do_not_remove_measurements(raw, status):
    obs = parse_weather(raw)
    assert "weather" not in obs.values
    assert obs.quality["weather"] == status
    model = WeatherSnapshot("新北市永和區", 25.01, 121.51, select([obs]), {}, NOW)
    current = model.structured(NOW, (), 1)["current"]
    assert current["temperature"] == 25.6
    assert "weather" not in current and "condition" not in current
    # Rainfall accumulated earlier today is not evidence of current rain.
    assert current["precipitation_today"] == 8.5


def test_exact_live_yonghe_missing_weather():
    data = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "yonghe_observation_weather_missing.json"
        ).read_text(encoding="utf-8")
    )
    (obs,) = parse_observations(data, "O-A0001-001")
    assert obs.station_id == "C0AH10"
    assert obs.observed_at == datetime(2026, 9, 12, 10, tzinfo=UTC)
    assert obs.values["temperature"] == 27.6
    assert obs.quality["weather"] == "missing"
    assert "weather" not in obs.values


def test_weather_tie_break_is_independent_of_mapper_and_keeps_one_station():
    base = parse_weather("-99")
    first = replace(base, station_id="AAA")
    second = replace(
        base,
        station_id="BBB",
        values={**base.values, "weather": "特殊天氣描述", "temperature": 12.3},
    )
    chosen = select([first, second]).observation
    assert chosen == second
    assert select([second, first]).observation == second
    # A more distant station must not displace the local measurements for an icon.
    distant = replace(second, longitude=second.longitude + 0.01)
    assert select([first, distant]).observation == first


def test_same_station_same_time_prefers_weather_but_never_an_older_report():
    base = parse_weather("-99")
    complete = replace(
        base, dataset="O-A0003-001", values={**base.values, "weather": "多雲有靄"}
    )
    assert select([base, complete]).observation == complete
    newer = replace(base, observed_at=NOW)
    assert select([newer, complete]).observation == newer


def test_yonghe_without_weather_does_not_blend_taipei_weather():
    rows = [
        parse_weather("-99"),
        *[o for o in observations() if o.station_id == "466920"],
    ]
    selected = select(rows)
    assert selected.observation.station_id == "C0AH10"
    assert "weather" not in selected.observation.values
