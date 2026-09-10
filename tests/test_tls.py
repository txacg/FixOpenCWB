"""CWA TLS exceptions must never disable authentication or affect other hosts."""

import ssl
from unittest.mock import patch

import pytest
import requests
from core.commons.cwa_tls import CWA_ORIGIN, CwaTLSAdapter, cwa_session
from requests.adapters import HTTPAdapter
from requests.utils import DEFAULT_CA_BUNDLE_PATH


def pool(adapter, url=CWA_ORIGIN, verify=True):
    request = requests.Request("GET", url).prepare()
    return adapter.build_connection_pool_key_attributes(request, verify)


def test_only_strict_flag_changes_and_trust_is_preserved():
    baseline = ssl.create_default_context(cafile=DEFAULT_CA_BUNDLE_PATH)
    # Python 3.11 local tests must exercise removing STRICT too, not a no-op.
    baseline.verify_flags |= ssl.VERIFY_X509_STRICT
    before = baseline.verify_flags
    properties = (baseline.options, baseline.minimum_version, baseline.maximum_version)
    trusted = baseline.get_ca_certs(binary_form=True)
    with patch(
        "core.commons.cwa_tls.ssl.create_default_context", return_value=baseline
    ) as create:
        _, kwargs = pool(CwaTLSAdapter())
    create.assert_called_once_with(cafile=DEFAULT_CA_BUNDLE_PATH, capath=None)
    context = kwargs["ssl_context"]
    assert context.verify_flags == before & ~ssl.VERIFY_X509_STRICT
    assert before ^ context.verify_flags == ssl.VERIFY_X509_STRICT
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert kwargs["cert_reqs"] == "CERT_REQUIRED"
    assert (
        context.options,
        context.minimum_version,
        context.maximum_version,
    ) == properties
    assert context.get_ca_certs(binary_form=True) == trusted
    assert trusted


def test_contexts_and_default_requests_adapter_are_not_modified():
    factory = ssl.create_default_context
    unrelated = factory()
    before = unrelated.verify_flags
    with cwa_session() as session, requests.Session() as ordinary:
        cwa = session.get_adapter(CWA_ORIGIN)
        assert isinstance(cwa, CwaTLSAdapter)
        _, first = pool(cwa)
        _, second = pool(cwa)
        assert first["ssl_context"] is not second["ssl_context"]
        assert type(ordinary.get_adapter(CWA_ORIGIN)) is HTTPAdapter
    assert ssl.create_default_context is factory
    assert unrelated.verify_flags == before == factory().verify_flags
    assert unrelated.check_hostname and unrelated.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://opendata.cwa.gov.tw/",
        "https://opendata.cwa.gov.tw.evil.example/",
        "https://opendata.cwa.gov.tw@evil.example/",
        "https://opendata.cwa.gov.tw:444/",
        "https://sub.opendata.cwa.gov.tw/",
    ],
)
def test_unrelated_origins_use_default_adapter_and_reject_direct_reuse(url):
    with cwa_session() as session:
        assert type(session.get_adapter(url)) is HTTPAdapter
    with pytest.raises(requests.exceptions.SSLError, match="Invalid CWA TLS"):
        pool(CwaTLSAdapter(), url)


@pytest.mark.parametrize("verify", [False, None, ""])
def test_unverified_connections_are_rejected(verify):
    with pytest.raises(requests.exceptions.SSLError):
        pool(CwaTLSAdapter(), verify=verify)


def test_explicit_port_and_https_proxy_keep_contexts_separate():
    with cwa_session() as session:
        adapter = session.get_adapter("https://opendata.cwa.gov.tw:443/")
        assert isinstance(adapter, CwaTLSAdapter)
        host, kwargs = pool(adapter, "https://opendata.cwa.gov.tw:443/")
        assert host["port"] == 443
        assert kwargs["ssl_context"].check_hostname
        proxy = adapter.proxy_manager_for("https://proxy.example:443")
        assert proxy.proxy_ssl_context is None
        assert "ssl_context" not in proxy.connection_pool_kw


@pytest.mark.parametrize("directory", [False, True])
def test_custom_ca_bundle_selection_is_preserved(tmp_path, directory):
    ca_path = str(tmp_path) if directory else DEFAULT_CA_BUNDLE_PATH
    with patch(
        "core.commons.cwa_tls.ssl.create_default_context",
        wraps=ssl.create_default_context,
    ) as create:
        _, kwargs = pool(CwaTLSAdapter(), verify=ca_path)
    create.assert_called_once_with(
        cafile=None if directory else ca_path,
        capath=ca_path if directory else None,
    )
    assert kwargs["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    assert kwargs["ssl_context"].check_hostname


def test_ca_loading_error_is_sanitized():
    with (
        patch(
            "core.commons.cwa_tls.ssl.create_default_context",
            side_effect=OSError("secret-path"),
        ),
        pytest.raises(requests.exceptions.SSLError) as error,
    ):
        pool(CwaTLSAdapter())
    assert "secret-path" not in str(error.value)
    assert error.value.__suppress_context__
