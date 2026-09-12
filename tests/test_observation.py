import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from core.utils.cwa_forecast import CwaDataError
from core.utils.cwa_observation import (
    observation_condition,
    parse_observations,
    select_station,
)

NOW = datetime(2026, 9, 11, 11, 15, tzinfo=UTC)


def payload(dataset="O-A0001-001"):
    return json.loads(
        (Path(__file__).parent / "fixtures" / (dataset + ".json")).read_text(
            encoding="utf-8"
        )
    )


def observations():
    return tuple(
        o
        for d in ("O-A0001-001", "O-A0003-001")
        for o in parse_observations(payload(d), d)
    )


def select(rows, now=NOW):
    return select_station(tuple(rows), "新北市", "永和區", 25.010926, 121.511985, now)


def test_real_station_and_coordinates():
    result = select(observations())
    obs = result.observation
    assert obs.station_id == "C0AH10"
    assert obs.latitude == 25.01125  # WGS84, not the first TWD67 coordinates.
    assert obs.values["temperature"] == 25.6
    assert obs.values["precipitation_today"] == 8.5
    assert obs.observed_at == datetime(2026, 9, 11, 11, tzinfo=UTC)
    assert 0.3 < result.distance_km < 0.5
    assert select(reversed(observations())) == result


@pytest.mark.parametrize(
    "marker,status",
    [
        ("T", "trace"),
        ("-98", "dry_last_6h"),
        ("-99", "missing"),
        ("X", "equipment_error"),
    ],
)
def test_precipitation_special_values(marker, status):
    data = payload()
    for station in data["records"]["Station"]:
        station["WeatherElement"]["Now"]["Precipitation"] = marker
    obs = select(parse_observations(data, "O-A0001-001")).observation
    assert "precipitation_today" not in obs.values
    assert obs.quality["precipitation_today"] == status


def test_zero_decimal_variable_wind_and_missing_gust():
    data = payload()
    for station in data["records"]["Station"]:
        station["WeatherElement"].update(
            AirTemperature="0", WindSpeed="0.7", WindDirection="990"
        )
    obs = select(parse_observations(data, "O-A0001-001")).observation
    assert obs.values["temperature"] == 0
    assert obs.values["wind_speed"] == 0.7
    assert "wind_bearing" not in obs.values and "wind_gust" not in obs.values
    assert obs.quality["wind_bearing"] == "variable"


def test_missing_field_does_not_blend_stations():
    rows = observations()
    rows = [
        replace(o, values={k: v for k, v in o.values.items() if k != "humidity"})
        if o.station_id == "C0AH10"
        else o
        for o in rows
    ]
    selected = select(rows).observation
    assert selected.station_id == "C0AH10"
    assert "humidity" not in selected.values


def test_missing_core_value_or_stale_local_station_falls_back():
    rows = observations()
    modified = [replace(o, values={}) if o.station_id == "C0AH10" else o for o in rows]
    assert select(modified).observation.station_id != "C0AH10"
    modified = [
        replace(o, observed_at=NOW - timedelta(hours=4))
        if o.station_id == "C0AH10"
        else o
        for o in rows
    ]
    assert select(modified).observation.station_id != "C0AH10"
    assert select(rows, NOW + timedelta(hours=3)).status == "stale"
    assert select([]).status == "unavailable"


def test_deduplicate_station_by_freshness_not_api_order():
    rows = [o for o in observations() if o.station_id == "466920"]
    assert select(rows).observation.dataset == "O-A0003-001"
    assert select(rows).observation.values["visibility_description"] == "11-15"
    assert "visibility" not in select(rows).observation.values
    assert select(rows).observation.values["wind_gust"] == 8.2


@pytest.mark.parametrize(
    "text,expected",
    [
        ("晴", "sunny"),
        ("多雲有雨", "rainy"),
        ("陰有霧", "fog"),
        ("多雲有雷雨", "lightning-rainy"),
        ("陰有雷聲", "lightning"),
        ("陰有雨雪", "snowy-rainy"),
        ("陰有雹", "hail"),
        ("未知", None),
    ],
)
def test_conditions(text, expected):
    assert observation_condition(text) == expected
    assert observation_condition("晴", False) == "clear-night"


def test_malformed_station_is_skipped_but_bad_dataset_fails():
    data = payload()
    data["records"]["Station"].insert(0, {"StationId": "bad"})
    assert (
        select(parse_observations(data, "O-A0001-001")).observation.station_id
        == "C0AH10"
    )
    for value in (
        {},
        {"success": False},
        {"success": True, "records": {"Station": []}},
    ):
        with pytest.raises(CwaDataError):
            parse_observations(value, "O-A0001-001")


def test_future_data_and_far_away_stations_rejected():
    rows = [replace(o, observed_at=NOW + timedelta(hours=1)) for o in observations()]
    assert select(rows).observation is None
    assert (
        select_station(observations(), "澎湖縣", "馬公市", 23.5, 119.5, NOW).observation
        is None
    )


def test_fresh_stations_with_no_usable_values_are_not_labeled_stale():
    assert (
        select([replace(o, values={}) for o in observations()]).status
        == "missing_values"
    )


def test_missing_station_identity_is_rejected():
    data = payload()
    for station in data["records"]["Station"]:
        station["StationId"] = None
    with pytest.raises(CwaDataError):
        parse_observations(data, "O-A0001-001")
