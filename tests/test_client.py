"""Dataset routing and sanitized transport errors."""

from unittest.mock import Mock

import pytest
import requests
from core.commons import exceptions
from core.commons.http_client import HttpClient
from core.utils.config import get_default_config
from core.utils.cwa_location import forecast_type_for_mode, resolve_location
from core.weatherapi12.weather_manager import WeatherManager
from test_parser import payload


@pytest.mark.parametrize(
    "name,hourly,weekly,filtered",
    [
        ("永和區", "069", "071", "永和區"),
        ("新北市永和區", "069", "071", "永和區"),
        ("台北市中正區", "061", "063", "中正區"),
        ("宜蘭市", "001", "003", "宜蘭市"),
        ("臺北市", "089", "091", "臺北市"),
        ("新竹市", "089", "091", "新竹市"),
    ],
)
def test_routing(name, hourly, weekly, filtered):
    for kind, suffix in (("hourly", hourly), ("twice_daily", weekly)):
        route = resolve_location(name, kind)
        assert route.dataset == "F-D0047-" + suffix
        assert route.name == filtered


@pytest.mark.parametrize("name", ["中正區", "", "不存在", None, "臺北市永和區"])
def test_unknown_or_ambiguous_location(name):
    with pytest.raises(ValueError):
        resolve_location(name, "twice_daily")


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("daily", "twice_daily"),
        ("onecall_daily", "twice_daily"),
        ("hourly", "hourly"),
        ("onecall_hourly", "hourly"),
    ],
)
def test_existing_modes(mode, expected):
    assert forecast_type_for_mode(mode) == expected


@pytest.fixture
def client():
    return HttpClient(
        "test-key-not-a-credential",
        get_default_config(),
        "opendata.cwa.gov.tw/api/v1/rest/datastore",
        False,
    )


def test_request_is_encoded_once_and_tls_verified(client, monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = payload()
    get = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    client.get_json("F-D0047-071", {"LocationName": "永和區"})
    args, kwargs = get.call_args
    assert "?" not in args[0]
    assert kwargs["params"] == {
        "LocationName": "永和區",
        "Authorization": "test-key-not-a-credential",
        "format": "JSON",
    }
    assert kwargs["verify"] is True
    assert kwargs["timeout"] > 0
    assert kwargs["allow_redirects"] is False
    response.close.assert_called_once()


@pytest.mark.parametrize(
    "error,expected",
    [
        (requests.Timeout, exceptions.TimeoutError),
        (requests.ConnectionError, exceptions.APIRequestError),
        (requests.exceptions.SSLError, exceptions.InvalidSSLCertificateError),
    ],
)
def test_network_errors_do_not_expose_url(client, monkeypatch, error, expected):
    monkeypatch.setattr(
        requests, "get", Mock(side_effect=error("Authorization=secret-value"))
    )
    with pytest.raises(expected) as result:
        client.get_json("F-D0047-071")
    assert "secret-value" not in str(result.value)
    assert result.value.__suppress_context__


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, exceptions.UnauthorizedError),
        (403, exceptions.UnauthorizedError),
        (404, exceptions.NotFoundError),
        (429, exceptions.APIRequestError),
        (500, exceptions.APIRequestError),
        (302, exceptions.APIRequestError),
    ],
)
def test_http_errors(client, monkeypatch, status, expected):
    response = Mock(status_code=status, text="secret-value")
    monkeypatch.setattr(requests, "get", Mock(return_value=response))
    with pytest.raises(expected) as result:
        client.get_json("F-D0047-071")
    assert "secret-value" not in str(result.value)
    response.close.assert_called_once()


@pytest.mark.parametrize("bad", [ValueError("body-secret"), [], None])
def test_malformed_json(client, monkeypatch, bad):
    response = Mock(status_code=200)
    if isinstance(bad, Exception):
        response.json.side_effect = bad
    else:
        response.json.return_value = bad
    monkeypatch.setattr(requests, "get", Mock(return_value=response))
    with pytest.raises(exceptions.ParseAPIResponseError):
        client.get_json("F-D0047-071")
    response.close.assert_called_once()


def test_manager_uses_one_request(monkeypatch):
    manager = WeatherManager("test-key", get_default_config())
    get = Mock(return_value=(200, payload()))
    monkeypatch.setattr(manager.http_client, "get_json", get)
    result = manager.cwa_forecast("新北市永和區", "daily")
    assert result.forecast_type == "twice_daily"
    get.assert_called_once_with("F-D0047-071", params={"LocationName": "永和區"})
