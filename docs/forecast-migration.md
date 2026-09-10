# Forecast behavior in 1.3.0

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

`hourly` and `onecall_hourly` expose **hourly**. All four stored settings use a
single request per refresh. They are retained to preserve existing identities.
The options selector describes the actual products.

CWA may shorten the first day/night period (for example, 12:00–18:00).
Its actual start time is preserved and it remains a daytime forecast. Night
periods beginning after midnight remain nighttime forecasts through 06:00.

Short-term temperature point times determine the forecast timeline. Other point
values are included only at the same timestamp; interval values must cover that
forecast period. No wind values are interpolated. A three-hour probability is
not exported as a one-hour probability; it is included only where the forecast
has the same three-hour boundaries. Missing values remain unavailable.

The current weather remains a **prediction**, selected from the interval valid
now. A valid current period also remains in the forecast list. Mean temperature
from the weekly product is not a station observation. Maximum apparent
temperature is not presented as the current apparent temperature. Observation
station selection is outside this change.

## CWA products

For 新北市永和區, the authenticated JSON endpoints verified on 2026-09-10 are
F-D0047-069 (short-term) and F-D0047-071 (12-hour day/night). County-level queries
use F-D0047-089 and F-D0047-091. Township products have explicit county/dataset
mappings. No latitude/longitude or language parameters are sent to this API.

True daily forecasts are **not fabricated or advertised**. The official daily
product exists: the F-D0047-093 file API archive downloaded on 2026-09-10 has
`file.csv`, which identifies `65_Week24_CH.xml` as 新北市一週24小時天氣預報XML檔中文.
The archive is about 4.8 MB and contains all locations/products, rather than a
location-filtered JSON response. A follow-up should implement and test ZIP/XML
selection, shared caching, interval semantics and failure handling before
advertising daily forecasts. It must use the official 24-hour values, including
24-hour precipitation probability, without combining 12-hour probabilities.

Sources:
- https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-D0047-001_093.pdf
- https://opendata.cwa.gov.tw/apidoc/v1
- https://opendata.cwa.gov.tw/webapi/datasetMetadata/F-D0047-093
- https://developers.home-assistant.io/docs/core/entity/weather/
- https://www.cwa.gov.tw/Data/js/WeatherIcon.js

## Validation

Run parser/client tests on Python 3.11+ with `pip install -r requirements_test.txt`
and `pytest`. The HA suite requires Linux and Python 3.14.2+; install
`pytest-homeassistant-custom-component==0.13.364` (pins HA 2026.9.1) and run the
same command. CI runs the full suite. Tests do not contact CWA or need a key.

On a real installation verify the card after a refresh without reopening it,
day/night labels around midnight, options changes/reloads without duplicate
entities, sensor units, and reauthentication if the API key expires.
