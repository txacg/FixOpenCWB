# Upgrade and forecast behavior in 1.4.0

For the 1.4.1 current-condition follow-up, see the
[live Weather investigation and regression notes](observation-weather.md).

Target runtime: Home Assistant 2026.9.1 (Python 3.14.2 or later).

## Existing installations

Keep the existing config entry. Stored mode values, config-entry unique IDs,
weather/sensor unique IDs, and device identifiers are unchanged. No schema
migration or removal/recreation of entities is needed.

The historical `daily` and `onecall_daily` settings now expose **twice_daily**.
Edit an existing weather card's forecast type accordingly:

```yaml
type: weather-forecast
entity: weather.your_existing_entity
forecast_type: twice_daily
```

`hourly` and `onecall_hourly` expose **hourly**. Stored aliases are retained to preserve existing identities. The options selector
shows only hourly and day/night. Both entry types additionally expose true daily
when the official Week24 product has loaded. Saving options may normalize the
mode option; it never rewrites the entry unique ID.

CWA may shorten the first day/night period (for example, 12:00–18:00).
Its actual start time is preserved and it remains a daytime forecast. Night
periods beginning after midnight remain nighttime forecasts through 06:00.

Short-term temperature point times determine the forecast timeline. Other point
values are included only at the same timestamp; interval values must cover that
forecast period. No wind values are interpolated. A three-hour probability is
not exported as a one-hour probability; it is included only where the forecast
has the same three-hour boundaries. Missing values remain unavailable.

Current weather now uses real O-A0001/O-A0003 observations, never forecast rows.
All modes use identical station selection. Missing/stale observations do not
fall back to predictions. Existing sensors for unsourced observation fields
(dew point, apparent temperature, numeric weather code) remain registered and
show unknown. See [architecture](architecture.md) for station and cache rules.

## CWA products

For 新北市永和區, the authenticated JSON endpoints verified on 2026-09-10 are
F-D0047-069 (short-term) and F-D0047-071 (12-hour day/night). County-level queries
use F-D0047-089 and F-D0047-091. Township products have explicit county/dataset
mappings. No latitude/longitude or language parameters are sent to this API.

True daily is now implemented directly from the official F-D0047-093 archive's
*_Week24_CH.xml files, including 65_Week24_CH.xml for New Taipei. The real
midnight-to-midnight values are used, including 24-hour probability and high/low
temperatures. No 12-hour rows are combined. A live archive check on 2026-09-11
parsed 390 canonical town/county locations. ZIP/XML limits and shared caching
are implemented; failure of this product can leave daily unavailable separately.
Use forecast_type: daily on a card to show this product.

Sources:
- https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-D0047-001_093.pdf
- https://opendata.cwa.gov.tw/apidoc/v1
- https://opendata.cwa.gov.tw/webapi/datasetMetadata/F-D0047-093
- https://developers.home-assistant.io/docs/core/entity/weather/
- https://www.cwa.gov.tw/Data/js/WeatherIcon.js

## Validation

### CWA TLS compatibility

Real Home Assistant 2026.9.1 testing (Python 3.14, OpenSSL 3.5.7,
Requests 2.34.2) identified strict X.509 validation as the TLS blocker:
`Missing Subject Key Identifier`. Removing only `VERIFY_X509_STRICT` changed
the default flags from 557088 to 557056 and allowed the HTTPS handshake.

On 2026-09-11, direct inspection with SNI `opendata.cwa.gov.tw` found:

| Certificate | Subject Key Identifier |
| --- | --- |
| Served leaf: `opendata.cwa.gov.tw` | Present |
| Served intermediate: `TWCA Secure SSL Certification Authority` | Present |
| Trusted root: `TWCA Global Root CA`, serial `0CBE` | **Absent** |

The root is loaded from the trust store, not sent by the server. Its SHA-256
fingerprint is
`59:76:90:07:F7:68:5D:0F:CD:50:87:2F:9F:95:D5:75:5A:5B:2B:45:7D:81:F3:69:2B:61:0A:98:67:2F:0E:1B`.
An independent OpenSSL 3.0.13 test with strict validation enabled reproduced
verification error 86; removing only that flag succeeded with TLS 1.3.

