# Ship GIS 重構計畫：Deck.gl + MapLibre + Arrow + Docker

## 目標
將現有 Leaflet + Canvas + JSON 架構升級為 Deck.gl + MapLibre + Arrow + Docker，
實現大資料量下的流暢軌跡播放與即時時間軸拖曳。

## 技術棧變更

| 項目 | 現有 | 目標 |
|------|------|------|
| 地圖引擎 | Leaflet.js (Canvas 2D) | MapLibre GL JS (WebGL) |
| 資料視覺化 | 手寫 Canvas 渲染 | deck.gl (GPU 加速) |
| 資料格式 | JSON (285 MB) | Apache Arrow IPC (~50-70 MB) |
| 前端打包 | 無（`<script>` 標籤） | Vite (ES modules) |
| 後端 | 可選 FastAPI | 必要 FastAPI（Arrow 產出 + 查詢）|
| 部署 | Zeabur 靜態 | Docker Compose |
| 定時任務 | 手動跑 Python 腳本 | cron 容器自動更新 |

## 目標專案結構

```
ship-gis/
├── frontend/                    # Vite 專案
│   ├── index.html               # 入口 HTML
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.js              # 入口：初始化 map + deck + UI
│       ├── map.js               # MapLibre 地圖初始化 + 日夜間底圖
│       ├── layers/
│       │   ├── trips.js         # TripsLayer (軌跡動畫)
│       │   ├── scatterplot.js   # ScatterplotLayer (即時船舶位置)
│       │   ├── hexagon.js       # HexagonLayer (六角網格密度)
│       │   ├── heatmap.js       # HeatmapLayer (KDE 熱力圖)
│       │   ├── grid.js          # ScreenGridLayer (密度格網)
│       │   └── path.js          # PathLayer (查詢模式軌跡)
│       ├── controls/
│       │   ├── timeline.js      # 時間軸 slider + 播放控制
│       │   ├── filters.js       # 船舶類型 checkbox 篩選
│       │   ├── theme.js         # 日夜間主題切換
│       │   └── query.js         # 軌跡查詢模式（點選/圈選）
│       ├── data/
│       │   ├── loader.js        # Arrow IPC 載入（含 fallback JSON）
│       │   └── transform.js     # Arrow Table → deck.gl 資料轉換
│       ├── ui/
│       │   ├── panels.js        # 狀態面板 + 統計資訊
│       │   └── legends.js       # 各模式圖例
│       └── utils/
│           ├── colors.js        # 速度/密度色彩映射
│           └── constants.js     # 常數定義（船舶類型、地理範圍等）
├── api/                         # FastAPI 後端
│   ├── main.py                  # API 路由（維持 + 擴充）
│   ├── arrow_export.py          # Arrow 格式產出
│   ├── db.py                    # 資料庫連線管理
│   └── requirements.txt
├── scripts/                     # 資料處理（維持現有 + 新增 Arrow 產出）
│   ├── import_to_db.py
│   ├── generate_arrow.py        # 新增：SQLite → Arrow IPC
│   ├── generate_json.py         # 保留：向下相容
│   ├── grid_utils.py
│   ├── vessel_types.py
│   └── requirements.txt
├── docker/
│   ├── Dockerfile.frontend
│   ├── Dockerfile.api
│   └── Dockerfile.scheduler
├── docker-compose.yml
├── data/                        # SQLite DB（Docker volume 掛載）
├── public/                      # 舊版前端（保留直到遷移完成）
└── REFACTOR_PLAN.md             # 本文件
```

## 現有功能清單（必須全部遷移）

### 五種視覺化模式
1. **密度熱區 (density)** → deck.gl ScreenGridLayer
2. **軌跡動畫 (trajectory)** → deck.gl TripsLayer + ScatterplotLayer
3. **六角網格 (hexbin)** → deck.gl HexagonLayer
4. **KDE 熱力圖 (heatmap)** → deck.gl HeatmapLayer
5. **軌跡查詢 (query)** → deck.gl PathLayer + ScatterplotLayer + API

