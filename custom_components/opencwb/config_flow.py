"""Config/options flows preserving existing entry and entity identities."""

import urllib.parse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_MODE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import _get_config_value
from .const import (
    CONF_LOCATION_NAME,
    CONFIG_FLOW_VERSION,
    DEFAULT_FORECAST_MODE,
    DEFAULT_NAME,
    DOMAIN,
    FORECAST_MODES,
)
from .core.commons.cwa_api import CwaAPI, CwaError
from .core.utils.cwa_forecast import CwaDataError, parse_forecast
from .core.utils.cwa_location import forecast_type_for_mode, resolve_location

MODE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=FORECAST_MODES, translation_key="forecast_mode"
    )
)


async def _validate(hass, api_key: str, location: str, mode: str) -> str | None:
    try:
        kind = forecast_type_for_mode(mode)
        route = resolve_location(location, kind)
    except ValueError:
        return "invalid_location_name"
    try:
        client = CwaAPI(api_key)
        await hass.async_add_executor_job(
            lambda: parse_forecast(
                client.json(route.dataset, route.name), route.name, kind
            )
        )
    except CwaError as error:
        return {
            "authorization": "invalid_api_key",
            "tls": "tls",
            "timeout": "timeout",
            "malformed_data": "invalid_data",
        }.get(error.code, "cannot_connect")
    except CwaDataError:
        return "invalid_data"
    return None


class OpenCWBConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up CWA or replace an expired API key without replacing the entry."""

    VERSION = CONFIG_FLOW_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OpenCWBOptionsFlow()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            mode = user_input.get(CONF_MODE, DEFAULT_FORECAST_MODE)
            location = user_input[CONF_LOCATION_NAME]
            error = await _validate(self.hass, user_input[CONF_API_KEY], location, mode)
            if error:
                errors["base"] = error
            else:
                # Keep the established identity format, including the original mode.
                await self.async_set_unique_id(
                    urllib.parse.quote_plus(location) + "-" + mode
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data={
                        **user_input,
                        CONF_MODE: mode,
                        CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_LOCATION_NAME): str,
                    vol.Optional(
                        CONF_MODE, default=DEFAULT_FORECAST_MODE
                    ): MODE_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            error = await _validate(
                self.hass,
                user_input[CONF_API_KEY],
                entry.data[CONF_LOCATION_NAME],
                _get_config_value(entry, CONF_MODE, DEFAULT_FORECAST_MODE),
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )


class OpenCWBOptionsFlow(config_entries.OptionsFlow):
    """Show effective settings and retain other previously stored options."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        mode = forecast_type_for_mode(
            _get_config_value(self.config_entry, CONF_MODE, DEFAULT_FORECAST_MODE)
        )
        if user_input is not None:
            mode = user_input.get(CONF_MODE, mode)
            error = await _validate(
                self.hass,
                self.config_entry.data[CONF_API_KEY],
                self.config_entry.data[CONF_LOCATION_NAME],
                mode,
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="",
                    data={**self.config_entry.options, **user_input, CONF_MODE: mode},
                )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Optional(CONF_MODE, default=mode): MODE_SELECTOR}
            ),
            errors=errors,
        )
