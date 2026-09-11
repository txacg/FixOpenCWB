"""One permission-checked normalized weather API for automations and LLMs."""

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt

from .const import DOMAIN, ENTRY_WEATHER_COORDINATOR

FORECAST_TYPES = ("all", "none", "hourly", "twice_daily", "daily")
SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("forecast_type", default="all"): vol.In(FORECAST_TYPES),
        vol.Optional("count", default=6): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=24)
        ),
    }
)


@callback
def weather_entities(hass, assistant=None):
    result = {}
    for entry in er.async_get(hass).entities.values():
        if entry.domain != "weather" or entry.platform != DOMAIN or entry.disabled:
            continue
        runtime = hass.data.get(DOMAIN, {}).get(entry.config_entry_id)
        if not runtime or ENTRY_WEATHER_COORDINATOR not in runtime:
            continue
        if assistant is not None and not async_should_expose(
            hass, assistant, entry.entity_id
        ):
            continue
        result[entry.entity_id] = runtime[ENTRY_WEATHER_COORDINATOR]
    return result


async def allowed_entities(hass, context, assistant=None):
    entities = weather_entities(hass, assistant)
    if context is not None and context.user_id is not None:
        user = await hass.auth.async_get_user(context.user_id)
        if user is None or not user.is_active:
            return {}
        entities = {
            entity_id: value
            for entity_id, value in entities.items()
            if user.permissions.check_entity(entity_id, POLICY_READ)
        }
    return entities


async def async_get_weather(
    hass, entity_id, forecast_type="all", count=6, *, context=None, assistant=None
):
    args = SCHEMA(
        {"entity_id": entity_id, "forecast_type": forecast_type, "count": count}
    )
    entities = await allowed_entities(hass, context, assistant)
    if entity_id not in entities:
        raise HomeAssistantError("CWA weather entity unavailable or access denied")
    coordinator = entities[entity_id]
    await coordinator.async_request_refresh()
    # Recheck after awaits so revoked exposure/permissions cannot leak cached data.
    if entity_id not in await allowed_entities(hass, context, assistant):
        raise HomeAssistantError("CWA weather entity unavailable or access denied")
    if not coordinator.last_update_success:
        raise HomeAssistantError("CWA refresh failed; inspect integration status")
    kinds = (
        ("hourly", "twice_daily", "daily")
        if forecast_type == "all"
        else (() if forecast_type == "none" else (forecast_type,))
    )
    return coordinator.data.structured(dt.utcnow(), kinds, args["count"])


@callback
def async_register(hass):
    if hass.services.has_service(DOMAIN, "get_weather"):
        return

    async def handle(call):
        return await async_get_weather(hass, **call.data, context=call.context)

    hass.services.async_register(
        DOMAIN,
        "get_weather",
        handle,
        schema=SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
