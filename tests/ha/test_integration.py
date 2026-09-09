"""Exercise actual HA services, subscriptions, flows and stable entity IDs."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote_plus

import pytest
from homeassistant.components.weather import DATA_COMPONENT, WeatherEntityFeature
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.opencwb import _get_config_value
from custom_components.opencwb.core.commons.exceptions import (
    TimeoutError,
    UnauthorizedError,
)
from custom_components.opencwb.core.utils.cwa_forecast import (
    CwaDataError,
    parse_forecast,
)
from custom_components.opencwb.weather_update_coordinator import (
    WeatherUpdateCoordinator,
)

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).parents[1] / "fixtures"
CLIENT = "custom_components.opencwb.core.weatherapi12.weather_manager.WeatherManager.cwa_forecast"


def forecast(kind="twice_daily", high=None):
    data = json.loads((FIXTURES / f"yonghe_{kind}.json").read_text(encoding="utf-8"))
    if high is not None:
        for element in data["records"]["Locations"][0]["Location"][0]["WeatherElement"]:
            if element["ElementName"] == "最高溫度":
                for row in element["Time"]:
                    row["ElementValue"][0]["MaxTemperature"] = str(high)
    return parse_forecast(data, "永和區", kind)


def make_entry(mode="onecall_daily", options=None):
    return MockConfigEntry(
        domain="opencwb",
        version=1,
        unique_id=quote_plus("永和區") + "-" + mode,
        data={
            "api_key": "test-key",
            "location_name": "永和區",
            "name": "OpenCWA",
            "mode": mode,
        },
        options=options or {},
    )


def entries(hass, entry):
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


async def setup(hass, entry, response=None):
    entry.add_to_hass(hass)
    with patch(CLIENT, return_value=response or forecast()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry_entry = next(e for e in entries(hass, entry) if e.domain == "weather")
    return hass.data[DATA_COMPONENT].get_entity(registry_entry.entity_id)


async def test_twice_daily_service_and_subscription(hass):
    entry = make_entry()
    entity = await setup(hass, entry)
    assert entity.supported_features == WeatherEntityFeature.FORECAST_TWICE_DAILY
    result = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": entity.entity_id, "type": "twice_daily"},
        blocking=True,
        return_response=True,
    )
    rows = result[entity.entity_id]["forecast"]
    assert rows[0]["is_daytime"] is True
    assert rows[1]["is_daytime"] is False
    assert all("precipitation" not in row for row in rows)
    assert all(
        "native_temperature" not in row for row in rows
    )  # HA converted the native contract.
    assert "temperature" in rows[0]
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "weather",
            "get_forecasts",
            {"entity_id": entity.entity_id, "type": "daily"},
            blocking=True,
            return_response=True,
        )
    updates = []
    unsubscribe = entity.async_subscribe_forecast("twice_daily", updates.append)
    try:
        with patch(CLIENT, return_value=forecast(high=35)):
            await entity.coordinator.async_request_refresh()
            await hass.async_block_till_done()
        assert updates and updates[-1][0]["temperature"] == 35
    finally:
        unsubscribe()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_existing_entry_reload_preserves_every_entity_id(hass):
    entry = make_entry("daily")
    entity = await setup(hass, entry)
    before = {(e.entity_id, e.unique_id) for e in entries(hass, entry)}
    original_data = deepcopy(dict(entry.data))
    uid = entry.unique_id
    with patch(CLIENT, return_value=forecast("hourly")):
        hass.config_entries.async_update_entry(entry, options={"mode": "hourly"})
        await hass.async_block_till_done()
    current = hass.data[DATA_COMPONENT].get_entity(entity.entity_id)
    assert current.supported_features == WeatherEntityFeature.FORECAST_HOURLY
    assert before == {(e.entity_id, e.unique_id) for e in entries(hass, entry)}
    assert (
        entry.unique_id == uid
        and dict(entry.data) == original_data
        and entry.version == 1
    )
    rows = await current.async_forecast_hourly()
    assert "is_daytime" not in rows[0]
    assert "native_temperature" in rows[0]


async def test_options_defaults_and_partial_fallback(hass):
    entry = make_entry("hourly", {"language": "en"})
    entry.add_to_hass(hass)
    assert _get_config_value(entry, "mode", "onecall_daily") == "hourly"
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({})["mode"] == "hourly"
    with patch(CLIENT, return_value=forecast()) as request:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"mode": "onecall_daily"}
        )
    assert result["type"] == "create_entry"
    assert result["data"] == {"language": "en", "mode": "onecall_daily"}
    request.assert_called_once_with("永和區", "onecall_daily")


async def test_new_config_validates_selected_mode(hass):
    with (
        patch(CLIENT, return_value=forecast("hourly")) as request,
        patch("custom_components.opencwb.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            "opencwb",
            context={"source": SOURCE_USER},
            data={
                "api_key": "test-key",
                "location_name": "新北市永和區",
                "mode": "hourly",
                "name": "CWA",
            },
        )
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    request.assert_called_once_with("新北市永和區", "hourly")


async def test_reauth_only_replaces_key(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    original = dict(entry.data)
    result = await hass.config_entries.flow.async_init(
        "opencwb",
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    with (
        patch(CLIENT, return_value=forecast()),
        patch.object(hass.config_entries, "async_reload", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "replacement-test-key"}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert dict(entry.data) == {**original, "api_key": "replacement-test-key"}
    assert entry.unique_id == quote_plus("永和區") + "-onecall_daily"


@pytest.mark.parametrize(
    "error,expected",
    [
        (UnauthorizedError("safe"), ConfigEntryAuthFailed),
        (TimeoutError("safe"), UpdateFailed),
        (CwaDataError("safe"), UpdateFailed),
    ],
)
async def test_coordinator_error_classification(hass, error, expected):
    client = Mock()
    client.cwa_forecast.side_effect = error
    coordinator = WeatherUpdateCoordinator(
        client, "永和區", 25.01, 121.51, "daily", hass
    )
    with pytest.raises(expected):
        await coordinator._async_update_data()


async def test_expired_data_not_used_as_current(hass):
    from datetime import UTC, datetime

    coordinator = WeatherUpdateCoordinator(
        Mock(), "永和區", 25.01, 121.51, "daily", hass
    )
    with pytest.raises(CwaDataError):
        coordinator._convert_weather_response(
            forecast(), datetime(2030, 1, 1, tzinfo=UTC)
        )
