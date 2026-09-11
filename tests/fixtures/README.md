# CWA forecast fixtures

`yonghe_hourly.json` and `yonghe_twice_daily.json` are unmodified weather
response bodies fetched on 2026-09-10 from the authenticated CWA datastore:

- F-D0047-069, LocationName=永和區
- F-D0047-071, LocationName=永和區

No request URL, credential, header, or account information is included.
Tests use explicit reference times so the forecast validity does not depend on
the date when the suite runs. Edge cases are produced from copies in tests.

`yonghe_twice_daily_partial.json` was fetched later on 2026-09-10 from
F-D0047-071. It retains the first two samples of each element, without changing
their values. The first weather period is 12:00–18:00, demonstrating that the
official day/night product can begin with a shortened period.

Schema: https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-D0047-001_093.pdf
API: https://opendata.cwa.gov.tw/apidoc/v1

`O-A0001-001.json` and `O-A0003-001.json` were fetched on 2026-09-11.
They retain the unmodified records for 永和、臺北、板橋、淡水、硬漢嶺 when
present in each product. Other stations were removed to keep fixtures compact.
Observation semantics: https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0001-001.pdf

`yonghe_daily.xml` retains 永和區 from official `65_Week24_CH.xml` in F-D0047-093 downloaded on 2026-09-11. Other locations were removed and namespace prefixes normalized; seven official 24-hour periods and values are unchanged. It is not derived from 12-hour JSON.
