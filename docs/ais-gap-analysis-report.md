# AIS 資料 Gap 分析報告與軌跡顯示改進方案

> 分析日期：2026-02-15
> 資料範圍：2026-02-03 ~ 2026-02-15（約 12 天）
> 資料庫：~7.3M 筆 AIS 紀錄，涵蓋 500+ 艘船

---

## 一、問題描述

目前前端軌跡顯示有兩個核心問題：

1. **假直線問題**：當 AIS 資料有時間斷裂（gap）時，系統會把隔了數小時甚至數天的兩個點直接連線，產生穿越海面的假直線
2. **船舶聚集問題**：移除時間限制後，長時間無更新的船舶點會停留在最後已知位置，造成不自然的聚集（如港口附近、漁場附近）

### 原先嘗試的方案及其缺陷

- **停止 8 小時以上消失**：會讓大量正常船隻突然消失（因為 96% 的 gap 發生在船還在移動中，不是停泊後消失），或從奇怪的地方突然冒出來
- **不做任何處理**：船會不自然地聚集在最後位置

---

## 二、全域 Gap 統計分析

### 分析範圍
- 取資料量前 200 艘船，共找到 **365 個超過 2 小時的 gap**

### Gap 時長分布

| 時長區間 | 數量 | 佔比 |
|---------|------|------|
| 2~4 hr  | 241  | 66.0% |
| 4~8 hr  | 81   | 22.2% |
| 8~24 hr | 42   | 11.5% |
| 24~48 hr| 1    | 0.3%  |
| > 48 hr | 0    | 0.0%  |

- 中位數：3.2 小時
- P75：5.0 小時
- P90：9.0 小時

### Gap 前船舶狀態

| 狀態 | 佔比 |
|------|------|
| 停泊中消失（sog < 0.5 kn） | **3.8%** |
| 慢速移動中消失（0.5 ≤ sog < 3 kn） | **64.1%** |
| 航行中消失（sog ≥ 3 kn） | **32.1%** |

**關鍵發現：96.2% 的 gap 發生在船還在移動中**，主因是 AIS 訊號收不到（通訊盲區、取樣遺漏），而非船停泊後關閉 AIS。

### Gap 後船舶狀態

| 狀態 | 佔比 |
|------|------|
| 停泊中出現（sog < 0.5 kn） | 9.9% |
| 慢速移動中出現（0.5 ≤ sog < 3 kn） | 58.1% |
| 航行中出現（sog ≥ 3 kn） | 32.1% |

### Gap 前後位移

| 位移範圍 | 佔比 |
|---------|------|
| < 0.5 km（原地） | **54.0%** |
| 0.5 ~ 5 km | 36.2% |
| 5 ~ 20 km | 6.0% |
| 20 ~ 100 km | 3.6% |
| > 100 km | 0.3% |

- 中位數位移：0.3 km

### 行為模式交叉分析

| 模式 | 佔比 | 說明 |
|------|------|------|
| 移動中消失 → 原地出現 | **50.7%** | 訊號暫時中斷，船沒動太遠 |
| 移動中消失 → 異地出現 | **45.5%** | 航行中訊號中斷，船繼續移動 |
| 停泊後消失 → 原地出現 | 3.3% | 傳統的港內停泊 gap |
| 停泊後消失 → 異地出現 | 0.5% | 極少見 |

---

## 三、個案分析（8 艘船）

### 正常船舶

| MMSI | 船籍 | 類型 | 筆數 | 行為 | 判定 |
|------|------|------|------|------|------|
| 416068556 | 台灣 | 漁船(30) | 118 | 布袋港日間近海作業，每天 05:00-10:00 | ✅ 正常 |
| 416005736 | 台灣 | 漁船(30) | 946 | 高雄母港，澎湖西南漁場拖網作業 | ✅ 正常 |
| 416005833 | 台灣 | 漁船(30) | 885 | 高雄前鎮漁港，澎湖水道延繩釣/拖網 | ✅ 正常 |
| 416014785 | 台灣 | 遊艇類(37) | 115 | 澎湖馬公港，高速巡航（max 33 kn） | ✅ 正常 |

**正常船舶共同特徵：**
- 有明確母港（gap 前 sog=0，gap 後同位置 sog=0）
- 資料密度合理（每天 10+ 筆以上）
- vessel_type 有正確申報
- 台灣船籍（MMSI 416）

### 值得關注的船舶

