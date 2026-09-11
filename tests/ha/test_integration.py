"""Exercise real HA entities, services, subscriptions, options and stable IDs."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch
from urllib.parse import quote_plus

import pytest
from homeassistant.components.weather import DATA_COMPONENT, WeatherEntityFeature
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.opencwb import _get_config_value
from custom_components.opencwb.core.commons.cwa_api import CwaError
from custom_components.opencwb.repository import forecast_ttl
from custom_components.opencwb.weather_update_coordinator import (
    WeatherUpdateCoordinator,
)

pytestmark = pytest.mark.asyncio


def make_entry(mode="onecall_daily", options=None, key="test-key"):
    return MockConfigEntry(
        domain="opencwb",
        version=1,
        unique_id=quote_plus("永和區") + "-" + mode,
        data={
            "api_key": key,
            "location_name": "永和區",
            "name": "OpenCWA",
            "mode": mode,
        },
        options=options or {},
    )


def entries(hass, entry):
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


async def setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registered = next(e for e in entries(hass, entry) if e.domain == "weather")
    return hass.data[DATA_COMPONENT].get_entity(registered.entity_id)


async def test_observed_current_daily_service_and_subscription(hass, api):
    entry = make_entry()
    entity = await setup(hass, entry)
    assert entity.native_temperature == 25.6
    assert entity.native_pressure == 1011.8
    assert entity.extra_state_attributes["observation"]["station"]["id"] == "C0AH10"
    assert (
        entity.supported_features
        == WeatherEntityFeature.FORECAST_TWICE_DAILY
        | WeatherEntityFeature.FORECAST_DAILY
    )
    result = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": entity.entity_id, "type": "twice_daily"},
        blocking=True,
        return_response=True,
    )
    rows = result[entity.entity_id]["forecast"]
    assert rows[0]["is_daytime"] is False and rows[1]["is_daytime"] is True
    assert "temperature" in rows[0] and "native_temperature" not in rows[0]
    assert all("precipitation" not in row for row in rows)
    daily = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": entity.entity_id, "type": "daily"},
        blocking=True,
        return_response=True,
    )
    assert daily[entity.entity_id]["forecast"][0]["temperature"] == 32
    updates = []
    unsubscribe = entity.async_subscribe_forecast("twice_daily", updates.append)
    try:
        api["high"] = 35
        with patch(
            "custom_components.opencwb.core.utils.cwa_cache.monotonic",
            return_value=1e12,
        ):
            await entity.coordinator.async_request_refresh()
            await hass.async_block_till_done()
        assert updates[-1][0]["temperature"] == 35
        assert entity.native_temperature == 25.6
    finally:
        unsubscribe()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service("opencwb", "get_weather")


async def test_existing_entry_reload_preserves_every_entity_id(hass):
    entry = make_entry("daily")
    entity = await setup(hass, entry)
    before = {(e.entity_id, e.unique_id) for e in entries(hass, entry)}
    original = deepcopy(dict(entry.data))
    uid = entry.unique_id
    hass.config_entries.async_update_entry(entry, options={"mode": "hourly"})
    await hass.async_block_till_done()
    current = hass.data[DATA_COMPONENT].get_entity(entity.entity_id)
    assert current.supported_features & WeatherEntityFeature.FORECAST_HOURLY
    assert before == {(e.entity_id, e.unique_id) for e in entries(hass, entry)}
    assert (
        entry.unique_id == uid and dict(entry.data) == original and entry.version == 1
    )
    assert current.native_temperature == 25.6
    rows = await current.async_forecast_hourly()
    assert "is_daytime" not in rows[0] and "native_temperature" in rows[0]


@pytest.mark.parametrize(
    "legacy,modern",
    [
        ("daily", "twice_daily"),
        ("onecall_daily", "twice_daily"),
        ("hourly", "hourly"),
        ("onecall_hourly", "hourly"),
    ],
)
async def test_two_choice_options_and_aliases(hass, api, legacy, modern):
    entry = make_entry(legacy, {"language": "en"})
    entry.add_to_hass(hass)
    assert _get_config_value(entry, "mode", "twice_daily") == legacy
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({})["mode"] == modern
    selector = next(iter(result["data_schema"].schema.values()))
    assert selector.config["options"] == ["hourly", "twice_daily"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"mode": "twice_daily"}
    )
    assert result["data"] == {"language": "en", "mode": "twice_daily"}
    assert entry.unique_id == quote_plus("永和區") + "-" + legacy
    assert api["json"].call_args.args[0] == "F-D0047-071"


async def test_new_config_validates_selected_mode(hass, api):
    with patch("custom_components.opencwb.async_setup_entry", return_value=True):
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
    assert api["json"].call_args.args == ("F-D0047-069", "永和區")


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
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "replacement-test-key"}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert dict(entry.data) == {**original, "api_key": "replacement-test-key"}
    assert entry.unique_id == quote_plus("永和區") + "-onecall_daily"


@pytest.mark.parametrize(
    "code,expected",
    [
        ("authorization", ConfigEntryAuthFailed),
        ("timeout", UpdateFailed),
        ("tls", UpdateFailed),
    ],
)
async def test_coordinator_error_classification(hass, code, expected):
    repository = AsyncMock()
    repository.snapshot.side_effect = CwaError(code)
    coordinator = WeatherUpdateCoordinator(repository, "永和區", "daily", hass)
    with pytest.raises(expected):
        await coordinator._async_update_data()


async def test_three_entries_share_requests_and_current_across_modes(hass, api):
    configs = [make_entry(mode) for mode in ("hourly", "daily", "onecall_daily")]
    entities = await asyncio.gather(*(setup(hass, e) for e in configs))
    assert {e.native_temperature for e in entities} == {25.6}
    assert len({id(e.coordinator.repository) for e in entities}) == 1
    assert api["json"].call_count == 4 and api["daily"].call_count == 1
    for e in configs[:2]:
        assert await hass.config_entries.async_unload(e.entry_id)
    assert hass.services.has_service("opencwb", "get_weather")
    assert entities[2].native_temperature == 25.6
    assert await hass.config_entries.async_unload(configs[2].entry_id)
    assert not hass.data["opencwb"]["repositories"]


async def test_observation_failure_does_not_become_forecast_current(hass, api, freezer):
    entity = await setup(hass, make_entry())
    api["failures"] = {
        "O-A0001-001": CwaError("timeout"),
        "O-A0003-001": CwaError("tls"),
    }
    freezer.move_to("2026-09-11T15:15:00+00:00")
    with patch(
        "custom_components.opencwb.core.utils.cwa_cache.monotonic", return_value=1e12
    ):
        await entity.coordinator.async_request_refresh()
    assert entity.native_temperature is None
    assert entity.coordinator.forecast("twice_daily")
    structured = entity.coordinator.data.structured(
        __import__("homeassistant.util.dt", fromlist=["utcnow"]).utcnow(),
        ("twice_daily",),
        2,
    )
    assert (
        structured["current"]["source"] == "observation"
        and "temperature" not in structured["current"]
    )
    assert structured["errors"]["O-A0001-001"] == "timeout"


async def test_api_keys_have_separate_caches(hass, api):
    first = await setup(hass, make_entry("daily", key="key-a"))
    second = await setup(hass, make_entry("hourly", key="key-b"))
    assert first.coordinator.repository is not second.coordinator.repository
    assert api["json"].call_count == 8


async def test_forecast_release_cache_ttl(hass):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    before = datetime(2026, 9, 11, 11, 35, tzinfo=ZoneInfo("Asia/Taipei"))
    assert forecast_ttl("hourly", before) == 300
    after = before.replace(minute=45)
    assert forecast_ttl("hourly", after) == 3600
    assert forecast_ttl("twice_daily", after) == 10800


async def test_release_detaches_closing_cache_before_another_setup(hass):
    from custom_components.opencwb import _release

    entity = await setup(hass, make_entry())
    pool = hass.data["opencwb"]["repositories"]
    key, shared = next(iter(pool.items()))
    replacement = {"repository": object(), "users": 1}

    async def close():
        assert key not in pool
        pool[key] = replacement

    with patch.object(entity.coordinator.repository.cache, "close", side_effect=close):
        await _release(hass, key)
    assert pool[key] is replacement
    pool[key] = shared  # restore real entry ownership for fixture cleanup
    shared["users"] = 1


async def test_platform_setup_failure_releases_repository(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    with (
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=RuntimeError("platform setup failed"),
        ),
        patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.entry_id not in hass.data["opencwb"]
    assert not hass.data["opencwb"]["repositories"]


async def test_invalid_stored_location_is_classified(hass):
    from custom_components.opencwb.repository import CwaRepository

    repository = CwaRepository(hass, "test-key")
    with pytest.raises(CwaError, match="invalid_location"):
        await repository.snapshot("invalid-town")
