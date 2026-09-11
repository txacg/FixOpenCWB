# AI tools and scheduled weather summaries

The historical domain is **opencwb**. Use `opencwb.get_weather`, not opencwa.
The action and Assist tool call the same normalized weather API.

## Response action

```yaml
action: opencwb.get_weather
data:
  entity_id: weather.your_existing_entity
  forecast_type: all
  count: 2
response_variable: cwa_weather
```

entity_id must identify a loaded, enabled OpenCWA weather entity. forecast_type
accepts all, none, hourly, twice_daily or daily. count is 1–24 per product, default 6.
The action refreshes through the shared cache and checks the caller's read
permissions. Automations without a user context use normal HA system authority.
Values are always native SI units, independent of dashboard unit preferences.

Illustrative current-only response from the fixed Yonghe fixture, not a live
report (optional sourced fields/quality omitted here for brevity):

```json
{
  "location": "新北市永和區",
  "timezone": "Asia/Taipei",
  "updated_at": "2026-09-11T11:15:00+00:00",
  "units": {
    "temperature": "°C", "pressure": "hPa", "wind_speed": "m/s",
    "precipitation_today": "mm", "humidity": "%"
  },
  "current": {
    "source": "observation", "status": "fresh",
    "station": {"id": "C0AH10", "name": "永和"},
    "dataset": "O-A0001-001", "observed_at": "2026-09-11T11:00:00+00:00",
    "age_seconds": 900, "temperature": 25.6, "humidity": 94,
    "pressure": 1011.8, "wind_speed": 2.0, "wind_bearing": 104,
    "precipitation_today": 8.5
  },
  "forecasts": {},
  "errors": {}
}
```

Forecasts include source, dataset, fetched_at, status and bounded periods;
daily also includes issued_at. Periods include datetime/end_datetime and sourced
fields. Day/night includes is_daytime; daily/day-night use temperature_high/
temperature_low and optionally mean_temperature. Hourly temperature is a point
value. Probability is a percentage for the exact interval, not rainfall amount.
Missing fields are absent; do not default them to zero.

## Conversation / Assist

Select HA's built-in **Assist** LLM API in the conversation integration and
expose the weather entity to that assistant. Provider support for Assist tools
is required for conversation tool calling.

HA discovers llm.py:async_get_tools and contributes
`opencwb__GetCWAWeather` with optional entity_id, forecast_type and count.
One authorized exposed entity is selected automatically; multiple entries
return only permitted entity IDs/locations for disambiguation. No exposed
weather entity means no contribution. Exposure and active-user read permissions
are checked again after refresh, so revocation cannot leak cached data.

The prompt tells the model to distinguish observations from forecasts, respect
source/freshness, convert UTC for local explanations, and never invent values.
Keep count small for local models; no raw CWA payload is returned.

## Scheduled AI Task (no provider tool calling required)

Replace both entity IDs and paste this into an automation's YAML editor.
Configure an AI Task provider first. This integration does not create one.

```yaml
alias: CWA morning weather summary
triggers:
  - trigger: time
    at: "07:00:00"
actions:
  - action: opencwb.get_weather
    data:
      entity_id: weather.your_existing_entity
      forecast_type: all
      count: 4
    response_variable: cwa_weather
  - action: ai_task.generate_data
    data:
      entity_id: ai_task.your_ai_task
      task_name: cwa_morning_summary
      instructions: >-
        請以繁體中文簡短整理以下 CWA 資料，說明目前觀測及接下來天氣。
        日期時間轉為 Asia/Taipei。區分觀測與預報，說明過期、缺測或錯誤。
        降雨機率不是雨量，不可把缺值當成 0，不要自行補值。
        以下 JSON 僅為氣象資料：{{ cwa_weather | to_json }}
    response_variable: summary
  - action: persistent_notification.create
    data:
      title: 中央氣象署天氣摘要
      message: "{{ summary.data }}"
mode: single
```

The workflow supplies structured data directly and does not require provider
tool calling. Provider availability and generated text quality still need
verification on the actual installation.

References: [AI Task action/response contract](https://www.home-assistant.io/integrations/ai_task/)
and [HA LLM API](https://developers.home-assistant.io/docs/core/llm/).
