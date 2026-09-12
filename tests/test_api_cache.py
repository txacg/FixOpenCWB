import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from core.commons.cwa_api import DISTRIBUTION, CwaAPI, CwaError
from core.utils.cwa_cache import DataCache


def response(status=200, data=b'{"success":true}', headers=None):
    r = MagicMock(status_code=status, headers=headers or {})
    r.__enter__.return_value = r
    r.iter_content.return_value = [data]
    return r


def session(result):
    s = MagicMock()
    s.__enter__.return_value = s
    if isinstance(result, Exception):
        s.get.side_effect = result
    else:
        s.get.return_value = result
    return s


def ski_error(code=86):
    cause = ssl.SSLCertVerificationError("credential-must-not-leak")
    cause.verify_code = code
    return requests.exceptions.SSLError(cause)


def test_strict_first_fallback_only_for_missing_ski():
    first, second = session(ski_error()), session(response())
    with patch(
        "core.commons.cwa_api.cwa_session", side_effect=[first, second]
    ) as factory:
        assert CwaAPI("test-secret").json("O-A0001-001")["success"]
    assert [c.kwargs for c in factory.call_args_list] == [
        {"strict": True},
        {"strict": False},
    ]
    assert second.get.call_args.kwargs["verify"] is True


@pytest.mark.parametrize(
    "failure",
    [
        ski_error(62),
        ski_error(20),
        requests.exceptions.SSLError("Missing Subject Key Identifier"),
    ],
)
def test_other_tls_errors_never_trigger_compatibility(failure):
    with (
        patch(
            "core.commons.cwa_api.cwa_session", return_value=session(failure)
        ) as factory,
        pytest.raises(CwaError, match="tls") as error,
    ):
        CwaAPI("test-secret").json("O-A0001-001")
    assert factory.call_count == 1
    assert "credential" not in str(error.value) and error.value.__suppress_context__


@pytest.mark.parametrize(
    "error,code",
    [
        (requests.Timeout("secret"), "timeout"),
        (requests.ConnectionError("secret"), "connection"),
    ],
)
def test_network_errors_are_sanitized(error, code):
    with patch("core.commons.cwa_api.cwa_session", return_value=session(error)):
        with pytest.raises(CwaError, match=code):
            CwaAPI("secret").json("O-A0001-001")


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authorization"),
        (403, "authorization"),
        (500, "http_error"),
        (302, "http_error"),
    ],
)
def test_http_failures(status, code):
    with (
        patch(
            "core.commons.cwa_api.cwa_session", return_value=session(response(status))
        ),
        pytest.raises(CwaError, match=code),
    ):
        CwaAPI("secret").json("O-A0001-001")


def test_archive_redirect_is_allowlisted_and_never_forwards_key():
    first = session(
        response(
            302, headers={"Location": DISTRIBUTION + "?Authorization=do-not-forward"}
        )
    )
    second = session(response(data=b"zip"))
    with patch("core.commons.cwa_api.cwa_session", side_effect=[first, second]):
        assert CwaAPI("secret").daily_archive() == b"zip"
    assert second.get.call_args.args == (DISTRIBUTION,)
    assert second.get.call_args.kwargs["params"] is None
    with (
        patch(
            "core.commons.cwa_api.cwa_session",
            return_value=session(
                response(302, headers={"Location": "https://evil.example/"})
            ),
        ),
        pytest.raises(CwaError, match="unexpected_redirect"),
    ):
        CwaAPI("secret").daily_archive()


def test_json_and_size_errors():
    for body in (b"not json", b"[]"):
        with (
            patch(
                "core.commons.cwa_api.cwa_session",
                return_value=session(response(data=body)),
            ),
            pytest.raises(CwaError, match="malformed_data"),
        ):
            CwaAPI("secret").json("O-A0001-001")
    with (
        patch(
            "core.commons.cwa_api.cwa_session",
            return_value=session(response(data=b"oversize")),
        ),
        pytest.raises(CwaError, match="response_too_large"),
    ):
        CwaAPI("secret")._request(DISTRIBUTION, None, 2)


@pytest.mark.asyncio
async def test_concurrent_identical_requests_deduplicate():
    cache = DataCache()
    gate = asyncio.Event()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        await gate.wait()
        return {"data": 1}

    tasks = [
        asyncio.create_task(cache.get(("dataset", "town"), fetch, 60))
        for _ in range(10)
    ]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks)
    assert calls == 1 and all(r is results[0] for r in results)
    await cache.close()


@pytest.mark.asyncio
async def test_ttl_key_isolation_and_error_backoff():
    cache = DataCache()
    other = DataCache()
    fetch = AsyncMock(return_value="good")
    with patch("core.utils.cwa_cache.monotonic", return_value=100):
        await cache.get(("d", "a"), fetch, 60)
        await cache.get(("d", "a"), fetch, 60)
        await cache.get(("d", "b"), fetch, 60)
        await other.get(("d", "a"), fetch, 60)  # separate credential namespace
    assert fetch.call_count == 3
    with patch("core.utils.cwa_cache.monotonic", return_value=200):
        fetch.side_effect = CwaError("timeout")
        for _ in range(2):
            with pytest.raises(CwaError):
                await cache.get(("d", "a"), fetch, 60)
        assert cache.entries[("d", "a")].value == "good"
    assert fetch.call_count == 4
    await cache.close()
    await other.close()


@pytest.mark.asyncio
async def test_cancelling_waiter_does_not_cancel_other_entry_and_unload_cancels_tasks():
    cache = DataCache()
    gate = asyncio.Event()

    async def fetch():
        await gate.wait()
        return 1

    a = asyncio.create_task(cache.get(("d",), fetch, 60))
    b = asyncio.create_task(cache.get(("d",), fetch, 60))
    await asyncio.sleep(0)
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    gate.set()
    assert (await b).value == 1
    gate.clear()
    pending = asyncio.create_task(cache.get(("other",), fetch, 60))
    await asyncio.sleep(0)
    await cache.close()
    with pytest.raises(asyncio.CancelledError):
        await pending


@pytest.mark.parametrize(
    "target",
    [
        "https://cwaopendata.s3.ap-northeast-1.amazonaws.com:secret/Forecast/F-D0047-093.zip",
        "https://[invalid/",
    ],
)
def test_malformed_redirect_is_sanitized(target):
    with (
        patch(
            "core.commons.cwa_api.cwa_session",
            return_value=session(response(302, headers={"Location": target})),
        ),
        pytest.raises(CwaError, match="unexpected_redirect") as error,
    ):
        CwaAPI("secret").daily_archive()
    assert "secret" not in str(error.value)
