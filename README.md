# 台灣海域船舶密度熱區圖

顯示台灣周邊海域的船舶密度分布，資料來源為航港局 AIS 系統。

## 功能

- 7 天船舶密度時間序列動畫
- 互動式地圖（可縮放、平移）
- 播放/暫停、速度控制（1x/2x/4x）
- 時間軸拖曳
- 船舶類型過濾

## 專案結構

```
ship-gis/
├── zeabur.json              # Zeabur 部署配置
├── .env.example             # 環境變數範例
├── data/
│   └── ship_data.db         # SQLite 資料庫（永久累積）
├── scripts/
│   ├── requirements.txt     # Python 相依套件
│   ├── import_to_db.py      # S3 → SQLite 匯入
│   ├── generate_json.py     # SQLite → JSON 產出
│   ├── update_all.py        # 舊版：直接從 S3 產 JSON
│   ├── grid_utils.py        # 格網計算工具
│   └── vessel_types.py      # 船舶類型定義
└── public/
    ├── index.html                  # 前端 SPA
    ├── ship_density_data.json      # 密度資料
    └── ship_trajectory_data.json   # 軌跡資料
```

## 資料更新

架構：`S3 → SQLite（永久累積）→ JSON（按需產生）`

### 安裝

```bash
pip3 install -r scripts/requirements.txt
cp .env.example .env
# 編輯 .env 填入 S3 設定
```

### 日常更新（一行搞定）

```bash
python3 scripts/import_to_db.py --incremental && python3 scripts/generate_json.py --days 7
```

這會：
1. 增量匯入 S3 新資料到 SQLite（只拉上次之後的）
2. 從 SQLite 產出最近 7 天的 JSON 供前端使用

### 進階用法

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

### 本地測試

```bash
cd public
python3 -m http.server 8000
# 瀏覽 http://localhost:8000
```

## 部署

推送至 GitHub 後，Zeabur 會自動部署 `public/` 目錄。

## 船舶類型

- `all`: 所有船舶
- `fishing`: 漁船
- `cargo`: 貨船
- `tanker`: 油輪
- `passenger`: 客輪
- `tug`: 拖船
- `military`: 軍艦
- `sailing`: 帆船/遊艇
- `service`: 服務船舶
- `highspeed`: 高速船
