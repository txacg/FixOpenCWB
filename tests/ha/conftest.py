"""Only the HA suite needs Linux and the supported Home Assistant runtime."""

import pytest

pytest.importorskip(
    "homeassistant",
    reason="HA integration tests require the Linux/Python 3.14 CI environment",
)


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def taipei(hass, freezer):
    hass.config.set_time_zone("Asia/Taipei")
    hass.config.latitude = 25.01
    hass.config.longitude = 121.51
    freezer.move_to("2026-09-10T00:00:00+00:00")