### 互動功能
- 播放/暫停 + 速度控制 (1x/2x/4x/8x)
- 時間軸 slider 拖曳（即時更新）
- 鍵盤快捷鍵（Space=播放, ←→=切幀）
- 10 種船舶類型 checkbox 篩選
- 日間/夜間主題切換（底圖 + 色彩）
- 地圖縮放/平移
- 軌跡查詢：點選單船 / 矩形圈選多船
- 查詢結果側邊面板（船舶卡片）
- 統計面板（時間、船舶數、密度等）
- 各模式圖例
- 載入動畫遮罩

### 色彩系統
- 速度色彩：<5=深藍, 5-10=紫, 10-15=橙, >15=深紅
- 密度色彩：7 級漸層（淡綠→深紅）
- 日間主題：暖色系
- 夜間主題：冷色系（深紫→亮黃）

---

## 實作步驟

### Step 1：Vite + MapLibre 基礎建設
**目標**：建立新的前端專案，MapLibre 地圖可正常顯示

- [ ] 在 `frontend/` 建立 Vite 專案（vanilla JS template）
- [ ] 安裝依賴：maplibre-gl, deck.gl 相關套件, apache-arrow
- [ ] 建立 `src/map.js`：MapLibre 初始化，中心 [24.5, 121.5]，zoom 7
- [ ] 建立 `src/utils/constants.js`：從舊 index.html 提取常數
- [ ] 建立 `src/controls/theme.js`：日夜間底圖切換（CARTO Positron / Dark Matter）
- [ ] 建立基本 `index.html`：地圖全屏 + 主題切換按鈕
- [ ] 驗證地圖可正常顯示、切換主題

### Step 2：資料載入 + Arrow 格式產出
**目標**：後端能產出 Arrow 格式，前端能載入

- [ ] 新增 `scripts/generate_arrow.py`：SQLite → Arrow IPC 檔案
  - trajectory.arrow：每艘船的完整軌跡（按 MMSI 分組，含時間戳）
  - density.arrow：每幀所有船舶位置
- [ ] 建立 `src/data/loader.js`：fetch Arrow 檔案 + tableFromIPC 解析
- [ ] 建立 `src/data/transform.js`：Arrow Table → deck.gl 所需的資料結構
  - TripsLayer 需要：[{path: [[lon,lat,ts],...], mmsi, vessel_type}, ...]
  - 其他 Layer 需要：[{position: [lon,lat], properties...}, ...]
- [ ] 加入 JSON fallback：Arrow 載入失敗時退回 JSON
- [ ] 驗證資料載入正常，console 印出資料統計

### Step 3：軌跡動畫（TripsLayer）— 核心功能
**目標**：船舶軌跡可播放、時間軸可拖曳

- [ ] 建立 `src/layers/trips.js`：
  - TripsLayer 配置（trailLength, getColor by speed, getWidth）
  - ScatterplotLayer 顯示船頭位置（當前時間點的船舶）
- [ ] 建立 `src/controls/timeline.js`：
  - slider 綁定 TripsLayer.currentTime
  - 播放/暫停按鈕 + rAF 驅動 currentTime 遞增
  - 速度控制 (1x/2x/4x/8x)
  - 時間顯示（將 currentTime 轉為人類可讀時間）
  - 鍵盤快捷鍵 (Space, ←, →)
- [ ] 建立 `src/utils/colors.js`：速度色彩映射
- [ ] 整合 MapboxOverlay 到 MapLibre map
- [ ] 驗證：播放流暢、拖曳即時、速度切換正常

### Step 4：其他視覺化模式
**目標**：完成全部五種模式

- [ ] 建立 `src/layers/grid.js`：ScreenGridLayer（密度熱區）
  - 從 density Arrow 提取當前時間幀的船舶位置
  - 色彩映射（7 級密度色）
- [ ] 建立 `src/layers/hexagon.js`：HexagonLayer（六角網格）
  - GPU 端聚合（不需前端計算 hex bin）
  - 高度/色彩映射
