"""Publish one normalized observation/forecast snapshot to every consumer."""

import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt

from .const import DOMAIN
from .core.commons.cwa_api import CwaError
from .core.utils.cwa_forecast import CwaDataError
from .core.utils.cwa_location import forecast_type_for_mode
from .core.utils.cwa_model import WeatherSnapshot

_LOGGER = logging.getLogger(__name__)


class WeatherUpdateCoordinator(DataUpdateCoordinator[WeatherSnapshot]):
    def __init__(
        self, repository, location_name, forecast_mode, hass, config_entry=None
    ):
        self.repository = repository
        self.location_name = location_name
        self.forecast_mode = forecast_mode
        self.forecast_type = forecast_type_for_mode(forecast_mode)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> WeatherSnapshot:
        try:
            return await self.repository.snapshot(self.location_name)
        except CwaError as error:
            if error.code == "authorization":
                raise ConfigEntryAuthFailed("CWA authorization failed") from None
            raise UpdateFailed(error.code) from None
        except CwaDataError:
            raise UpdateFailed("Malformed CWA data") from None

    def forecast(self, kind: str | None = None):
        return self.data.ha_forecast(kind or self.forecast_type, dt.utcnow())

    @property
    def current(self):
        return self.data.current_values(dt.utcnow())
