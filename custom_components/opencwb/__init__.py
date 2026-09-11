"""OpenCWA integration; historical domain and entity identities are retained."""

from hashlib import sha256

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_MODE, CONF_NAME
from homeassistant.core import HomeAssistant

from .const import (
    CONF_LOCATION_NAME,
    DEFAULT_FORECAST_MODE,
    DOMAIN,
    ENTRY_NAME,
    ENTRY_WEATHER_COORDINATOR,
    PLATFORMS,
)
from .repository import CwaRepository
from .weather_update_coordinator import WeatherUpdateCoordinator


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    domain = hass.data.setdefault(DOMAIN, {})
    pool = domain.setdefault("repositories", {})
    key = sha256(config_entry.data[CONF_API_KEY].encode()).digest()
    if key not in pool:
        pool[key] = {
            "repository": CwaRepository(hass, config_entry.data[CONF_API_KEY]),
            "users": 0,
        }
    shared = pool[key]
    shared["users"] += 1
    coordinator = WeatherUpdateCoordinator(
        shared["repository"],
        config_entry.data[CONF_LOCATION_NAME],
        _get_config_value(config_entry, CONF_MODE, DEFAULT_FORECAST_MODE),
        hass,
        config_entry,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # Release ownership when HA retries setup; do not suppress setup failures.
        await _release(hass, key)
        raise
    domain[config_entry.entry_id] = {
        ENTRY_NAME: config_entry.data[CONF_NAME],
        ENTRY_WEATHER_COORDINATOR: coordinator,
        CONF_LOCATION_NAME: config_entry.data[CONF_LOCATION_NAME],
        "repository_key": key,
    }
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    config_entry.async_on_unload(config_entry.add_update_listener(async_update_options))
    from .services import async_register

    async_register(hass)
    return True


async def _release(hass, key):
    pool = hass.data[DOMAIN]["repositories"]
    shared = pool[key]
    shared["users"] -= 1
    if shared["users"] == 0:
        await shared["repository"].cache.close()
        pool.pop(key)


async def async_update_options(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    runtime = hass.data[DOMAIN].pop(entry.entry_id)
    await _release(hass, runtime["repository_key"])
    if not hass.data[DOMAIN]["repositories"]:
        hass.services.async_remove(DOMAIN, "get_weather")
    return True


def _get_config_value(config_entry, key, default):
    return config_entry.options.get(key, config_entry.data.get(key, default))
