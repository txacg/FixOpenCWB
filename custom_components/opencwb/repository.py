"""Share source responses across entries using the same credential."""

import asyncio
from datetime import datetime, timedelta

from homeassistant.helpers import sun
from homeassistant.util import dt

from .core.commons.cwa_api import CwaAPI, CwaError
from .core.utils.cwa_cache import DataCache
from .core.utils.cwa_daily import parse_daily_archive
from .core.utils.cwa_forecast import TAIPEI, CwaDataError, parse_forecast
from .core.utils.cwa_location import resolve_location
from .core.utils.cwa_model import ForecastProduct, WeatherSnapshot
from .core.utils.cwa_observation import (
    StationSelection,
    parse_observations,
    select_station,
)


def forecast_ttl(kind: str, now: datetime) -> float:
    """Check shortly after scheduled releases, with bounded interim updates."""
    local = now.astimezone(TAIPEI)
    releases = [
        local.replace(hour=h, minute=40, second=0, microsecond=0) + timedelta(days=d)
        for d in (0, 1)
        for h in (5, 11, 17, 23)
    ]
    next_release = min(t for t in releases if t > local)
    return min(
        3600 if kind == "hourly" else 10800, (next_release - local).total_seconds()
    )


class CwaRepository:
    def __init__(self, hass, api_key: str):
        self.hass = hass
        self.api = CwaAPI(api_key)
        self.cache = DataCache()

    async def forecast(self, location: str, kind: str):
        route = resolve_location(location, kind)

        async def fetch():
            def parse():
                return parse_forecast(
                    self.api.json(route.dataset, route.name), route.name, kind
                )

            return await self.hass.async_add_executor_job(parse)

        return await self.cache.get(
            (route.dataset, route.name), fetch, forecast_ttl(kind, dt.utcnow())
        )

    async def observations(self, dataset: str):
        async def fetch():
            return await self.hass.async_add_executor_job(
                lambda: parse_observations(self.api.json(dataset), dataset)
            )

        return await self.cache.get((dataset,), fetch, 600)

    async def daily(self):
        async def fetch():
            return await self.hass.async_add_executor_job(
                lambda: parse_daily_archive(self.api.daily_archive())
            )

        return await self.cache.get(
            ("F-D0047-093",), fetch, forecast_ttl("daily", dt.utcnow())
        )

    async def snapshot(self, location: str) -> WeatherSnapshot:
        # Both modes use the same canonical representative coordinates and data.
        try:
            route = resolve_location(location, "hourly")
        except ValueError:
            raise CwaError("invalid_location") from None
        canonical = (
            route.name if route.name == route.county else route.county + route.name
        )
        sources = ["hourly", "twice_daily", "daily", "O-A0001-001", "O-A0003-001"]
        results = await asyncio.gather(
            self.forecast(location, "hourly"),
            self.forecast(location, "twice_daily"),
            self.daily(),
            self.observations(sources[3]),
            self.observations(sources[4]),
            return_exceptions=True,
        )
        products, errors, observations = {}, {}, []
        for source, result in zip(sources, results, strict=True):
            if isinstance(result, Exception):
                if isinstance(result, CwaError) and result.code == "authorization":
                    raise result
                if not isinstance(result, (CwaError, CwaDataError)):
                    raise result
                errors[source] = (
                    result.code if isinstance(result, CwaError) else "malformed_data"
                )
                key = (
                    (source,)
                    if source.startswith("O-")
                    else (
                        ("F-D0047-093",)
                        if source == "daily"
                        else (resolve_location(location, source).dataset, route.name)
                    )
                )
                result = self.cache.entries.get(key)
                if result is None:
                    continue
            if source.startswith("O-"):
                observations.extend(result.value)
            elif source == "daily":
                if canonical in result.value:
                    data, issued = result.value[canonical]
                    products[source] = ForecastProduct(
                        data, "F-D0047-093", result.fetched_at, issued
                    )
                else:
                    errors[source] = "location_unavailable"
            else:
                products[source] = ForecastProduct(
                    result.value,
                    resolve_location(location, source).dataset,
                    result.fetched_at,
                )
        # Coordinates always come from the short-term product, independently of UI mode.
        representative = products.get("hourly")
        lat = representative.data.latitude if representative else None
        lon = representative.data.longitude if representative else None
        now = dt.utcnow()
        selection = (
            select_station(tuple(observations), route.county, route.name, lat, lon, now)
            if lat is not None and lon is not None
            else StationSelection(None, None, "missing_coordinates")
        )
        daylight = {
            period.start.isoformat(): sun.is_up(self.hass, period.start)
            for product in products.values()
            for period in product.data.periods
        }
        return WeatherSnapshot(
            canonical,
            lat,
            lon,
            selection,
            products,
            now,
            errors,
            sun.is_up(self.hass, now),
            daylight,
        )
