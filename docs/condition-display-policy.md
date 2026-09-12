# Current-condition display policy (1.4.2)

Configure this in OpenCWA setup/options. Existing entries default to
**strict_observation**, without migration or changed entity IDs.
The policy changes only the WeatherEntity condition/icon. Measurements and
observation sensors stay authoritative station data.

| Policy | If selected station Weather is missing/unmapped | Accuracy tradeoff |
| --- | --- | --- |
| strict_observation | Unknown | Default/recommended; most faithful to the observation |
| last_valid_observation | Most recent recognized Weather from the same station, within the age limit | A past observation may not describe present weather |
| forecast_fallback | Recognized short-term forecast condition valid now | A prediction may disagree with actual weather; explicitly forecast-derived |

Valid current observations always win. No fallback applies without a fresh
selected observation. If no eligible fallback exists, the display stays unknown.
The policies do not chain: last_valid_observation never tries forecast.
Accumulated rainfall is never used to infer current rain.

## Same-station history

The age option is **1–120 minutes, default 30**, from the original observation
timestamp, never the fetch/display time. Only recognized Weather is remembered.
Missing/unmapped updates cannot overwrite valid history; repeated cached responses
cannot renew its timestamp. Other stations, future records and expired records
cannot supply the display condition. Either observation dataset may supply a
record for the same station ID. Day/night icons use the current solar state.

History is in memory, isolated by API credential and station ID, and survives
options reload/temporary unload in the running HA process. It is not persisted:
after restart, valid observations must accumulate again. Records are pruned at
the hard 120-minute bound on access/update; inactive empty history containers
are removed during setup. An hourly station may have no record inside 30 minutes;
this does not justify extending its original timestamp.

## Forecast display

Only the already-fetched short-term hourly product is considered, independently
of the entry's forecast mode. A period must satisfy start <= now < end and have
a recognized condition. Expired/future periods cannot qualify; the later
three-hour periods keep their actual boundaries. There is no inference from
daily/day-night summaries and no extra network request.

The weather entity schedules an update at fallback expiration so the icon does
not wait for the next poll. Structured requests always recheck the age/interval.
Coordinator updates replace this timer; entity unload cancels it.

## Observation versus display

Action, LLM, AI Tasks and diagnostics retain current.source=observation and
**current.condition=null** when observed Weather is missing/unmapped.
Weather=-99 retains quality.weather=missing. Unknown valid raw text remains in
current.weather with quality.condition=unmapped. Display fallback changes neither.

Abbreviated example (illustrative, not live weather):

```json
{
  "current": {
    "source": "observation", "condition": null,
    "station": {"id": "C0AH10", "name": "永和"},
    "dataset": "O-A0001-001", "observed_at": "2026-09-12T10:00:00+00:00",
    "quality": {"weather": "missing"}
  },
  "display_condition": {
    "policy": "forecast_fallback", "condition": "rainy",
    "source": "forecast_fallback", "forecast_type": "hourly",
    "dataset": "F-D0047-069",
    "valid_from": "2026-09-12T10:00:00+00:00",
    "valid_until": "2026-09-12T11:00:00+00:00",
    "fetched_at": "2026-09-12T10:05:00+00:00"
  }
}
```

Historical display instead includes source=last_observation, station_id,
dataset, original observed_at, age_seconds, raw weather and condition.
If the current observation is mapped, display source is observation.
Without an eligible value, display condition is null and source is unavailable.
The selected policy is always included.

WeatherEntity attributes expose observation and display_condition separately.
Its current Condition sensor can correctly remain unknown while the weather
card shows a fallback. The LLM prompt prohibits reporting fallback as observed
current weather; any explanation must state the source/time.
Clients must accept explicit null current.condition (1.4.1 omitted this key).

## Real-installation checks

1. With Weather=-99, strict must show unknown; action/diagnostics must show
   current.condition=null and the missing quality flag.
2. Enable forecast display: inspect forecast_fallback source and validity bounds.
   Temperature/pressure/humidity/wind and current.source must not change.
3. Collect a valid Weather before testing history. After a missing/unmapped
   update, confirm the same station and original timestamp, then expiration.
4. Switch policies through options; confirm IDs, measurements and effective
   option defaults are preserved. History should survive reload.
5. Compare get_weather, the LLM tool and diagnostics. Test your AI provider
   distinguishes past observations/predictions from actual current observation.
