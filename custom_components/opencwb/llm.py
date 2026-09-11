"""Contribute an exposure-aware CWA weather tool to Home Assistant Assist."""

import voluptuous as vol
from homeassistant.components.llm import LLMTools
from homeassistant.core import callback
from homeassistant.helpers.llm import LLM_API_ASSIST, LLMContext, Tool, ToolInput

from .services import (
    FORECAST_TYPES,
    allowed_entities,
    async_get_weather,
    weather_entities,
)

PROMPT = (
    "Use opencwb__GetCWAWeather for Taiwan CWA current weather and forecasts. "
    "Select an exposed weather entity; omit entity_id to discover accessible locations. "
    "Request only the forecast type and count needed. Current is a station observation, "
    "not a forecast. Respect source, observed_at, period start/end, status and quality. "
    "Times are UTC; interpret local days in Asia/Taipei. Missing or trace values are not zero. "
    "Never describe stale or unavailable data as current."
)


class GetCWAWeather(Tool):
    name = "opencwb__GetCWAWeather"
    description = "Get compact CWA observations and forecasts for an exposed OpenCWA weather entity."
    parameters = vol.Schema(
        {
            vol.Optional("entity_id"): str,
            vol.Optional("forecast_type", default="all"): vol.In(FORECAST_TYPES),
            vol.Optional("count", default=6): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=24)
            ),
        }
    )

    async def async_call(self, hass, tool_input: ToolInput, llm_context: LLMContext):
        if not llm_context.assistant:
            return {"error": "An assistant exposure context is required"}
        args = self.parameters(tool_input.tool_args)
        entities = await allowed_entities(
            hass, llm_context.context, llm_context.assistant
        )
        if not entities:
            return {
                "error": "No accessible CWA weather entity is exposed to this assistant"
            }
        if "entity_id" not in args:
            if len(entities) != 1:
                return {
                    "locations": [
                        {"entity_id": eid, "location": c.data.location}
                        for eid, c in sorted(entities.items())
                    ]
                }
            args["entity_id"] = next(iter(entities))
        return await async_get_weather(
            hass, **args, context=llm_context.context, assistant=llm_context.assistant
        )


@callback
def async_get_tools(hass, llm_context: LLMContext, api_id: str):
    if (
        api_id != LLM_API_ASSIST
        or not llm_context.assistant
        or not weather_entities(hass, llm_context.assistant)
    ):
        return None
    return LLMTools(tools=[GetCWAWeather()], prompt=PROMPT)
