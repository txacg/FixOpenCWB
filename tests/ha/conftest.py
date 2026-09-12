"""Actual HA 2026.9.1 tests with only the CWA network boundary replaced."""

import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest

pytest.importorskip(
    "homeassistant", reason="HA integration tests require Linux/Python 3.14"
)
FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
async def taipei(hass, freezer):
    await hass.config.async_set_time_zone("Asia/Taipei")
    hass.config.latitude = 25.01
    hass.config.longitude = 121.51
    freezer.move_to("2026-09-11T11:15:00+00:00")


@pytest.fixture(autouse=True)
def api():
    state = {"high": None, "failures": {}}

    def fetch(dataset, location=None):
        if dataset in state["failures"]:
            raise state["failures"][dataset]
        name = (
            dataset
            if dataset.startswith("O-")
            else ("yonghe_hourly" if dataset.endswith("069") else "yonghe_twice_daily")
        )
        data = json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))
        if state["high"] is not None and name == "yonghe_twice_daily":
            for e in data["records"]["Locations"][0]["Location"][0]["WeatherElement"]:
                if e["ElementName"] == "最高溫度":
                    for t in e["Time"]:
                        t["ElementValue"][0]["MaxTemperature"] = str(state["high"])
        return deepcopy(data)

    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "65_Week24_CH.xml", (FIXTURES / "yonghe_daily.xml").read_bytes()
        )
    with (
        patch(
            "custom_components.opencwb.core.commons.cwa_api.CwaAPI.json",
            side_effect=fetch,
        ) as json_mock,
        patch(
            "custom_components.opencwb.core.commons.cwa_api.CwaAPI.daily_archive",
            return_value=buffer.getvalue(),
        ) as daily_mock,
    ):
        state.update(json=json_mock, daily=daily_mock)
        yield state