| MMSI | 船籍 | 類型 | 筆數 | 行為 | 判定 |
|------|------|------|------|------|------|
| 252100233 | 盧森堡 | 未知(0) | 38/7.7天 | 海峽南段低速作業，消失 5.5 天 | ⚠️ 關注 |
| 252100235 | 盧森堡 | 未知(0) | 83/8天 | 同上海域，消失 4.8 天 | ⚠️ 關注 |
| 253101833 | 盧森堡 | 未知(0) | 79/7.3天 | 同上海域，消失 5 天 | ⚠️ 關注 |
| 251400737 | 冰島 | 未知(0) | 33/5天 | 海峽中線附近，從未停泊 | ⚠️⚠️ 可疑 |
| 585866888 | 孟加拉 | 漁船(30) | 96/10.8天 | 從未停泊，AIS 覆蓋率僅 6.1%，疑似關閉 AIS | ⚠️⚠️⚠️ 高度可疑 |

**可疑船舶共同特徵：**
- 外國船籍（盧森堡/冰島/孟加拉），可能為權宜旗或偽造 MMSI
- vessel_type = 0（未申報）
- AIS 訊號極度稀疏（每天 < 15 筆）
- 從未停泊（sog 最低也有 0.5~0.8 kn）
- 多艘盧森堡籍船同時段同海域活動，疑似同一船隊
- 消失數天後在反方向出現

**盧森堡籍船群體行為：**
- 252100233、252100235、253101833 三艘船 + 251400737（冰島）在同一海域（118.6°~119.5°E）
- 同時段消失（02/06~02/10，約 5 天）
- 消失後同方向航行（COG ~40°, 7~9 kn, 朝東北）

---

## 四、軌跡顯示改進方案

### 4.1 設計目標

1. 消除假直線（gap 造成的不合理連線）
2. 船消失時不要留殘影在地圖上聚集
3. 船重新出現時有合理的過渡（不要突然冒出來）
4. 點選船舶顯示完整軌跡時，能區分「實際資料」和「推測航段」

### 4.2 航段切割規則

將每艘船的連續軌跡切成多個**航段（segment）**，依據相鄰兩點的時間差：

```
gap < 30 min    → 同一航段，正常連線（實線）
30 min ≤ gap < 4 hr  → 同一航段，正常連線（資料可能有少量遺漏但合理）
4 hr ≤ gap < 8 hr    → 視為推測航段（虛線連接，表示路徑不確定）
gap ≥ 8 hr     → 切成不同航段（完全不連線）
```

**為什麼選這些閾值：**
- 66% 的 gap 在 2~4 hr → 4hr 以下大多是正常訊號間歇
- P90 = 9 hr → 8hr 以上是明確的長時間中斷
- 中間的 4~8 hr 用虛線過渡

### 4.3 軌跡動畫模式（全域檢視）的行為

#### 當前行為
- 每艘船有一個移動的點，用 `getShipPositionsAtTime()` 做時間插值
- 船後方有 1 小時的尾跡（TripsLayer）
- 問題：gap 期間船會沿著假直線緩慢移動

#### 改進後行為

**Gap 期間（船消失）：**

```
1. gap < 4 hr：
   - 船頭點維持在 gap 前最後一個已知位置
   - 尾跡正常消散
   - 效果：船看起來像是暫停不動

2. 4 hr ≤ gap < 8 hr：
   - 船頭點在 gap 開始後逐漸淡出（alpha 從 255 降到 0，耗時 30 分鐘）
   - 在 gap 結束前 1 小時，船頭點在「下一段的起點」逐漸淡入
   - 效果：船消失一段時間後，在新位置浮現

3. gap ≥ 8 hr：
   - 船頭點在 gap 開始後 30 分鐘內完全淡出消失
   - 在 gap 結束前 1 小時，船頭點在「下一段的起點」逐漸淡入
   - 效果：長 gap 期間船完全消失，接近新航段時才重新出現
```

**虛擬碼邏輯：**

```javascript
function getShipVisibility(trip, currentTime) {
  // 找到 currentTime 落在哪個 gap 中
  const gapInfo = findGap(trip, currentTime);

  if (!gapInfo) {
    // 不在 gap 中，正常顯示
    return { visible: true, alpha: 255, position: interpolate(trip, currentTime) };
  }

  const { gapStart, gapEnd, gapDuration, nextSegmentStart } = gapInfo;
  const timeIntoGap = currentTime - gapStart;
  const timeBeforeResume = gapEnd - currentTime;

  if (gapDuration < 4 * 3600) {
    // 短 gap：停在最後位置
    return { visible: true, alpha: 255, position: gapInfo.lastKnownPosition };
  }

  // 中/長 gap
  const FADE_OUT_SEC = 30 * 60;   // 30 分鐘淡出
  const FADE_IN_SEC = 60 * 60;    // 1 小時前淡入

  if (timeIntoGap < FADE_OUT_SEC) {
    // 正在淡出
    const alpha = 255 * (1 - timeIntoGap / FADE_OUT_SEC);
    return { visible: true, alpha, position: gapInfo.lastKnownPosition };
  }

  if (timeBeforeResume < FADE_IN_SEC) {
    // 即將恢復，開始淡入（在下一段起點位置）
    const alpha = 255 * (1 - timeBeforeResume / FADE_IN_SEC);
    return { visible: true, alpha, position: nextSegmentStart };
  }

  // gap 中間：完全不顯示
  return { visible: false };
}
```

