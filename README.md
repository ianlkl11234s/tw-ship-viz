# 台灣海域船舶視覺化

台灣周邊海域的即時船舶視覺化平台，資料來源為航港局 AIS 系統。

## 技術棧

| 項目 | 技術 |
|------|------|
| 地圖引擎 | MapLibre GL JS (WebGL) |
| 資料視覺化 | deck.gl (GPU 加速) |
| 資料格式 | Apache Arrow IPC (零拷貝) |
| 前端打包 | Vite |
| 後端 | FastAPI + SQLite |
| 部署 | Docker Compose |

## 功能

### 五種視覺化模式

| 模式 | deck.gl Layer | 說明 |
|------|---------------|------|
| 軌跡動畫 | TripsLayer | 船舶移動軌跡，速度色彩編碼，GPU shader 驅動 |
| 密度熱區 | ScreenGridLayer | 格網密度分布 |
| 六角網格 | HexagonLayer | 六角形 binning 密度圖 |
| KDE 熱力圖 | HeatmapLayer | 核密度估計熱力圖 |
| 軌跡查詢 | PathLayer | 單船/多船歷史軌跡（需後端 API） |

### 互動功能

- 播放/暫停、速度控制（1x/2x/4x/8x）
- 時間軸 slider 即時拖曳（TripsLayer.currentTime = shader uniform，零延遲）
- 鍵盤快捷鍵（Space=播放, 左右箭頭=逐幀）
- 10 種船舶類型 checkbox 篩選
- 日間/夜間模式切換（CARTO Positron / Dark Matter）
- 軌跡查詢：點選單船 / 矩形圈選多船

## 專案結構

```
ship-gis/
├── frontend/                    # Vite 前端專案
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js              # 入口：map + deck.gl + UI 整合
│       ├── map.js               # MapLibre 初始化 + 主題切換
│       ├── style.css            # 完整樣式（日間/夜間）
│       ├── layers/              # deck.gl 圖層
│       │   ├── trips.js         # TripsLayer (軌跡動畫)
│       │   ├── grid.js          # ScreenGridLayer (密度)
│       │   ├── hexagon.js       # HexagonLayer (六角)
│       │   ├── heatmap.js       # HeatmapLayer (熱力圖)
│       │   └── path.js          # PathLayer (查詢軌跡)
│       ├── controls/            # 互動控制
│       │   ├── timeline.js      # 時間軸 + 播放控制
│       │   └── query.js         # 軌跡查詢（點選/圈選）
│       ├── data/                # 資料載入與轉換
│       │   ├── loader.js        # Arrow IPC 載入 + JSON fallback
│       │   └── transform.js     # Arrow → deck.gl 資料結構
│       ├── ui/
│       │   └── legends.js       # 各模式圖例
│       └── utils/
│           └── constants.js     # 常數（色彩、船舶類型、主題）
├── api/
│   └── main.py                  # FastAPI 查詢 API + 靜態檔案服務
├── scripts/
│   ├── requirements.txt         # Python 依賴
│   ├── import_to_db.py          # S3 → SQLite 匯入
│   ├── generate_arrow.py        # SQLite → Arrow IPC 產出
│   ├── optimize_db.py           # 資料庫索引優化
│   ├── generate_json.py         # SQLite → JSON（向下相容）
│   ├── grid_utils.py            # 格網計算工具
│   └── vessel_types.py          # 船舶類型定義
├── docker/
│   ├── Dockerfile.frontend      # Vite build → Nginx
│   ├── Dockerfile.api           # FastAPI + uvicorn
│   ├── Dockerfile.scheduler     # cron 自動更新 S3 + Arrow
│   └── nginx.conf               # Nginx 反向代理 + gzip
├── docker-compose.yml           # 3 服務 + 2 volumes
├── data/
│   └── ship_data.db             # SQLite（gitignore）
└── public/                      # 舊版前端（保留向下相容）
```

## 快速開始

### 前置需求

- Node.js >= 18
- Python >= 3.10
- S3 存取權限（AIS 資料源）

### 安裝

```bash
# Python 依賴
pip3 install -r scripts/requirements.txt

# 前端依賴
cd frontend && npm install && cd ..

# 環境變數
cp .env.example .env
# 編輯 .env 填入 S3 設定
```

### 資料準備

```bash
# 1. 匯入 S3 資料到 SQLite
python3 scripts/import_to_db.py --days 7

# 2. 優化資料庫索引（執行一次即可）
python3 scripts/optimize_db.py

# 3. 產出 Arrow IPC 檔案
python3 scripts/generate_arrow.py --days 7
```

### 本地開發

```bash
# 前端 dev server（port 3000，自動 proxy /api 到 8000）
cd frontend && npm run dev

# 後端 API（另一個 terminal）
cd api && uvicorn main:app --reload --port 8000
```

開啟 http://localhost:3000 即可使用。

### 日常資料更新

```bash
# 增量匯入 + 重新產出 Arrow
python3 scripts/import_to_db.py --incremental && python3 scripts/generate_arrow.py --days 7
```

## Docker 部署

### 一鍵啟動

```bash
# 建立 .env 檔案（S3 credentials）
cp .env.example .env

# 啟動所有服務
docker compose up -d
```

### 服務架構

| 服務 | 說明 | Port |
|------|------|------|
| frontend | Nginx 靜態服務 + API 反向代理 | 3000 (可設定) |
| api | FastAPI 查詢 API | 8000 (內部) |
| scheduler | cron 每 10 分鐘自動同步 S3 + 產出 Arrow | - |

### Volumes

| Volume | 用途 |
|--------|------|
| db-data | SQLite 資料庫（api + scheduler 共用） |
| arrow-data | Arrow IPC 檔案（scheduler 產出，frontend + api 讀取） |

### 環境變數

```env
# .env
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_DEFAULT_REGION=ap-northeast-1
S3_BUCKET=your-bucket
FRONTEND_PORT=3000
```

## 船舶類型

貨船、油輪、客輪、漁船、拖船、軍艦、帆船/遊艇、高速船、服務船舶、不明
