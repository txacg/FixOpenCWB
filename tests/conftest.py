"""Unit tests also run without HA; full integration tests use HA 2026.9.1."""

from importlib.util import find_spec

pytest_plugins = (
    ["pytest_homeassistant_custom_component"]
    if find_spec("pytest_homeassistant_custom_component")
    else []
)
