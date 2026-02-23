# Ship GIS — 台灣海域船舶動態視覺化平台

台灣周邊海域 AIS（自動識別系統）船舶動態的即時 GIS 視覺化平台，資料來源為航港局 AIS 系統（AWS S3）。

## 功能

### 五種視覺化模式

| 模式 | Layer | 說明 |
|------|-------|------|
| 軌跡動畫 | TripsLayer | 船舶移動軌跡，速度色彩編碼，GPU shader 驅動 |
| 密度熱區 | ScreenGridLayer | 格網密度分布 |
| 六角網格 | HexagonLayer | 六角形 binning 密度圖 |
| 熱力圖 | MapLibre heatmap | 原生 heatmap layer，雙 slot cross-fade |
| 軌跡查詢 | PathLayer | 單船/多船歷史軌跡（需後端 API） |

### 互動功能

- 播放/暫停、速度控制（1x/2x/4x/8x）
- 時間軸拖曳（TripsLayer.currentTime = shader uniform，零延遲）
- 鍵盤快捷鍵（Space=播放, 左右箭頭=逐幀）
- 10 種船舶類型 checkbox 篩選（全模式皆有效）
- 日間/夜間主題自動切換 + 手動選擇
- 4 種軌跡配色方案
- 船舶點選 → 資訊卡片 + 完整軌跡 + 相機追蹤
- 277 座港口標示 + 圍欄半徑
- AIS 訊號中斷 8hr+ 自動斷開軌跡（虛線=推測航段，16hr+ 完全斷開）

## 技術架構

```
航港局 AIS 系統
      |
      v  (外部收集器，不在本 repo)
AWS S3 (ship_ais/YYYY/MM/DD/ship_ais_HHMM.json)
      |
      v  boto3 下載
import_to_db.py  →  SQLite (~2GB, 索引優化)
      |
      v  地理感知切段
generate_arrow.py --daily
      |
      ├── positions_YYYYMMDD.arrow  (按日分檔，漸進式載入)
      ├── trajectory.arrow          (軌跡動畫用)
      ├── manifest.json             (分檔索引)
      └── *.arrow.gz                (gzip 預壓縮，Nginx gzip_static 用)
           |
           v
  FastAPI / Nginx  ←→  前端 (Vite + deck.gl + MapLibre + Apache Arrow)
```

| 元件 | 技術 |
|------|------|
| 前端 | Vite + MapLibre GL JS + deck.gl 9.x + Apache Arrow |
| 後端 | FastAPI + SQLite（唯讀模式） |
| 排程 | Cron（每日 07:00 台灣時間更新） |
| 部署 | Docker Compose / Zeabur |

## 快速開始

### 環境需求

- Python 3.12+（numpy, pyarrow, boto3）
- Node.js 20+
- AWS S3 存取權限

### 安裝與執行

```bash
# 1. 環境設定
cp .env.example .env
# 編輯 .env 填入 S3 憑證

# 2. 安裝依賴
pip3 install -r scripts/requirements.txt
cd frontend && npm install && cd ..

# 3. 匯入資料 + 產出 Arrow（按日分檔 + gzip 預壓縮）
python3 scripts/import_to_db.py --days 14
python3 scripts/optimize_db.py            # 一次性索引優化
python3 scripts/generate_arrow.py --days 14 --daily

# 4. 啟動
# Terminal 1: API
uvicorn api.main:app --reload --port 8000
# Terminal 2: 前端
cd frontend && npm run dev
```

開啟 http://localhost:3000 即可使用。

### 日常資料更新

```bash
python3 scripts/import_to_db.py --incremental && python3 scripts/generate_arrow.py --days 14 --daily
```

## Arrow 資料最佳化

### 按日分檔 + 漸進式載入

`generate_arrow.py --daily` 將 positions 按日切割，前端透過 `manifest.json` 實現漸進式載入：

1. 先載入最近 2 天（秒級首次可互動）
2. 其餘天數背景逐日載入（不阻塞 UI）
3. 未載入天數的 frame 顯示空（不卡不崩）

```
frontend/public/data/
├── manifest.json              # 分檔索引（version 2）
├── positions_20260210.arrow   # 各日位置資料
├── positions_20260211.arrow
├── ...
├── trajectory.arrow           # 軌跡（不分檔，按 MMSI 排序）
├── *.arrow.gz                 # gzip 預壓縮副本
└── ports.geojson              # 港口資料
```

### gzip 預壓縮

Arrow 檔案產出後自動建立 `.gz` 預壓縮副本。Nginx 設定 `gzip_static on`，瀏覽器請求時直接送出壓縮檔（零 CPU 成本），傳輸量降低約 60-70%。

> apache-arrow JS 不支援 IPC 內建壓縮（zstd/lz4），故採用 HTTP 層壓縮方案。

### 三層 Fallback

| 優先順序 | 條件 | 行為 |
|----------|------|------|
| 1 | manifest.json 存在 | MultiDayFrameIndex + 漸進式載入 |
| 2 | positions.arrow 存在 | 原有 FrameIndex（單檔載入） |
| 3 | Arrow 全部失敗 | JSON fallback |

### CLI 參數

```bash
# 按日分檔（推薦）
python3 scripts/generate_arrow.py --days 14 --daily

# 單一檔案（舊模式）
python3 scripts/generate_arrow.py --days 14 --monolithic

# 指定時間範圍
python3 scripts/generate_arrow.py --start 2026-02-01 --end 2026-02-14 --daily
```

## 資料管線

### S3 資料結構

```
s3://migu-gis-data-collector/ship_ais/YYYY/MM/DD/ship_ais_HHMM.json
```

