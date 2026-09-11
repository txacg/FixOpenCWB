import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import voluptuous as vol
from homeassistant.components import llm
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.llm import LLM_API_ASSIST, LLMContext, ToolInput
from homeassistant.setup import async_setup_component
from test_integration import make_entry, setup

from custom_components.opencwb.diagnostics import async_get_config_entry_diagnostics
from custom_components.opencwb.llm import GetCWAWeather, async_get_tools
from custom_components.opencwb.services import async_get_weather

pytestmark = pytest.mark.asyncio


def context(user_id=None, assistant="conversation"):
    return LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="zh-TW",
        assistant=assistant,
        device_id=None,
    )


async def expose(hass, entity_id, enabled=True):
    assert await async_setup_component(hass, "homeassistant", {})
    async_expose_entity(hass, "conversation", entity_id, enabled)
    await hass.async_block_till_done()


async def test_response_action_and_llm_share_same_model(hass):
    entry = make_entry()
    entity = await setup(hass, entry)
    await expose(hass, entity.entity_id)
    action = await hass.services.async_call(
        "opencwb",
        "get_weather",
        {"entity_id": entity.entity_id, "forecast_type": "all", "count": 2},
        blocking=True,
        return_response=True,
    )
    contribution = async_get_tools(hass, context(), LLM_API_ASSIST)
    assert contribution and contribution.tools[0].name == "opencwb__GetCWAWeather"
    tool = await contribution.tools[0].async_call(
        hass,
        ToolInput(
            tool_name=GetCWAWeather.name,
            tool_args={
                "entity_id": entity.entity_id,
                "forecast_type": "all",
                "count": 2,
            },
        ),
        context(),
    )
    assert tool == action
    assert action["current"]["temperature"] == entity.native_temperature == 25.6
    assert action["current"]["source"] == "observation"
    assert action["current"]["station"]["id"] == "C0AH10"
    assert all(len(product["periods"]) == 2 for product in action["forecasts"].values())
    encoded = json.dumps(action, ensure_ascii=False)
    assert len(encoded) < 6000 and "test-key" not in encoded
    assert async_get_tools(hass, context(), "unrelated_api") is None


async def test_real_llm_platform_discovery(hass):
    entity = await setup(hass, make_entry())
    await expose(hass, entity.entity_id)
    assert await async_setup_component(hass, "llm", {})
    tools = await llm.async_get_tools(hass, context(), LLM_API_ASSIST)
    assert any(tool.name == GetCWAWeather.name for tool in tools.tools)


async def test_tool_requires_assistant_exposure_context(hass):
    await setup(hass, make_entry())
    assert async_get_tools(hass, context(assistant=None), LLM_API_ASSIST) is None
    result = await GetCWAWeather().async_call(
        hass,
        ToolInput(tool_name=GetCWAWeather.name, tool_args={}),
        context(assistant=None),
    )
    assert "error" in result and "current" not in result


async def test_unexposed_entity_and_revocation_are_denied(hass):
    entity = await setup(hass, make_entry())
    await expose(hass, entity.entity_id, False)
    assert async_get_tools(hass, context(), LLM_API_ASSIST) is None
    with pytest.raises(HomeAssistantError):
        await async_get_weather(hass, entity.entity_id, assistant="conversation")
    await expose(hass, entity.entity_id)
    tools = async_get_tools(hass, context(), LLM_API_ASSIST)

    async def revoke():
        async_expose_entity(hass, "conversation", entity.entity_id, False)

    with patch.object(entity.coordinator, "async_request_refresh", side_effect=revoke):
        with pytest.raises(HomeAssistantError):
            await tools.tools[0].async_call(
                hass,
                ToolInput(
                    tool_name=GetCWAWeather.name,
                    tool_args={"entity_id": entity.entity_id},
                ),
                context(),
            )


@pytest.mark.parametrize("active,permitted", [(True, False), (False, True)])
async def test_user_permissions_apply_to_tool_and_action(hass, active, permitted):
    entity = await setup(hass, make_entry())
    await expose(hass, entity.entity_id)
    user = SimpleNamespace(
        is_active=active, permissions=Mock(check_entity=Mock(return_value=permitted))
    )
    with patch.object(hass.auth, "async_get_user", new=AsyncMock(return_value=user)):
        with pytest.raises(HomeAssistantError):
            await async_get_weather(
                hass, entity.entity_id, context=Context(user_id="restricted")
            )
        result = await GetCWAWeather().async_call(
            hass,
            ToolInput(tool_name=GetCWAWeather.name, tool_args={}),
            context("restricted"),
        )
        assert "error" in result and "current" not in result


async def test_allowed_user_and_filtered_location_discovery(hass):
    first = await setup(hass, make_entry("daily"))
    second = await setup(hass, make_entry("hourly"))
    await expose(hass, first.entity_id)
    await expose(hass, second.entity_id)
    result = await GetCWAWeather().async_call(
        hass, ToolInput(tool_name=GetCWAWeather.name, tool_args={}), context()
    )
    assert len(result["locations"]) == 2
    user = SimpleNamespace(
        is_active=True,
        permissions=Mock(
            check_entity=Mock(side_effect=lambda eid, policy: eid == first.entity_id)
        ),
    )
    with patch.object(hass.auth, "async_get_user", new=AsyncMock(return_value=user)):
        result = await GetCWAWeather().async_call(
            hass,
            ToolInput(
                tool_name=GetCWAWeather.name, tool_args={"forecast_type": "none"}
            ),
            context("allowed"),
        )
    assert result["current"]["temperature"] == 25.6 and result["forecasts"] == {}


async def test_schema_limits_and_diagnostics_redaction(hass):
    entry = make_entry(key="credential-for-redaction-test")
    await setup(hass, entry)
    for args in ({"count": 0}, {"count": 25}, {"forecast_type": "fake"}):
        with pytest.raises(vol.Invalid):
            GetCWAWeather.parameters(args)
    with pytest.raises(HomeAssistantError):
        await async_get_weather(hass, "weather.unknown")
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diagnostics, ensure_ascii=False)
    assert (
        "credential-for-redaction-test" not in text
        and "api_key" not in text
        and "Authorization" not in text
    )
    assert diagnostics["current"]["station"]["id"] == "C0AH10"
    assert diagnostics["forecast_datasets"]["daily"] == "F-D0047-093"