The dedicated request-scoped session uses Requests' documented
`HTTPAdapter.build_connection_pool_key_attributes` extension point and a fresh
`ssl.create_default_context`. The active CwaAPI first tries the default strict context. Only a nested actual
SSLCertVerificationError with verify_code 86 permits one retry for the CWA host.
The fallback clears only `ssl.VERIFY_X509_STRICT`, keeping
`CERT_REQUIRED`, hostname checking, all other flags/protocol defaults, and
normal trusted CA chain validation. CA selection follows Requests' usual bundle
or configured CA file/directory; no certificate is added as a trust anchor.
The adapter is mounted only for HTTPS `opendata.cwa.gov.tw` on port 443 and
independently rejects other destinations or disabled verification. Automatic redirects
remain disabled; only the explicit daily CWA S3 distribution allowlist is followed
without the CWA credential or query. S3 uses ordinary verified TLS. HTTPS proxy TLS contexts, other hosts, ordinary Requests
sessions, and Home Assistant's global context are not changed. Sessions are
closed after each request and failures remain credential-safe.

This is a scoped compatibility workaround for the current CWA/TWCA chain, not
a general recommendation to disable strict validation. Recheck it when the
chain/trust anchor changes and remove it once the default strict handshake
works. Other TLS errors never trigger fallback; when the chain is fixed, the strict
first attempt succeeds without retrying.

References:
- https://docs.python.org/3.14/library/ssl.html#ssl.create_default_context
- https://requests.readthedocs.io/en/latest/api/#requests.adapters.HTTPAdapter.build_connection_pool_key_attributes

### Tests and real installation

Run parser/client tests on Python 3.11+ with `pip install -r requirements_test.txt`
and `pytest`. The HA suite requires Linux and Python 3.14.2+; install
`pytest-homeassistant-custom-component==0.13.364` (pins HA 2026.9.1) and run the
same command. CI runs the full suite. Tests do not contact CWA or need a key.

On a real installation verify the card after a refresh without reopening it,
day/night labels around midnight, options changes/reloads without duplicate
entities, sensor units, and reauthentication if the API key expires.

## New architecture: real installation checks

The prior PR revision was user-verified for three existing entries, TLS,
hourly/day-night display and preserved IDs. The new observation/daily/AI
architecture requires these additional checks:

1. Keep all three entries; compare entity IDs and device associations after restart.
2. Compare current temperature, station and observed_at across all modes and with
   that exact CWA station. Yonghe fixture selects C0AH10; live fallback may differ.
3. Check pressure (station hPa), humidity %, decimal m/s wind and today's rainfall.
   Missing UV/dew point/numeric weather-code sensors must not inherit forecasts.
4. Check hourly, twice_daily and daily cards across Taipei midnight; updates
   should appear without reopening. Compare daily against official Week24.
5. Change options/reload: two choices, no duplicated entities, identical current.
6. Run opencwb.get_weather with count 2 and inspect sources/times/status/errors.
   Try invalid entity/count and verify rejection.
7. Expose a weather entity to Assist and ask for weather. Revoke exposure and
   confirm access stops; repeat with a restricted user.
8. Manually run the [AI Task automation](ai-weather.md) before scheduling it.
9. Download diagnostics. Verify station/cache/source details and no API key.
   During outage, old current values must disappear after their freshness limit.
10. Confirm strict-first TLS in actual HA Python 3.14. Unload one entry while
    others remain, then unload all; the action should disappear only after the last.

Known limits: no terrain/elevation station modelling or manual override; 50 km
selection radius; day/night solar checks use HA's configured home coordinates,
so configure them correctly; no exact visibility inferred from descriptions;
short-term later periods can be three-hourly; daily needs a national archive;
service/tool use native SI units while HA weather service may convert units.
AI provider support and output quality cannot be verified by fixture-based CI.
Earlier HA releases are not claimed supported.

Domain opencwb and version-1 config structure remain unchanged. No schema
migration or deleting/recreating entries is required. Old language/coordinate
options remain stored but do not change location-based Chinese CWA products.
