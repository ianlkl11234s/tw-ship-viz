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
├── zeabur.json          # Zeabur 部署配置
├── .env.example         # 環境變數範例
├── scripts/
│   ├── requirements.txt # Python 相依套件
│   ├── update_data.py   # 資料處理主程式
│   ├── grid_utils.py    # 格網計算工具
│   └── vessel_types.py  # 船舶類型定義
└── public/
    ├── index.html       # 前端 SPA
    └── ship_density_data.json  # 密度資料
```

## 格網設定

| 參數 | 值 |
|------|-----|
| 範圍 | 117°E - 127°E, 20°N - 28°N |
| 解析度 | 0.05° (~5.5km) |
| 格網 | 200 x 160 = 32,000 格 |

## 使用方式

### 1. 安裝相依套件

```bash
cd scripts
pip3 install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env 填入 S3 設定
```

### 3. 產生資料

```bash
# 預設 7 天
python3 scripts/update_data.py

# 指定天數
python3 scripts/update_data.py --days 3

# 指定日期範圍
python3 scripts/update_data.py --start-date 2025-01-10 --end-date 2025-01-15

# 過濾船舶類型
python3 scripts/update_data.py --vessel-type cargo
```

### 4. 本地測試

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
