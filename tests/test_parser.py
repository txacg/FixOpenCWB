"""CWA field and time semantics, independent of Home Assistant."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from core.utils.cwa_forecast import (
    CwaDataError,
    condition_for_code,
    parse_forecast,
    parse_timestamp,
    select_current,
    to_ha_forecast,
)

FIXTURES = Path(__file__).parent / "fixtures"


def payload(kind="twice_daily"):
    return json.loads((FIXTURES / f"yonghe_{kind}.json").read_text(encoding="utf-8"))


def elements(data):
    return data["records"]["Locations"][0]["Location"][0]["WeatherElement"]


def element(data, name):
    return next(item for item in elements(data) if item["ElementName"] == name)


def parse(data, kind="twice_daily"):
    return parse_forecast(data, "永和區", kind)


@pytest.mark.parametrize(
    "stamp",
    ["2026-09-10T18:00:00+08:00", "2026-09-10T10:00:00Z", "2026-09-10 18:00:00"],
)
def test_aware_timestamp(stamp):
    assert parse_timestamp(stamp) == datetime(2026, 9, 10, 10, tzinfo=UTC)


@pytest.mark.parametrize("stamp", [None, "", "invalid", "2026-09-10", 123])
def test_invalid_time_never_becomes_now(stamp):
    with pytest.raises(CwaDataError):
        parse_timestamp(stamp)


def test_twice_daily_preserves_all_periods_and_midnight():
    data = payload()
    result = parse(data)
    assert len(result.periods) == len(element(data, "天氣現象")["Time"]) == 15
    first = result.periods[0]
    assert first.start == datetime(2026, 9, 9, 10, tzinfo=UTC)
    assert first.end == datetime(2026, 9, 9, 22, tzinfo=UTC)
    night, day = [to_ha_forecast(row, "twice_daily") for row in result.periods[:2]]
    assert night["is_daytime"] is False
    assert day["is_daytime"] is True
    assert night["datetime"] == "2026-09-09T10:00:00+00:00"
    assert night["native_temperature"] == 27
    assert night["native_templow"] == 23


def test_hourly_joins_by_time_instead_of_position():
    data = payload("hourly")
    result = parse(data, "hourly")
    temperatures = element(data, "溫度")["Time"]
    assert len(result.periods) == len(temperatures) == 56
    for row in result.periods:
        source = next(
            item
            for item in temperatures
            if parse_timestamp(item["DataTime"]) == row.start
        )
        assert row.values["temperature"] == float(
            source["ElementValue"][0]["Temperature"]
        )
    # A three-hour point wind value must not be carried into intervening hours.
    assert "wind_speed" not in result.periods[1].values
    # Three-hour probability is not an hourly probability.
    assert "precipitation_probability" not in to_ha_forecast(
        result.periods[0], "hourly"
    )


def test_element_and_object_order_does_not_matter():
    data = payload()
    expected = parse(data)
    elements(data).reverse()
    for item in elements(data):
        item["Time"].reverse()
        for row in item["Time"]:
            row["ElementValue"] = [
                dict(reversed(list(value.items()))) for value in row["ElementValue"]
            ]
    assert parse(data) == expected


def test_uv_uses_its_own_shorter_time_axis():
    result = parse(payload())
    assert result.periods[0].values.get("uv_index") is None
    assert "uv_index" in result.periods[7].values
    assert "uv_index" in result.periods[13].values


def test_decimal_wind_and_beaufort_are_distinct():
    data = payload()
    element(data, "風速")["Time"][0]["ElementValue"] = [
        {"BeaufortScale": "2", "WindSpeed": "1.5"}
    ]
    row = parse(data).periods[0]
    assert row.values["wind_speed"] == 1.5
    assert row.values["beaufort_scale"] == 2
    assert to_ha_forecast(row, "twice_daily")["native_wind_speed"] == 1.5
    assert "native_wind_gust_speed" not in to_ha_forecast(row, "twice_daily")


@pytest.mark.parametrize("missing", ["-", "", None, "-99", ">= 11", "1-2", "NaN"])
def test_unusable_numeric_values_are_missing(missing):
    data = payload()
    element(data, "風速")["Time"][0]["ElementValue"][0]["WindSpeed"] = missing
    assert "native_wind_speed" not in to_ha_forecast(
        parse(data).periods[0], "twice_daily"
    )


def test_missing_pop_and_precipitation_are_not_zero():
    result = parse(payload())
    output = to_ha_forecast(result.periods[-1], "twice_daily")
    assert "precipitation_probability" not in output
    assert "native_precipitation" not in output
    assert "native_pressure" not in output
    assert "cloud_coverage" not in output


def test_zero_minimum_and_probability_survive():
    data = payload()
    element(data, "最低溫度")["Time"][0]["ElementValue"][0]["MinTemperature"] = "0"
    element(data, "12小時降雨機率")["Time"][0]["ElementValue"][0][
        "ProbabilityOfPrecipitation"
    ] = "0"
    output = to_ha_forecast(parse(data).periods[0], "twice_daily")
    assert output["native_templow"] == 0
    assert output["native_temperature"] == 27
    assert output["precipitation_probability"] == 0


@pytest.mark.parametrize("value", [[], None, [{}]])
def test_empty_optional_element_value(value):
    data = payload()
    element(data, "平均相對濕度")["Time"][0]["ElementValue"] = value
    assert "humidity" not in to_ha_forecast(parse(data).periods[0], "twice_daily")


@pytest.mark.parametrize(
    "code,condition",
    [
        (1, "sunny"),
        (2, "partlycloudy"),
        (3, "partlycloudy"),
        (7, "cloudy"),
        (8, "rainy"),
        (15, "lightning-rainy"),
        (21, "lightning-rainy"),
        (33, "lightning-rainy"),
        (42, "snowy"),
        (99, None),
        (None, None),
    ],
)
def test_conditions(code, condition):
    assert condition_for_code(code, True) == condition
    assert condition_for_code(1, False) == "clear-night"


def test_unknown_weather_code_is_not_an_error():
    data = payload()
    element(data, "天氣現象")["Time"][0]["ElementValue"][0]["WeatherCode"] = "99"
    assert "condition" not in to_ha_forecast(parse(data).periods[0], "twice_daily")


@pytest.mark.parametrize("empty", [[], [{}], [{"Weather": "未知天氣"}]])
def test_missing_weather_value_preserves_interval(empty):
    data = payload()
    element(data, "天氣現象")["Time"][0]["ElementValue"] = empty
    result = parse(data)
    assert len(result.periods) == 15
    assert "condition" not in to_ha_forecast(result.periods[0], "twice_daily")


def test_current_uses_valid_interval_without_removing_forecasts():
    result = parse(payload())
    before = deepcopy(result.periods)
    boundary = datetime(2026, 9, 9, 22, tzinfo=UTC)
    assert select_current(result, boundary) == result.periods[1]
    assert result.periods == before
    assert select_current(result, result.periods[-1].end + timedelta(seconds=1)) is None
    assert (
        select_current(result, result.periods[0].start - timedelta(seconds=1)) is None
    )


@pytest.mark.parametrize("success", [False, "false", None])
def test_api_failure_flag(success):
    data = payload()
    data["success"] = success
    with pytest.raises(CwaDataError):
        parse(data)


def test_wrong_location_and_invalid_interval_fail_safely():
    data = payload()
    with pytest.raises(CwaDataError):
        parse_forecast(data, "板橋區", "twice_daily")
    element(data, "天氣現象")["Time"][0]["EndTime"] = "bad-time"
    with pytest.raises(CwaDataError):
        parse(data)


def test_daily_is_not_fabricated():
    with pytest.raises(CwaDataError):
        parse_forecast(payload(), "永和區", "daily")


def test_live_shortened_day_period():
    data = json.loads(
        (FIXTURES / "yonghe_twice_daily_partial.json").read_text(encoding="utf-8")
    )
    result = parse(data)
    day, night = [to_ha_forecast(p, "twice_daily") for p in result.periods]
    assert day["datetime"] == "2026-09-10T04:00:00+00:00"
    assert day["is_daytime"] is True
    assert night["is_daytime"] is False
    assert result.periods[0].end - result.periods[0].start == timedelta(hours=6)
    assert (
        select_current(result, datetime(2026, 9, 10, 6, tzinfo=UTC))
        == result.periods[0]
    )
    assert day["native_temperature"] == float(
        element(data, "最高溫度")["Time"][0]["ElementValue"][0]["MaxTemperature"]
    )


@pytest.mark.parametrize(
    "start", ["2026-09-10T00:00:00+08:00", "2026-09-09T21:00:00+08:00"]
)
def test_shortened_night_remains_night(start):
    data = payload()
    element(data, "天氣現象")["Time"][0]["StartTime"] = start
    first = parse(data).periods[0]
    assert to_ha_forecast(first, "twice_daily")["is_daytime"] is False


def test_twice_daily_rejects_crossing_day_night_boundary():
    data = payload()
    element(data, "天氣現象")["Time"][0]["EndTime"] = "2026-09-10T09:00:00+08:00"
    with pytest.raises(CwaDataError, match="day/night boundary"):
        parse(data)
