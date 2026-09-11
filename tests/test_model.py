from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from core.utils.cwa_daily import parse_daily_xml
from core.utils.cwa_model import ForecastProduct, WeatherSnapshot
from test_observation import NOW, observations, select


def snapshot():
    data, issued = parse_daily_xml(
        (Path(__file__).parent / "fixtures" / "yonghe_daily.xml").read_bytes()
    )["新北市永和區"]
    return WeatherSnapshot(
        "新北市永和區",
        25.01,
        121.51,
        select(observations()),
        {"daily": ForecastProduct(data, "F-D0047-093", NOW, issued)},
        NOW,
    )


def test_structured_current_is_observation_and_stale_never_leaks_values():
    model = snapshot()
    result = model.structured(NOW, ("daily",), 2)
    assert (
        result["current"]["temperature"]
        == model.current_values(NOW)["temperature"]
        == 25.6
    )
    assert result["forecasts"]["daily"]["periods"][0]["temperature_high"] == 32
    later = model.structured(NOW + timedelta(hours=4), ("daily",), 2)
    assert later["current"]["status"] == "stale"
    assert "temperature" not in later["current"]


def test_expired_forecast_remains_stale_even_when_refresh_failed():
    model = replace(snapshot(), errors={"daily": "timeout"})
    assert (
        model.structured(NOW, ("daily",), 2)["forecasts"]["daily"]["status"] == "cached"
    )
    old = model.structured(NOW + timedelta(days=10), ("daily",), 2)
    assert old["forecasts"]["daily"]["status"] == "stale"
    assert old["forecasts"]["daily"]["periods"] == []
