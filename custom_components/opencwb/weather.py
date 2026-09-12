"""Support for the OpenCWB (OCWB) service."""

from datetime import timedelta

from homeassistant.components.weather import (
    Forecast,
    SingleCoordinatorWeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt

from .const import (
    ATTRIBUTION,
    CONF_LOCATION_NAME,
    DEFAULT_NAME,
    DOMAIN,
    ENTRY_NAME,
    ENTRY_WEATHER_COORDINATOR,
    MANUFACTURER,
)
from .weather_update_coordinator import WeatherUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up OpenCWB weather entity based on a config entry."""
    domain_data = hass.data[DOMAIN][config_entry.entry_id]
    name = domain_data[ENTRY_NAME]
    weather_coordinator = domain_data[ENTRY_WEATHER_COORDINATOR]
    location_name = domain_data[CONF_LOCATION_NAME]

    unique_id = f"{config_entry.unique_id}"
    ocwb_weather = OpenCWBWeather(
        f"{name} {location_name}", f"{unique_id}-{location_name}", weather_coordinator
    )

    async_add_entities([ocwb_weather], False)


class OpenCWBWeather(SingleCoordinatorWeatherEntity[WeatherUpdateCoordinator]):
    """Implementation of an OpenCWB sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_precipitation_unit = UnitOfLength.MILLIMETERS
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND

    def __init__(
        self,
        name,
        unique_id,
        weather_coordinator: WeatherUpdateCoordinator,
    ):
        """Initialize the sensor."""
        super().__init__(weather_coordinator)
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._weather_coordinator = weather_coordinator
        self._display_expiry_unsub = None
        split_unique_id = unique_id.split("-")
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{split_unique_id[0]}-{split_unique_id[1]}")},
            manufacturer=MANUFACTURER,
            name=DEFAULT_NAME,
        )
        if weather_coordinator.forecast_type in ("twice_daily",):
            self._attr_supported_features = WeatherEntityFeature.FORECAST_TWICE_DAILY
        else:  # FORECAST_MODE_DAILY or FORECAST_MODE_ONECALL_HOURLY
            self._attr_supported_features = WeatherEntityFeature.FORECAST_HOURLY

    @property
    def should_poll(self):
        """Return the polling requirement of the entity."""
        return False

    @property
    def condition(self):
        """Return the current condition."""
        return self._weather_coordinator.data.display_condition(dt.utcnow())[
            "condition"
        ]

    @property
    def available(self):
        """Return True if entity is available."""
        return self._weather_coordinator.last_update_success and (
            bool(self._weather_coordinator.current)
            or any(
                self._weather_coordinator.forecast(kind)
                for kind in self._weather_coordinator.data.forecasts
            )
        )

    async def async_added_to_hass(self):
        """Register the base listener that updates state AND forecast subscribers."""
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_display_expiry)
        self.async_on_remove(
            self.coordinator.async_add_listener(self._schedule_display_expiry)
        )
        self._schedule_display_expiry()

    @callback
    def _cancel_display_expiry(self):
        if self._display_expiry_unsub:
            self._display_expiry_unsub()
            self._display_expiry_unsub = None

    @callback
    def _schedule_display_expiry(self):
        self._cancel_display_expiry()
        now = dt.utcnow()
        display = self.coordinator.data.display_condition(now)
        deadline = None
        if display["source"] == "last_observation":
            deadline = dt.parse_datetime(display["observed_at"]) + timedelta(
                minutes=self.coordinator.condition_max_age_minutes, microseconds=1
            )
        elif display["source"] == "forecast_fallback":
            deadline = dt.parse_datetime(display["valid_until"])
        if deadline is not None and deadline > now:

            @callback
            def expire(_now):
                self._display_expiry_unsub = None
                self.async_write_ha_state()
                self._schedule_display_expiry()

            self._display_expiry_unsub = async_track_point_in_utc_time(
                self.hass, expire, deadline
            )

    @property
    def cloud_coverage(self) -> float | None:
        """Return the Cloud coverage in %."""
        return self._weather_coordinator.current.get("clouds")

    @property
    def native_apparent_temperature(self) -> float | None:
        """Return the apparent temperature."""
        return self._weather_coordinator.current.get("apparent_temperature")

    @property
    def native_temperature(self) -> float | None:
        """Return the temperature."""
        return self._weather_coordinator.current.get("temperature")

    @property
    def native_pressure(self) -> float | None:
        """Return the pressure."""
        return self._weather_coordinator.current.get("pressure")

    @property
    def humidity(self) -> float | None:
        """Return the humidity."""
        return self._weather_coordinator.current.get("humidity")

    @property
    def native_dew_point(self) -> float | None:
        """Return the dew point."""
        return self._weather_coordinator.current.get("dew_point")

    @property
    def native_wind_gust_speed(self) -> float | None:
        """Return the wind gust speed."""
        return self._weather_coordinator.current.get("wind_gust")

    @property
    def native_wind_speed(self) -> float | None:
        """Return the wind speed."""
        return self._weather_coordinator.current.get("wind_speed")

    @property
    def wind_bearing(self) -> float | str | None:
        """Return the wind bearing."""
        return self._weather_coordinator.current.get("wind_bearing")

    @callback
    def _async_forecast_twice_daily(self) -> list[Forecast] | None:
        """Return CWA's 12-hour day/night intervals in native units."""
        return self._weather_coordinator.forecast("twice_daily")

    @callback
    def _async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast in native units."""
        return self._weather_coordinator.forecast("hourly")

    @property
    def supported_features(self):
        features = self._attr_supported_features
        if "daily" in self._weather_coordinator.data.forecasts:
            features |= WeatherEntityFeature.FORECAST_DAILY
        return features

    @property
    def extra_state_attributes(self):
        data = self._weather_coordinator.data.structured(dt.utcnow(), (), 1)
        return {
            "observation": data["current"],
            "display_condition": data["display_condition"],
            "data_errors": data["errors"],
        }

    @callback
    def _async_forecast_daily(self) -> list[Forecast] | None:
        return self._weather_coordinator.forecast("daily")