### 4.4 選中船舶軌跡顯示（點選後的完整軌跡）

#### 當前行為
- 點選船舶後，用 `createSelectedShipTrajectoryLayers()` 畫出完整軌跡
- 使用 deck.gl `PathLayer` 畫一條連續線
- 問題：gap 部分也被畫成實線

#### 改進後行為

把一艘船的軌跡拆成多條 path，分三種樣式：

```
1. 實線段（solid）：gap < 4 hr 的連續航段
   - 用現有的橙色實線
   - 這是確定的軌跡

2. 虛線段（dashed）：4 hr ≤ gap < 8 hr 的推測航段
   - 用半透明的同色虛線
   - 只連接 gap 前最後一點和 gap 後第一點
   - 表示「船可能走過這段路，但不確定」

3. 不連線：gap ≥ 8 hr
   - 完全不連接
   - 兩段之間有明顯的視覺斷裂
   - 起終點標記可以標示不同顏色（例如紅=結束，綠=開始）
```

**資料結構改動：**

```javascript
// 原本：一艘船 = 一條 path
{ mmsi, path: [[lng,lat], ...], timestamps: [...] }

// 改後：一艘船 = 多條 segment
{
  mmsi,
  segments: [
    {
      path: [[lng,lat], ...],
      timestamps: [...],
      type: 'solid'     // 確定航段
    },
    {
      path: [[gapStart], [gapEnd]],  // 只有兩個點
      timestamps: [t1, t2],
      type: 'dashed'    // 推測航段（4~8hr gap）
    },
    {
      path: [[lng,lat], ...],
      timestamps: [...],
      type: 'solid'
    }
    // gap ≥ 8hr 時，不產生 dashed segment，直接斷開
  ]
}
```

**渲染方式：**

```javascript
// 實線段：一般 PathLayer
new PathLayer({
  id: 'selected-trajectory-solid',
  data: segments.filter(s => s.type === 'solid'),
  getPath: d => d.path,
  getColor: SELECTION_COLORS[theme].trajectory,
  widthMinPixels: 2,
});

// 虛線段：使用 PathLayer + getDashArray
new PathLayer({
  id: 'selected-trajectory-dashed',
  data: segments.filter(s => s.type === 'dashed'),
  getPath: d => d.path,
  getColor: [...SELECTION_COLORS[theme].trajectory.slice(0,3), 128], // 半透明
  widthMinPixels: 2,
  getDashArray: [8, 4],       // 虛線：8px 實線 + 4px 空白
  dashJustified: true,
  extensions: [new PathStyleExtension({ dash: true })],
});
```

### 4.5 需要修改的檔案

| 檔案 | 修改內容 |
|------|---------|
| `frontend/src/layers/trips.js` | 1. `preprocessTrips()` 加入航段切割邏輯<br>2. `getShipPositionsAtTime()` 加入 gap 期間的淡入淡出<br>3. `createSelectedShipTrajectoryLayers()` 改為分段渲染（實線+虛線） |
| `frontend/src/utils/constants.js` | 新增常數：`GAP_THRESHOLD_MEDIUM = 4 * 3600`（4hr）、`GAP_THRESHOLD_LONG = 8 * 3600`（8hr）、`FADE_OUT_SEC = 30 * 60`、`FADE_IN_SEC = 60 * 60` |
| `frontend/src/main.js` | 可能需要微調 `updateLayers()` 以支援新的 segment 結構 |

### 4.6 航段切割演算法

