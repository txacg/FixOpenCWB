# Data architecture (1.4.0)

Target: Home Assistant 2026.9.1. All network I/O, ZIP/XML parsing and JSON parsing
run in HA's executor. No raw response is exposed to entities, diagnostics or AI.

```text
CWA HTTPS → bounded transport → pure parsers → credential-scoped source cache
    → location WeatherSnapshot → weather / sensors / get_weather / Assist tool
```

## Sources and semantics

| Product | Use | Source timing |
| --- | --- | --- |
| O-A0001-001 | Automatic station observations | Hourly observation timestamps; published every 10 minutes |
| O-A0003-001 | Synoptic station observations | 10-minute observations/publication |
| F-D0047 town JSON pairs | Short-term / day-night forecasts | Scheduled 05:30, 11:30, 17:30, 23:30 Taipei; unscheduled revisions possible |
| F-D0047-089 / 091 | County/city short-term / day-night | Same forecast family |
| F-D0047-093 file archive, *_Week24_CH.xml | Official calendar-day forecast | Same forecast family; XML Sent retained |

For 新北市永和區 the town pair is **069 / 071**. Explicit mappings cover all
22 county/city groups. The daily archive contains official midnight-to-midnight
24-hour periods and sourced maxima/minima, mean temperature, humidity and 24-hour
precipitation probability. These are parsed directly; there is no averaging,
summing or joining of 12-hour probabilities. A live archive checked on 2026-09-11
contained 390 canonical town/county locations.

The authenticated F-D0047-093 file endpoint currently redirects to the official
CWA S3 distribution. Only that exact HTTPS host/path is accepted; it is fetched
without the CWA credential or redirect query. ZIPs are parsed in memory with
compressed/expanded/member limits, no filesystem extraction, and no XML DTD/entities.

Each forecast element uses its own DataTime or StartTime/EndTime. Point values
match timestamps; interval values must cover the output interval. Probability
requires matching boundaries. Outputs use aware UTC RFC3339 timestamps. CWA
Taipei dates and explicit offsets are preserved through conversion. Invalid
timestamps are rejected, never replaced by now.

## Observation selection

Coordinates use official **WGS84**, not whichever coordinate object comes first.
The configured place uses its official short-term forecast representative point
(the township office for town products). Both UI modes always use the same point.

1. Consider stations within 50 km. Reject observations more than 5 minutes ahead.
2. O-A0001 observations are usable for 90 minutes; O-A0003 for 30 minutes.
3. Require at least one of temperature, humidity, pressure or wind speed.
4. For duplicate station IDs, prefer usable temperature, then newest observation,
   then valid Weather availability, number of available fields, then dataset ID.
5. Across stations prefer usable temperature, then the configured town (or county
   for a county query), then distance, then valid Weather availability, then station ID.

These are explicit integration selection policies, not a CWA promise that a
station represents every microclimate. Missing temperature can cause station
fallback; a missing secondary field does not mix in another station's value.
Stale stations are excluded. If none qualify, current data is unavailable/stale/
missing_values; forecast values are never substituted. If the short-term product
has never supplied coordinates, selection reports missing_coordinates.

Selected station ID/name, distance, dataset, observed_at, age and quality are
retained. A transport failure can reuse a still-fresh cached observation with
status cached. Values disappear once too old. Rain is **today's accumulated
precipitation**, pressure is **station pressure**, humidity is percentage.
-99 means missing; X equipment error; T trace has a quality flag, no fabricated
numeric amount. -98 indicates the documented dry-last-six-hours condition and
does not become today's 0 mm. Wind 990 is variable direction. Decimal wind and
zero temperature are preserved. Gusts include their occurrence time and are
not Beaufort scale values. Visibility descriptions such as 11-15 or >30 remain
descriptions, not invented exact visibility. Unsourced apparent temperature,
dew point, numeric weather code or UV remain absent.

Condition mapping uses observation descriptions separately from forecast codes.
Valid unfamiliar raw descriptions remain available with condition quality
unmapped; missing Weather has an explicit quality flag. Only the normalized
condition is omitted when unknown. Existing current sensors for
   unsourced fields remain registered but show unknown. No cross-station blending.

## Shared cache and lifecycle

One in-memory repository per API credential, referenced by loaded entries.
Credential hashes are internal only and never diagnostics fields.
Forecast keys include dataset and canonical routed town; observations and the
national daily archive are shared across locations for that credential.
Different credentials have independent caches. Concurrent identical requests
await one shielded task. Failures use a 60-second retry backoff; last-good data
retains its original fetch time, never masquerading as a successful new fetch.

Every entry evaluates freshness every 5 minutes. Network TTLs are 10 minutes for
observations, up to one hour short-term, and up to three hours day/night/daily.
Forecast TTLs shorten to the next scheduled release plus ten minutes' grace.
The coordinator cycle can add up to five minutes' delay. This checks unscheduled
updates without downloading every forecast on each coordinator update.
All products are prepared for the shared action/tool regardless of primary UI
mode. The approximately 4.8 MB daily archive is downloaded once per credential/TTL.

The last entry unload removes pool ownership before awaiting task cancellation;
a new setup cannot reuse a closing cache. Setup failure releases ownership.
Forecast subscriptions receive coordinator updates without reopening the card.
Reauthentication updates only the key; options reload only the existing entry.

## Legacy audit and directly related cleanup

| Area | Classification / decision |
| --- | --- |
| opencwb domain, entry/device/sensor unique-ID construction, stored mode strings | Required identity compatibility; retained |
| const.py sensor definitions and location_tw.py | Active; retained |
| cwa_* parsers, transport, cache/model, repository and HA adapters | Active |
| Legacy OCWB/weatherapi12, old generic HTTP client and geo helpers | Unused by the HA runtime; retained as historical library code outside this focused replacement |
| core/__init__.py eager OCWB import | Dead runtime dependency; removed so HA does not import legacy library |
| const.py CONDITION_CLASSES and associated HA condition imports | Proven unused by repository search; removed (also contained obsolete mapping) |
| geojson manifest requirement | Only referenced by inactive legacy geo helpers; removed from HA requirements, retained in legacy test environment |

No claim is made that every historic library method is modernized or supported.
Tests still exercise the legacy client/parser bridges to avoid unintentional
breakage while keeping their large deletion separate. HA sensor code now uses
native_value/native_unit_of_measurement. Fork documentation, maintainer metadata
and UI translations identify Central Weather Administration / 中央氣象署.

## Official references

- [Observation schema O-A0001](https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0001-001.pdf)
- [Observation schema O-A0003](https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0003-001.pdf)
- [Forecast schema and products](https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-D0047-001_093.pdf)
- [CWA API](https://opendata.cwa.gov.tw/apidoc/v1)
- [Observation publication metadata](https://opendata.cwa.gov.tw/webapi/datasetMetadata/O-A0001-001)
- [Daily distribution metadata](https://opendata.cwa.gov.tw/webapi/datasetMetadata/F-D0047-093)
- [HA weather contract](https://developers.home-assistant.io/docs/core/entity/weather/)
- [HA LLM API](https://developers.home-assistant.io/docs/core/llm/)
