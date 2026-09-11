"""Explicitly allowlisted diagnostics; never serialize config or client objects."""

from time import monotonic

from homeassistant.loader import async_get_integration
from homeassistant.util import dt

from .const import DOMAIN, ENTRY_WEATHER_COORDINATOR


async def async_get_config_entry_diagnostics(hass, config_entry):
    runtime = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not runtime:
        return {"status": "not_loaded"}
    coordinator = runtime[ENTRY_WEATHER_COORDINATOR]
    snapshot = coordinator.data
    current = snapshot.structured(dt.utcnow(), (), 1)["current"]
    integration = await async_get_integration(hass, DOMAIN)
    return {
        "version": integration.version,
        "location": snapshot.location,
        "mode": coordinator.forecast_type,
        "current": current,
        "updated_at": snapshot.updated_at.isoformat(),
        "errors": dict(snapshot.errors),
        "forecast_datasets": {
            kind: product.dataset for kind, product in snapshot.forecasts.items()
        },
        "last_successful_forecast_fetch": {
            kind: product.fetched_at.isoformat()
            for kind, product in snapshot.forecasts.items()
        },
        "supported_forecasts": [coordinator.forecast_type]
        + (["daily"] if "daily" in snapshot.forecasts else []),
        "cache": [
            {
                "dataset": key[0],
                "location": key[1] if len(key) > 1 else None,
                "fetched_at": cached.fetched_at.isoformat(),
                "fresh": cached.expires > monotonic(),
            }
            for key, cached in coordinator.repository.cache.entries.items()
        ],
    }
