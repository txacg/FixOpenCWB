# CWA forecast fixtures

`yonghe_hourly.json` and `yonghe_twice_daily.json` are unmodified weather
response bodies fetched on 2026-09-10 from the authenticated CWA datastore:

- F-D0047-069, LocationName=永和區
- F-D0047-071, LocationName=永和區

No request URL, credential, header, or account information is included.
Tests use explicit reference times so the forecast validity does not depend on
the date when the suite runs. Edge cases are produced from copies in tests.

Schema: https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-D0047-001_093.pdf
API: https://opendata.cwa.gov.tw/apidoc/v1
