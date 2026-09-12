# Current Weather diagnostics (1.4.1)

In 1.4.2, unavailable current.condition is explicitly null and optional
[display fallback](condition-display-policy.md) is separate from current data.
The investigation and missing-Weather evidence below remain applicable.

## Live investigation

Read-only API checks on 2026-09-12 around 18:12 Asia/Taipei found:

| Dataset / station | Observation time (Taipei) | Raw Weather | Temperature |
| --- | --- | --- | --- |
| O-A0001-001 / 永和 C0AH10 | 18:00 | -99 | 27.6°C |
| O-A0001-001 / 臺北 466920 | 18:00 | -99 | 27.6°C |
| O-A0003-001 / 臺北 466920 | 17:50 | 晴 | 27.7°C |

C0AH10 was absent from O-A0003. All 876 stations in this particular O-A0001
response had Weather=-99, while O-A0003 still had real descriptions. This is
evidence for a missing upstream Weather field at the sampled time, not proof
of a permanent station limitation or the precise upstream outage cause.
C0AH10 remained the correctly selected local station with usable measurements.

The [official station description](https://opendata.cwa.gov.tw/opendatadoc/DIV2/A0001-001.pdf)
defines -99 as no data at that time. Therefore unknown is an honest HA condition
for this observation. Mapping cannot recover a missing measurement.
The exact C0AH10 response record is retained in the regression fixture without
request URLs, headers or credentials.

## Parser and mapping changes

1. Nonempty non-sentinel Weather text is retained as current.weather even if no
   HA condition mapping exists. It is the sourced description, not a translation.
2. Missing Weather yields quality.weather=missing; X yields equipment_error.
   Numeric/non-string invalid descriptions and T (not a Weather description)
   are omitted with invalid quality. Measurements still remain available.
3. Valid unfamiliar descriptions retain current.weather and expose
   quality.condition=unmapped. current.condition is present only when mapped.
4. The mapper recognizes complete cloud+phenomenon combinations in
   [O-A0001/O-A0003 schema appendix 2](https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0001-001.pdf).
   It handles 晴/多雲/陰 with haze/mist/fog, lightning, rain, snow, ice pellets,
   hail and thunder combinations. Observed live examples include 多雲有靄 and 晴有霾.
   HA has one condition slot: thunder+snow maps snowy, thunder+hail maps hail,
   thunder+rain maps lightning-rainy; the raw text preserves both phenomena.
   Bare substring matches are avoided: an unfamiliar sentence containing 雨
   is not automatically interpreted as currently raining.

All fields retain one observation source, station and observed_at.
No forecast condition is substituted. Today's accumulated precipitation is
never evidence for rain at the current instant.

Examples (abbreviated structured current objects):

```json
{"source":"observation","station":{"id":"C0AH10","name":"永和"},
 "dataset":"O-A0001-001","observed_at":"2026-09-12T10:00:00+00:00",
 "temperature":27.6,"quality":{"weather":"missing"}}
```

An unfamiliar but valid description produces weather="特殊天氣描述" and
quality.condition="unmapped"; a recognized 晴有閃電 produces that raw weather
plus condition="lightning". The weather entity, action, LLM tool and diagnostics
consume this same model. Existing current Weather sensor also retains valid raw text.

## Station selection decision

Weather availability is a completeness tie-break, independent of whether the
mapper knows the text. For duplicate reports of one station, temperature and
newest timestamp still take priority; then valid Weather, number of fields,
dataset ID. Across stations, temperature, town membership and distance remain
primary; valid Weather only precedes the final station-ID tie-break.

This intentionally does not switch Yonghe's whole observation to a farther
Taipei station solely to display an icon. Missing secondary fields do not
cause station blending, and an older report with Weather cannot replace a
newer otherwise useful report merely for its description.

## Re-test on Home Assistant

Install 1.4.1 from the same Draft PR branch and reload/restart. Inspect
opencwb.get_weather with forecast_type: none and the entity's observation
attribute (or diagnostics). Confirm station, observed_at, raw weather when valid,
and quality.weather/quality.condition. If CWA still supplies -99, unknown is
expected while temperature/pressure/humidity/wind remain usable.
When a valid description arrives, confirm the raw Weather sensor and structured
output retain it, and recognized descriptions also give a normalized condition.
Forecasts and entity IDs should remain unchanged.
