"""A host-scoped TLS compatibility policy for CWA's current TWCA chain."""

import os
import ssl
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.utils import DEFAULT_CA_BUNDLE_PATH

CWA_ORIGIN = "https://opendata.cwa.gov.tw/"


class CwaTLSAdapter(HTTPAdapter):
    """Keep verified TLS; relax only strict X.509 checks for the CWA origin."""

    def __init__(self, *, strict: bool = False):
        self._strict = strict
        super().__init__()

    def build_connection_pool_key_attributes(
        self,
        request: requests.PreparedRequest,
        verify: bool | str,
        cert: str | tuple[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        host, pool = super().build_connection_pool_key_attributes(request, verify, cert)
        if (
            host["scheme"] != "https"
            or host["host"] != "opendata.cwa.gov.tw"
            or host["port"] not in (None, 443)
            or not (verify is True or isinstance(verify, str) and verify)
        ):
            raise requests.exceptions.SSLError(
                "Invalid CWA TLS destination or verification policy"
            )

        # Match Requests' normal CA bundle selection, including an explicit or
        # environment-provided bundle/directory. Do not add any custom trust anchor.
        ca_path = verify if isinstance(verify, str) else DEFAULT_CA_BUNDLE_PATH
        try:
            context = ssl.create_default_context(
                cafile=None if os.path.isdir(ca_path) else ca_path,
                capath=ca_path if os.path.isdir(ca_path) else None,
            )
        except OSError:
            raise requests.exceptions.SSLError(
                "Unable to load CWA trust store"
            ) from None
        # Python 3.14 strict X.509 validation rejects the current CWA/TWCA chain
        # for a missing Subject Key Identifier. All other flags, CERT_REQUIRED,
        # hostname checking, and trusted-chain validation stay at their defaults.
        if not self._strict:
            context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        pool["ssl_context"] = context
        return host, pool


def cwa_session(*, strict: bool = False) -> requests.Session:
    """Create a request-scoped session; callers close it with a context manager."""
    session = requests.Session()
    adapter = CwaTLSAdapter(strict=strict)
    session.mount(CWA_ORIGIN, adapter)
    session.mount("https://opendata.cwa.gov.tw:443/", adapter)
    return session