```javascript
/**
 * 將一艘船的軌跡切割成多個航段
 * @param {Object} trip - { path, timestamps, mmsi, vesselType, ... }
 * @returns {Object} - { ...trip, segments: [...] }
 */
function segmentTrip(trip) {
  const segments = [];
  let currentSegment = {
    path: [trip.path[0]],
    timestamps: [trip.timestamps[0]],
    type: 'solid'
  };

  for (let i = 1; i < trip.path.length; i++) {
    const dt = trip.timestamps[i] - trip.timestamps[i - 1]; // 秒

    if (dt < GAP_THRESHOLD_MEDIUM) {
      // < 4hr：同一航段
      currentSegment.path.push(trip.path[i]);
      currentSegment.timestamps.push(trip.timestamps[i]);

    } else if (dt < GAP_THRESHOLD_LONG) {
      // 4~8hr：結束當前航段，插入虛線段
      segments.push(currentSegment);

      // 虛線段：前一段最後一點 → 新一段第一點
      segments.push({
        path: [trip.path[i - 1], trip.path[i]],
        timestamps: [trip.timestamps[i - 1], trip.timestamps[i]],
        type: 'dashed'
      });

      // 開始新航段
      currentSegment = {
        path: [trip.path[i]],
        timestamps: [trip.timestamps[i]],
        type: 'solid'
      };

    } else {
      // ≥ 8hr：結束當前航段，不連線
      segments.push(currentSegment);

      // 開始新航段（完全斷開）
      currentSegment = {
        path: [trip.path[i]],
        timestamps: [trip.timestamps[i]],
        type: 'solid'
      };
    }
  }

  // 推入最後一個航段
  segments.push(currentSegment);

  return { ...trip, segments };
}
```

### 4.7 船頭位置計算（含 gap 處理）

```javascript
/**
 * 計算船舶在 currentTime 的顯示位置和透明度
 * 替換原本的 getShipPositionsAtTime 中對單艘船的邏輯
 */
function getShipDisplayState(trip, currentTime) {
  const { timestamps, path, segments } = trip;

  // 找到 currentTime 在哪兩個資料點之間
  const idx = binarySearch(timestamps, currentTime);

  if (idx < 0 || idx >= timestamps.length - 1) {
    // 超出資料範圍
    if (currentTime < timestamps[0]) return null;
    if (currentTime > timestamps[timestamps.length - 1]) {
      // 超過最後一筆，30 分鐘後消失
      const elapsed = currentTime - timestamps[timestamps.length - 1];
      if (elapsed > FADE_OUT_SEC) return null;
      return {
        position: path[path.length - 1],
        alpha: 255 * (1 - elapsed / FADE_OUT_SEC)
      };
    }
  }

  const dt = timestamps[idx + 1] - timestamps[idx];

  if (dt < GAP_THRESHOLD_MEDIUM) {
    // 正常間隔：線性插值
    const ratio = (currentTime - timestamps[idx]) / dt;
    return {
      position: lerpPosition(path[idx], path[idx + 1], ratio),
      alpha: 255
    };
  }

  // 在 gap 中
  const timeIntoGap = currentTime - timestamps[idx];
  const timeBeforeResume = timestamps[idx + 1] - currentTime;

  if (dt < GAP_THRESHOLD_LONG) {
    // 4~8hr 中等 gap
    if (timeIntoGap < FADE_OUT_SEC) {
      // 淡出中，停在最後位置
      return {
        position: path[idx],
        alpha: 255 * (1 - timeIntoGap / FADE_OUT_SEC)
      };
    }
    if (timeBeforeResume < FADE_IN_SEC) {
      // 1hr 前淡入，出現在下一段起點
      return {
        position: path[idx + 1],
        alpha: 255 * (1 - timeBeforeResume / FADE_IN_SEC)
      };
    }
    // 中間：不顯示
    return null;
  }

  // ≥ 8hr 長 gap
  if (timeIntoGap < FADE_OUT_SEC) {
    return {
      position: path[idx],
      alpha: 255 * (1 - timeIntoGap / FADE_OUT_SEC)
    };
  }
  if (timeBeforeResume < FADE_IN_SEC) {
    return {
      position: path[idx + 1],
      alpha: 255 * (1 - timeBeforeResume / FADE_IN_SEC)
    };
  }
  return null;
}
```

---

## 五、未來可擴充：全量異常偵測

可以寫一個 Python 腳本對所有船隻自動分類：

| 類別 | 判斷條件 |
|------|---------|
| ✅ 正常港口船 | 有 sog=0 停泊段、有明確母港位置、gap 前後在同位置 |
| ⚠️ 訊號不佳 | 資料稀疏（< 15 筆/天）但行為模式合理 |
| ⚠️⚠️ 值得關注 | 外籍 + vessel_type=0 + 訊號稀疏 |
| ⚠️⚠️⚠️ 高度可疑 | 從未停泊 + AIS 覆蓋率 < 10% + 異常路線 |

可選指標：
- `has_port`：是否有 sog < 0.5 且持續 > 30 min 的停泊段
- `data_density`：每天平均筆數
- `max_gap_hours`：最大 gap 時長
- `ais_coverage`：有效資料時間 / 總跨度
- `foreign_flag`：非 416（台灣）船籍
- `vessel_type_declared`：是否有申報 vessel_type
