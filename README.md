# OpenCWA for Home Assistant

CWA station observations and official Taiwan forecasts for Home Assistant **2026.9.1**.
Maintained at [txacg/FixOpenCWB](https://github.com/txacg/FixOpenCWB).
[繁體中文](README_zh-tw.md).

Current weather, sensors, automations and Assist tools use the same normalized
data. Current values come from real stations, never from forecast rows.
Forecasts support short-term hourly, one-week day/night and official calendar-day
products. Missing measurements stay missing.

The [current-condition display policy](docs/condition-display-policy.md) defaults
to strict observation. Optional same-station history or forecast icons have
separate provenance; structured current observations remain unchanged.

## Install and upgrade

Add `txacg/FixOpenCWB` as an Integration custom repository in HACS, or copy
`custom_components/opencwb` into your Home Assistant configuration's
`custom_components` directory. Restart Home Assistant.
While this change is a Draft PR, install the reviewed development branch
`fix/cwa-forecast-correctness`; master does not contain this work yet.

Obtain your own key from the [CWA open-data platform](https://opendata.cwa.gov.tw/).
In Settings → Devices & services, add OpenCWA and enter the key and a location,
for example `新北市永和區`. Include the county/city for ambiguous town names.
Choose Short-term hourly forecast or One-week day/night forecast.

**Existing users: retain your entries.** The `opencwb` domain, stored unique IDs,
device identifiers and existing weather/sensor entities are preserved.
Old `daily` / `onecall_daily` options mean day/night; old `onecall_hourly` means
hourly. See [upgrade notes](docs/forecast-migration.md) before changing cards.
No deletion or re-creation of entries is required.

## Weather cards and AI

The selected mode controls the weather entity's primary forecast and existing
forecast sensors. True `daily` is additionally available when CWA's official
Week24 product is loaded. For example:

```yaml
type: weather-forecast
entity: weather.your_existing_entity
forecast_type: daily
```

Use `twice_daily` for separate day/night periods, or `hourly` on an hourly entry.
CWA's short-term timeline becomes three-hourly later in its range; no interpolation
or invented one-hour rain probabilities are applied.

[AI and automation examples](docs/ai-weather.md) cover
`opencwb.get_weather`, the contributed `opencwb__GetCWAWeather` Assist tool, and
a scheduled `ai_task.generate_data` summary. The response action works even if
your AI provider does not support tool calling.

[Architecture and source semantics](docs/architecture.md) explain station
selection, freshness, caching, dataset IDs and the legacy-code audit.
[Upgrade and TLS notes](docs/forecast-migration.md) include real-installation checks.

## Development

`python -m pip install -r requirements_test.txt`, then `python -m pytest -q`.
Pure parser/transport tests run on Python 3.11+. Full HA tests require Linux,
Python 3.14.2+ and `pytest-homeassistant-custom-component==0.13.364`, which pins
Home Assistant 2026.9.1. CI runs the complete suite without live API keys.

Report issues at [this fork's issue tracker](https://github.com/txacg/FixOpenCWB/issues)
with downloaded integration diagnostics. Do not post API keys or credential-bearing URLs.

## Credits

Forked from [tsunglung/OpenCWB](https://github.com/tsunglung/OpenCWB).
The original integration included code derived from
[csparpa/pyowm](https://github.com/csparpa/pyowm). Original license and attribution
are retained. Data is provided by Taiwan's Central Weather Administration (中央氣象署).