- [ ] 建立 `src/layers/heatmap.js`：HeatmapLayer（KDE 熱力圖）
  - 權重、半徑、色帶配置
- [ ] 建立 `src/layers/path.js`：PathLayer（查詢模式）
  - 單船軌跡：綠起點→紅終點
  - 多船軌跡：HSL 色相漸變
- [ ] 建立模式切換機制（tab 按鈕 → 切換 deck.gl layers）
- [ ] 為每種模式建立對應的時間幀資料提取邏輯
- [ ] 驗證：所有模式渲染正確、切換流暢

### Step 5：UI 控件遷移
**目標**：所有互動功能完整遷移

- [ ] 建立 `src/controls/filters.js`：
  - 10 種船舶類型 checkbox
  - 全選/取消全選按鈕
  - 篩選邏輯：更新 deck.gl layer 的 data / filterRange
- [ ] 建立 `src/controls/query.js`：
  - 點選模式：deck.gl picking → API 查詢
  - 矩形圈選：自訂拖曳 → API 查詢
  - 結果卡片面板
- [ ] 建立 `src/ui/panels.js`：
  - 狀態面板（模式名、時間、船舶數、密度等統計）
  - 載入動畫遮罩
- [ ] 建立 `src/ui/legends.js`：各模式圖例
- [ ] 遷移 CSS 樣式（日間/夜間主題、響應式佈局）
- [ ] 驗證：所有 UI 功能完整可用

### Step 6：後端強化 + API 擴充
**目標**：FastAPI 支援 Arrow 資料供給 + 優化查詢

- [ ] 新增 `api/arrow_export.py`：
  - GET /data/trajectory.arrow → 靜態檔案服務
  - GET /data/density.arrow → 靜態檔案服務
- [ ] 優化資料庫：
  - 加複合索引 (ts_unix, lon, lat)
  - 加唯一索引 (mmsi, ts_unix) 解決去重
- [ ] 優化現有 API：
  - /api/ships/latest 加分頁
  - /api/ships/tracks 改用 JOIN 批次查詢
- [ ] 新增 `api/db.py`：連線池管理
- [ ] 驗證：API 效能提升、Arrow 檔案可正常取得

### Step 7：Docker 容器化
**目標**：一鍵部署完整服務

- [ ] 建立 `docker/Dockerfile.frontend`：
  - Vite build → Nginx 服務靜態檔案
  - Nginx 設定：/api/* 反向代理到 api 容器
- [ ] 建立 `docker/Dockerfile.api`：
  - FastAPI + uvicorn
  - 掛載 data volume
- [ ] 建立 `docker/Dockerfile.scheduler`：
  - cron 每 10 分鐘執行 import_to_db.py + generate_arrow.py
  - 掛載 data volume（與 api 共用）
- [ ] 建立 `docker-compose.yml`：
  - 3 個服務 + 2 個 volumes（db-data, arrow-data）
  - 環境變數管理（S3 credentials）
- [ ] 驗證：docker-compose up 可啟動全部服務
- [ ] 更新 README.md

---

## 關鍵技術決策

1. **不引入 React/Vue**：Vanilla JS + Vite 足夠，避免過度工程化
2. **保留 JSON fallback**：Arrow 載入失敗時可退回 JSON，確保可用性
3. **保留舊版 public/**：遷移完成前舊版可繼續使用
4. **TripsLayer 為核心**：其 currentTime 機制是實現流暢拖曳的關鍵
5. **Arrow 零拷貝**：避免 JSON.parse 的主線程阻塞和 GC 暫停

## 參考資源

- deck.gl TripsLayer: https://deck.gl/docs/api-reference/geo-layers/trips-layer
- deck.gl + MapLibre: https://deck.gl/docs/developer-guide/base-maps/using-with-maplibre
- deck.gl Standalone: https://deck.gl/docs/get-started/using-standalone
- Apache Arrow JS: https://arrow.apache.org/docs/js/
- MapLibre GL JS: https://maplibre.org/maplibre-gl-js/docs/
- CARTO 免費底圖: https://github.com/CartoDB/basemap-styles