每個 JSON 是一個時間快照，包含當時所有在台灣海域的船舶位置（mmsi, lon, lat, sog, cog, vessel_type）。由外部收集器定期從航港局 AIS 系統抓取。

### 匯入流程

`import_to_db.py` 用 boto3 從 S3 增量下載新 JSON → 寫入 SQLite。認證方式為 AWS IAM Access Key（`.env` 設定）。

### 軌跡切段策略（方案 D）

| 條件 | 處理 |
|------|------|
| 速度 > 45kt | 切斷（GPS 異常 / MMSI 共用） |
| 穿越台灣本島 | 切斷（多邊形碰撞檢測） |
| 港內停泊 > 1h（sog < 0.5） | 切斷（港口圍欄半徑判斷） |
| AIS 中斷 8~16hr | 前端虛線連接（推測航段） |
| AIS 中斷 > 16hr | 前端完全斷開 |

### Arrow 輸出

| 檔案 | 用途 |
|------|------|
| `positions_YYYYMMDD.arrow` | 密度/六角/熱力圖（按日分檔，10 分鐘幀索引） |
| `trajectory.arrow` | 軌跡動畫（含地理切段 segment_id） |
| `manifest.json` | 分檔索引（base_timestamp, 每日 frame_times） |
| `ports.geojson` | 277 座港口座標與屬性 |
| `*.arrow.gz` | gzip 預壓縮副本（Nginx gzip_static 用） |

## 部署

### Docker Compose（自架推薦）

```bash
cp .env.example .env    # 填入 S3 憑證
docker compose up -d
```

| 服務 | 說明 | Port |
|------|------|------|
| `frontend` | Nginx（靜態 + gzip_static + API 反向代理） | 3000（可配置） |
| `api` | FastAPI 查詢 API | 8000（內部） |
| `scheduler` | Cron 每日 07:00 自動更新 | — |

| Volume | 用途 |
|--------|------|
| `db-data` | SQLite 資料庫（api + scheduler 共用） |
| `arrow-data` | Arrow IPC + gzip 檔案（scheduler 產出，frontend 讀取） |

### Zeabur 部署

專案根目錄包含統一 `Dockerfile`，支援 Zeabur 一鍵部署（前端 + API + 排程合一）。

**步驟：**

1. 在 Zeabur 建立專案，連結 Git repo
2. 設定環境變數（見下方）
3. 掛載持久儲存到 `/app/data`（SQLite 資料庫）
4. 部署即自動 build + 啟動

**必須設定的環境變數：**

| 變數 | 說明 |
|------|------|
| `S3_BUCKET` | S3 Bucket 名稱 |
| `S3_REGION` | S3 區域（如 `ap-northeast-1`） |
| `S3_ACCESS_KEY` | AWS Access Key |
| `S3_SECRET_KEY` | AWS Secret Key |
| `S3_ENDPOINT` | S3 Endpoint URL |

**可選環境變數：**

| 變數 | 預設 | 說明 |
|------|------|------|
| `PORT` | `8000` | API 監聽 Port（Zeabur 自動設定） |
| `DB_PATH` | `data/ship_data.db` | SQLite 路徑 |
| `ARROW_OUTPUT_DIR` | `frontend/public/data` | Arrow 輸出目錄 |

**排程：** 容器內建 cron，每日 07:00（台灣時間）自動執行 S3 匯入 + 清理 14 天前舊資料 + Arrow 產出（`--daily`）。首次啟動時若無 Arrow 資料會自動嘗試產出。

## 專案結構

```
ship-gis/
├── api/main.py                 # FastAPI 後端
├── frontend/
│   └── src/
│       ├── main.js              # 應用入口（漸進式載入整合）
│       ├── map.js               # MapLibre 初始化 + 主題切換
│       ├── layers/              # deck.gl 圖層
│       │   ├── trips.js         # TripsLayer (軌跡動畫)
│       │   ├── grid.js          # ScreenGridLayer (密度熱區)
│       │   ├── hexagon.js       # HexagonLayer (六角網格)
│       │   ├── heatmap.js       # MapLibre 原生 heatmap
│       │   ├── path.js          # PathLayer (查詢模式)
│       │   └── ports.js         # 港口圖層
│       ├── controls/            # 時間軸、查詢控制
│       ├── data/
│       │   ├── loader.js        # Arrow 載入（含漸進式 + fallback）
│       │   └── transform.js     # FrameIndex + MultiDayFrameIndex
│       ├── ui/legends.js        # 各模式圖例
│       └── utils/constants.js   # 常數（色彩、船舶類型、閾值）
├── scripts/
│   ├── import_to_db.py          # S3 → SQLite
│   ├── generate_arrow.py        # SQLite → Arrow IPC（--daily 按日分檔 + gzip）
│   ├── cleanup_old_data.py      # 刪除超過 N 天的舊資料
│   └── optimize_db.py           # 資料庫索引優化
├── docker/
│   ├── Dockerfile.frontend      # Nginx + gzip_static
│   ├── Dockerfile.api           # FastAPI
│   ├── Dockerfile.scheduler     # Cron 排程
│   ├── unified-start.sh         # Zeabur 單容器啟動腳本
│   └── nginx.conf               # Nginx 設定（含 gzip_static）
├── Dockerfile                   # Zeabur 統一部署
├── docker-compose.yml           # 3 服務 + 2 volumes
└── .env.example                 # 環境變數範本
```

## 船舶類型

漁船、貨船、油輪、客輪、拖船、軍艦、帆船/遊艇、高速船、服務船舶、不明
