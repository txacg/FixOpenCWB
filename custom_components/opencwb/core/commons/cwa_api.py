"""Bounded synchronous CWA transport; all callers run it in an executor."""

import ssl
from urllib.parse import urlsplit

import requests

from .cwa_tls import cwa_session

DATASTORE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/"
ARCHIVE = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/F-D0047-093"
DISTRIBUTION = (
    "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Forecast/F-D0047-093.zip"
)


class CwaError(Exception):
    """Public error codes never contain request URLs, keys, or upstream bodies."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _missing_ski(error: BaseException) -> bool:
    """Match the verified OpenSSL error object, not an arbitrary error string."""
    pending, seen = [error], set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if (
            isinstance(value, ssl.SSLCertVerificationError)
            and getattr(value, "verify_code", None) == 86
        ):
            return True
        for child in (
            *getattr(value, "args", ()),
            getattr(value, "reason", None),
            value.__cause__,
            value.__context__,
        ):
            if isinstance(child, BaseException):
                pending.append(child)
    return False


class CwaAPI:
    """Credentials remain private; sessions and responses have bounded lifetimes."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def _request(
        self, url: str, params: dict | None, limit: int, redirects: bool = False
    ):
        try:
            for strict in (True, False):
                try:
                    with cwa_session(strict=strict) as session:
                        with session.get(
                            url,
                            params=params,
                            verify=True,
                            timeout=(10, 30),
                            allow_redirects=False,
                            stream=True,
                        ) as response:
                            status = response.status_code
                            if status in (401, 403):
                                raise CwaError("authorization")
                            if redirects and status in (301, 302, 307, 308):
                                target = urlsplit(response.headers.get("Location", ""))
                                allowed = urlsplit(DISTRIBUTION)
                                if (
                                    target.scheme,
                                    target.hostname,
                                    target.port,
                                    target.path,
                                ) != (
                                    allowed.scheme,
                                    allowed.hostname,
                                    None,
                                    allowed.path,
                                ):
                                    raise CwaError("unexpected_redirect")
                                # Never forward the CWA key/query to the distribution host.
                                return None
                            if status != 200:
                                raise CwaError("http_error")
                            chunks, size = [], 0
                            for chunk in response.iter_content(65536):
                                size += len(chunk)
                                if size > limit:
                                    raise CwaError("response_too_large")
                                chunks.append(chunk)
                            return b"".join(chunks)
                except requests.exceptions.SSLError as error:
                    if (
                        not strict
                        or urlsplit(url).hostname != "opendata.cwa.gov.tw"
                        or not _missing_ski(error)
                    ):
                        raise CwaError("tls") from None
        except requests.exceptions.Timeout:
            raise CwaError("timeout") from None
        except requests.exceptions.RequestException:
            raise CwaError("connection") from None

    def json(self, dataset: str, location: str | None = None) -> dict:
        import json

        params = {"Authorization": self._api_key, "format": "JSON"}
        if location:
            params["LocationName"] = location
        raw = self._request(DATASTORE + dataset, params, 8_000_000)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise TypeError
            return data
        except (ValueError, TypeError):
            raise CwaError("malformed_data") from None

    def daily_archive(self) -> bytes:
        raw = self._request(
            ARCHIVE, {"Authorization": self._api_key, "format": "ZIP"}, 16_000_000, True
        )
        return raw if raw is not None else self._request(DISTRIBUTION, None, 16_000_000)
