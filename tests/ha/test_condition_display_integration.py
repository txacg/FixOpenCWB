from datetime import timedelta
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.components.weather import DATA_COMPONENT
from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers.llm import ToolInput
from homeassistant.util import dt
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_integration import entries, make_entry, setup
from test_tools import context, expose

from custom_components.opencwb.diagnostics import async_get_config_entry_diagnostics
from custom_components.opencwb.llm import GetCWAWeather

pytestmark = pytest.mark.asyncio


def weather_control(api, raw="-99"):
    state = {"weather": raw}
    original = api["json"].side_effect

    def fetch(dataset, location=None):
        data = original(dataset, location)
        if dataset.startswith("O-"):
            for station in data["records"]["Station"]:
                if station["StationId"] == "C0AH10":
                    station["WeatherElement"]["Weather"] = state["weather"]
        return data

    api["json"].side_effect = fetch
    return state


@pytest.mark.parametrize(
    "policy",
    [
        "strict_observation",
        "last_valid_observation",
        "forecast_fallback",
    ],
)
async def test_display_policy_action_llm_diagnostics_share_provenance(
    hass, api, policy
):
    state = weather_control(api, "多雲")
    entry = make_entry(options={"condition_policy": policy})
    entity = await setup(hass, entry)
    state["weather"] = "-99"
    entity.coordinator.repository.cache.entries.clear()
    await entity.coordinator.async_refresh()
    await expose(hass, entity.entity_id)
    action = await hass.services.async_call(
        "opencwb",
        "get_weather",
        {"entity_id": entity.entity_id, "forecast_type": "none"},
        blocking=True,
        return_response=True,
    )
    tool = await GetCWAWeather().async_call(
        hass,
        ToolInput(
            tool_name=GetCWAWeather.name,
            tool_args={"entity_id": entity.entity_id, "forecast_type": "none"},
        ),
        context(),
    )
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert tool == action
    assert diagnostics["current"] == action["current"]
    assert diagnostics["display_condition"] == action["display_condition"]
    assert action["current"]["source"] == "observation"
    assert action["current"]["condition"] is None
    assert action["current"]["quality"]["weather"] == "missing"
    assert action["current"]["temperature"] == entity.native_temperature == 25.6
    assert entity.condition == action["display_condition"]["condition"]
    assert (
        entity.extra_state_attributes["display_condition"]
        == action["display_condition"]
    )
    expected = {
        "strict_observation": "unavailable",
        "last_valid_observation": "last_observation",
        "forecast_fallback": "forecast_fallback",
    }[policy]
    assert action["display_condition"]["source"] == expected
    if policy == "last_valid_observation":
        assert action["display_condition"]["station_id"] == "C0AH10"
        assert action["display_condition"]["age_seconds"] == 900
    if policy == "forecast_fallback":
        assert action["display_condition"]["forecast_type"] == "hourly"
        assert action["display_condition"]["valid_from"] <= action["updated_at"]


async def test_options_reload_preserves_ids_history_and_effective_defaults(hass, api):
    state = weather_control(api, "多雲")
    entry = make_entry()
    entity = await setup(hass, entry)
    before = {(e.entity_id, e.unique_id) for e in entries(hass, entry)}
    history = entity.coordinator.repository.condition_history
    state["weather"] = "-99"
    entity.coordinator.repository.cache.entries.clear()
    for policy, source in [
        ("forecast_fallback", "forecast_fallback"),
        ("last_valid_observation", "last_observation"),
        ("strict_observation", "unavailable"),
    ]:
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        defaults = flow["data_schema"]({})
        assert defaults["condition_policy"] == entity.coordinator.condition_policy
        assert defaults["condition_max_age_minutes"] == 30
        result = await hass.config_entries.options.async_configure(
            flow["flow_id"],
            {
                "mode": "twice_daily",
                "condition_policy": policy,
                "condition_max_age_minutes": 30,
            },
        )
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        entity = hass.data[DATA_COMPONENT].get_entity(entity.entity_id)
        assert entity.coordinator.repository.condition_history is history
        assert (
            entity.coordinator.data.display_condition(dt.utcnow())["source"] == source
        )
        assert before == {(e.entity_id, e.unique_id) for e in entries(hass, entry)}
    assert "condition_policy" not in entry.data and entry.version == 1


async def test_last_condition_expiry_updates_entity_state_and_unload_cancels_timer(
    hass, api, freezer
):
    state = weather_control(api, "多雲")
    entry = make_entry(options={"condition_policy": "last_valid_observation"})
    entity = await setup(hass, entry)
    state["weather"] = "-99"
    entity.coordinator.repository.cache.entries.clear()
    await entity.coordinator.async_refresh()
    assert entity.condition == "partlycloudy"
    assert entity._display_expiry_unsub is not None
    later = dt.utcnow() + timedelta(minutes=16)
    freezer.move_to(later)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done()
    assert entity.condition is None
    assert hass.states.get(entity.entity_id).state == "unknown"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entity._display_expiry_unsub is None


async def test_per_entry_policy_does_not_modify_shared_repository_snapshot(hass, api):
    weather_control(api)
    strict = await setup(hass, make_entry("daily"))
    fallback = await setup(
        hass, make_entry("hourly", {"condition_policy": "forecast_fallback"})
    )
    assert strict.coordinator.repository is fallback.coordinator.repository
    assert strict.condition is None and fallback.condition is not None
    assert strict.coordinator.current == fallback.coordinator.current
    raw = await strict.coordinator.repository.snapshot("永和區")
    assert raw.condition_policy == "strict_observation"
    other = await setup(hass, make_entry("onecall_daily", key="other-key"))
    assert (
        other.coordinator.repository.condition_history
        is not strict.coordinator.repository.condition_history
    )


async def test_config_flow_policy_fields_and_options_data_fallback(hass):
    flow = await hass.config_entries.flow.async_init(
        "opencwb", context={"source": SOURCE_USER}
    )
    schema = flow["data_schema"]
    defaults = schema({"api_key": "test", "location_name": "永和區"})
    assert defaults["condition_policy"] == "strict_observation"
    assert defaults["condition_max_age_minutes"] == 30
    for bad in [0, 121]:
        with pytest.raises(vol.Invalid):
            schema(
                {
                    "api_key": "test",
                    "location_name": "永和區",
                    "condition_max_age_minutes": bad,
                }
            )
    with patch("custom_components.opencwb.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "api_key": "test",
                "location_name": "永和區",
                "condition_policy": "last_valid_observation",
                "condition_max_age_minutes": 15,
            },
        )
        await hass.async_block_till_done()
    assert result["data"]["condition_policy"] == "last_valid_observation"
    entry = result["result"]
    hass.config_entries.async_update_entry(entry, options={"mode": "hourly"})
    options = await hass.config_entries.options.async_init(entry.entry_id)
    assert options["data_schema"]({})["condition_policy"] == "last_valid_observation"
    assert options["data_schema"]({})["condition_max_age_minutes"] == 15
