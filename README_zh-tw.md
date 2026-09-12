# OpenCWA：Home Assistant 中央氣象署整合

此版本由 [txacg/FixOpenCWB](https://github.com/txacg/FixOpenCWB) 維護，
測試基準為 **Home Assistant 2026.9.1**。

目前天氣改用真實測站觀測；WeatherEntity、感測器、自動化及 AI 工具共用
同一份標準化資料。預報支援短期逐時、一週日間／夜間，以及官方逐日產品。
缺測不會補成 0，也不會用預報冒充觀測。

1.4.2 可設定[目前天氣圖示備援政策](docs/condition-display-policy.md)：
預設嚴格觀測；可選同站歷史天氣（預設 30 分鐘）或有效預報。
備援僅供顯示，原始觀測、缺測標記及來源不會被改寫。

## 安裝與升級

HACS 自訂儲存庫新增 `txacg/FixOpenCWB`，類別選 Integration；
或將 `custom_components/opencwb` 複製到 HA 設定目錄，然後重新啟動。
目前仍為 Draft PR，測試本次修改請使用 `fix/cwa-forecast-correctness` 分支；
master 尚未包含本次功能。

在[中央氣象署資料平台](https://opendata.cwa.gov.tw/)申請自己的 API key。
於「設定 → 裝置與服務」新增 OpenCWA，輸入 key 與地點，例如「新北市永和區」。
重名鄉鎮必須附縣市。模式只顯示「短期逐時預報」及「一週日間／夜間預報」。

**既有使用者請保留原本 entry，不必刪除重建。**
`opencwb` domain、config entry unique ID、weather/sensor unique ID 與裝置識別碼均保留。
舊 `daily`、`onecall_daily` 仍代表日夜預報，`onecall_hourly` 代表逐時。
修改選項不會建立另一套實體。

## 預報與 AI

天氣卡片可選 `twice_daily` 顯示白天／晚上；逐時模式選 `hourly`。
載入官方 Week24 資料後，兩種 entry 都額外支援真正的 `daily`：
一筆代表台北時間 00:00 到次日 00:00，沒有自行合併兩筆 12 小時資料。
短期產品後段原本為 3 小時間距，本整合不插值。

`opencwb.get_weather` action 可將結構化結果存入 response_variable。
Assist 工具名稱為 `opencwb__GetCWAWeather`，遵循實體曝光與使用者讀取權限。
排程 AI Task 可直接接收 action 回傳資料，不依賴模型的 tool calling 能力。

- [AI 工具與每日摘要自動化範例](docs/ai-weather.md)
- [資料來源、選站、更新快取及舊程式分類](docs/architecture.md)
- [升級、TLS 與真實 HA 驗證清單](docs/forecast-migration.md)

在[此 fork 的 issues](https://github.com/txacg/FixOpenCWB/issues)回報問題，
可附整合診斷，請勿貼 API key 或帶憑證的 URL。

原始專案為 [tsunglung/OpenCWB](https://github.com/tsunglung/OpenCWB)，
其中歷史程式衍生自 [csparpa/pyowm](https://github.com/csparpa/pyowm)；
保留原有授權與來源致謝。資料提供者為中央氣象署。
