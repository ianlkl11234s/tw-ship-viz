# 台灣海域船舶視覺化

台灣周邊海域的即時船舶視覺化平台，資料來源為航港局 AIS 系統。

## 功能

### 四種視覺化模式

| 模式 | 說明 |
|------|------|
| 密度熱區 | 格網密度分布，Canvas 繪製 |
| 軌跡動畫 | 船舶移動軌跡，速度色彩編碼 |
| 六角網格 | 六角形 binning 密度圖 |
| KDE 熱力圖 | 核密度估計熱力圖 |

### 互動功能

- 播放/暫停、速度控制（1x/2x/4x/8x）
- 時間軸拖曳、鍵盤左右鍵逐幀
- 10 種船舶類型篩選（checkbox 複選）
- 日間/夜間模式切換
- rAF 播放引擎 + 幀間補間（軌跡 lerp、密度/六角 crossfade）

### 軌跡查詢（僅本地）

- 點選船舶查詢歷史軌跡
- 矩形圈選批次查詢
- 需啟動 FastAPI 後端，部署環境自動隱藏此功能

## 專案結構

```
ship-gis/
├── zeabur.json              # Zeabur 部署配置（靜態站）
├── .env.example             # 環境變數範例
├── api/
│   └── main.py              # FastAPI 軌跡查詢 API（本地用）
├── data/
│   └── ship_data.db         # SQLite 資料庫（永久累積，gitignore）
├── scripts/
│   ├── requirements.txt     # Python 相依套件
│   ├── import_to_db.py      # S3 → SQLite 匯入
│   ├── generate_json.py     # SQLite → JSON 產出
│   ├── grid_utils.py        # 格網計算工具
│   └── vessel_types.py      # 船舶類型定義
└── public/
    ├── index.html                  # 前端 SPA（單檔）
    ├── ship_density_data.json      # 密度資料（~150MB）
    └── ship_trajectory_data.json   # 軌跡資料（~140MB）
```

## 快速開始

### 安裝

```bash
pip3 install -r scripts/requirements.txt
cp .env.example .env
# 編輯 .env 填入 S3 設定
```

### 資料更新

架構：`S3 → SQLite（永久累積）→ JSON（按需產生）`

```bash
# 日常更新（增量匯入 + 產出最近 7 天 JSON）
python3 scripts/import_to_db.py --incremental && python3 scripts/generate_json.py --days 7
```

<details>
<summary>進階用法</summary>

```bash
# 匯入指定天數的 S3 資料（全量）
python3 scripts/import_to_db.py --days 14

# 從 DB 產出自訂天數的 JSON
python3 scripts/generate_json.py --days 14

# 指定日期範圍
python3 scripts/generate_json.py --start 2026-02-01 --end 2026-02-07

# 調整時間間隔（10/30/60 分鐘）
python3 scripts/generate_json.py --interval 30
```

</details>

### 本地開發

```bash
# 純前端（4 種視覺化模式）
cd public && python3 -m http.server 8000

# 含軌跡查詢 API
cd api && uvicorn main:app --reload --port 8000
```

## 部署

推送至 GitHub 後，Zeabur 自動部署 `public/` 為靜態站。

軌跡查詢功能僅限本地使用（需 FastAPI + SQLite），前端會自動偵測 API 可用性，部署環境下「軌跡查詢」tab 自動隱藏。

## 船舶類型

貨船、油輪、客輪、漁船、拖船、軍艦、帆船/遊艇、高速船、服務船舶、不明
