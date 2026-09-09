"""Fetch and publish CWA forecasts through Home Assistant's coordinator."""

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import sun
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt

from .const import (
    ATTR_API_CLOUDS,
    ATTR_API_CONDITION,
    ATTR_API_DEW_POINT,
    ATTR_API_FEELS_LIKE_TEMPERATURE,
    ATTR_API_FORECAST,
    ATTR_API_HUMIDITY,
    ATTR_API_PRECIPITATION_KIND,
    ATTR_API_PRESSURE,
    ATTR_API_RAIN,
    ATTR_API_SNOW,
    ATTR_API_TEMPERATURE,
    ATTR_API_UV_INDEX,
    ATTR_API_WEATHER,
    ATTR_API_WEATHER_CODE,
    ATTR_API_WIND_BEARING,
    ATTR_API_WIND_GUST,
    ATTR_API_WIND_SPEED,
    DOMAIN,
)
from .core.commons.exceptions import OCWBError, UnauthorizedError
from .core.utils.cwa_forecast import (
    CwaDataError,
    CwaForecast,
    condition_for_code,
    select_current,
    to_ha_forecast,
)
from .core.utils.cwa_location import forecast_type_for_mode

_LOGGER = logging.getLogger(__name__)
WEATHER_UPDATE_INTERVAL = timedelta(minutes=15)


class WeatherUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keep original mode values/identities while selecting real CWA products."""

    def __init__(
        self,
        ocwb,
        location_name,
        latitude,
        longitude,
        forecast_mode,
        hass,
        config_entry=None,
    ):
        self._ocwb_client = ocwb
        self._location_name = location_name
        self.forecast_mode = forecast_mode
        self.forecast_type = forecast_type_for_mode(forecast_mode)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=WEATHER_UPDATE_INTERVAL,
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            response = await self.hass.async_add_executor_job(
                self._ocwb_client.cwa_forecast, self._location_name, self.forecast_mode
            )
            return self._convert_weather_response(response)
        except UnauthorizedError:
            raise ConfigEntryAuthFailed("CWA authorization failed") from None
        except (OCWBError, CwaDataError, ValueError) as error:
            # Client/parser exceptions carry only sanitized diagnostics.
            raise UpdateFailed(str(error)) from None

    def _convert_weather_response(
        self, response: CwaForecast, now: datetime | None = None
    ) -> dict[str, Any]:
        now = now or dt.utcnow()
        current = select_current(response, now)
        if current is None:
            raise CwaDataError("CWA response has no currently valid forecast")
        values = current.values
        forecasts = [
            to_ha_forecast(
                period,
                response.forecast_type,
                is_daytime=sun.is_up(self.hass, period.start),
            )
            for period in response.periods
            if period.end > now
        ]
        return {
            ATTR_API_TEMPERATURE: values.get("temperature"),
            ATTR_API_FEELS_LIKE_TEMPERATURE: values.get("apparent_temperature"),
            ATTR_API_DEW_POINT: values.get("dew_point"),
            ATTR_API_PRESSURE: None,
            ATTR_API_HUMIDITY: values.get("humidity"),
            ATTR_API_WIND_BEARING: values.get("wind_bearing"),
            ATTR_API_WIND_GUST: None,
            ATTR_API_WIND_SPEED: values.get("wind_speed"),
            ATTR_API_CLOUDS: None,
            ATTR_API_RAIN: None,
            ATTR_API_SNOW: None,
            ATTR_API_PRECIPITATION_KIND: None,
            ATTR_API_WEATHER: values.get("description", values.get("weather")),
            ATTR_API_CONDITION: condition_for_code(
                values.get("weather_code"), sun.is_up(self.hass, now)
            ),
            ATTR_API_UV_INDEX: values.get("uv_index"),
            ATTR_API_WEATHER_CODE: values.get("weather_code"),
            ATTR_API_FORECAST: forecasts,
        }
