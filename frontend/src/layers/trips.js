/**
 * 軌跡動畫 Layer
 * 使用 deck.gl TripsLayer 渲染船舶軌跡 + ScatterplotLayer 渲染船頭位置。
 */
import { TripsLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer, PathLayer } from '@deck.gl/layers';
import { PathStyleExtension } from '@deck.gl/extensions';
import { getSpeedColorByPalette, SELECTION_COLORS, GAP_THRESHOLDS } from '../utils/constants.js';

/**
 * 建立軌跡動畫的 deck.gl layers。
 *
 * data 應由呼叫端預先篩選並快取，確保同一篩選條件下引用不變，
 * 讓 deck.gl 只更新 currentTime uniform 而不重建 GPU buffer。
 *
 * @param {Array} data - 已篩選的 trips 資料（引用穩定）
 * @param {number} currentTime - 當前時間（秒，相對 base_timestamp）
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createTrajectoryLayers(data, currentTime, theme = 'day') {
  const tripsLayer = new TripsLayer({
    id: 'trips-layer',
    data,
    getPath: d => d.path,
    getTimestamps: d => d.timestamps,
    getColor: d => d._color,
    getWidth: 2,
    widthMinPixels: 2,
    widthMaxPixels: 4,
    trailLength: 1800,
    currentTime,
    opacity: 0.8,
    rounded: true,
  });

  // 船頭位置（ScatterplotLayer）：顯示在 currentTime 時刻活躍的船舶
  const shipPositions = getShipPositionsAtTime(data, currentTime);

  const scatterLayer = new ScatterplotLayer({
    id: 'ship-positions-layer',
    data: shipPositions,
    getPosition: d => d.position,
    getFillColor: d => d.color,
    getRadius: 3,
    radiusMinPixels: 3,
    radiusMaxPixels: 6,
    radiusUnits: 'pixels',
    opacity: 0.95,
    pickable: true,
  });

  return [tripsLayer, scatterLayer];
}

/**
 * 根據 currentTime 用二分搜尋計算每艘船的插值位置。
 */
export function getShipPositionsAtTime(tripsData, currentTime) {
  const positions = [];

  for (const trip of tripsData) {
    const { timestamps, path, mmsi, vesselType, avgSog, _dotColor } = trip;
    const len = timestamps.length;
    if (len === 0) continue;

    if (currentTime < timestamps[0] || currentTime > timestamps[len - 1] + 600) {
      continue;
    }

    // 二分搜尋：找最後一個 <= currentTime 的索引
    let lo = 0, hi = len - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >>> 1;
      if (timestamps[mid] <= currentTime) lo = mid;
      else hi = mid - 1;
    }
    const idx = lo;

    if (idx >= len - 1) {
      // 在最後一個點附近（10 分鐘內）
      if (currentTime - timestamps[len - 1] < 600) {
        positions.push({
          position: path[len - 1],
          mmsi,
          vesselType,
          avgSog,
          color: _dotColor,
        });
      }
      continue;
    }

    // 線性插值
    const t0 = timestamps[idx];
    const t1 = timestamps[idx + 1];
    const ratio = (t1 > t0) ? (currentTime - t0) / (t1 - t0) : 0;
    const p0 = path[idx];
    const p1 = path[idx + 1];

    positions.push({
      position: [p0[0] + (p1[0] - p0[0]) * ratio, p0[1] + (p1[1] - p0[1]) * ratio],
      mmsi,
      vesselType,
      avgSog,
      color: _dotColor,
    });
  }

  return positions;
}

/**
 * 預處理 trips 資料：計算平均速度 + 預烘焙顏色。
 * 在資料載入後呼叫一次，避免每幀重複計算。
 */
export function preprocessTrips(tripsData, arrowTable) {
  if (!arrowTable) {
    // 無 Arrow 表時用預設顏色
    for (const trip of tripsData) {
      trip.avgSog = 5;
      _bakeColors(trip, 'day', 'speed');
    }
    return tripsData;
  }

  const sogCol = arrowTable.getChild('sog');
  const mmsiCol = arrowTable.getChild('mmsi');
  if (!sogCol || !mmsiCol) return tripsData;

  // 計算每艘船的平均 SOG
  const sogSums = new Map();
  const sogCounts = new Map();
  const numRows = arrowTable.numRows;
  for (let i = 0; i < numRows; i++) {
    const mmsi = mmsiCol.get(i);
    const sog = sogCol.get(i);
    sogSums.set(mmsi, (sogSums.get(mmsi) || 0) + sog);
    sogCounts.set(mmsi, (sogCounts.get(mmsi) || 0) + 1);
  }

  for (const trip of tripsData) {
    const sum = sogSums.get(trip.mmsi) || 0;
    const count = sogCounts.get(trip.mmsi) || 1;
    trip.avgSog = sum / count;
  }

  // Gap-aware 拆分：在 4hr+ gap 處把 trip 切成子段
  const beforeCount = tripsData.length;
  const splitResult = splitTripsAtGaps(tripsData);
  tripsData.length = 0;                        // 原地清空
  for (let i = 0; i < splitResult.length; i++) // 逐一填入（避免 spread 超過 call stack）
    tripsData[i] = splitResult[i];
  console.log(`[trips] gap 拆分: ${beforeCount} → ${tripsData.length} 子段`);

  // 預烘焙顏色（初始用 day 主題，切換時會重新烘焙）
  bakeAllColors(tripsData, 'day', 'speed');

  return tripsData;
}

/**
 * 為所有 trips 預烘焙顏色。主題或配色切換時呼叫。
 */
export function bakeAllColors(tripsData, theme, palette = 'speed') {
  for (const trip of tripsData) {
    _bakeColors(trip, theme, palette);
  }
}

function _bakeColors(trip, theme, palette) {
  const rgb = getSpeedColorByPalette(trip.avgSog || 5, theme, palette);
  const alpha = trip.path.length < 6 ? 120 : 200;
  trip._color = [rgb[0], rgb[1], rgb[2], alpha];
  trip._dotColor = [rgb[0], rgb[1], rgb[2], 240];
}

/**
 * 在時間 gap >= NORMAL_MAX 處把 trip 拆分為子段。
 * 子段繼承 mmsi/vesselType/avgSog，並標記 _gapAfter。
 * @returns {Array} 展開後的子段陣列
 */
function splitTripsAtGaps(tripsData) {
  const { NORMAL_MAX, INFERRED_MAX } = GAP_THRESHOLDS;
  const result = [];

  for (const trip of tripsData) {
    const { timestamps, path, mmsi, vesselType, avgSog } = trip;
    if (timestamps.length < 2) {
      trip._gapAfter = null;
      result.push(trip);
      continue;
    }

    // 找出所有 gap 位置（索引）
    const gapIndices = [];
    for (let i = 0; i < timestamps.length - 1; i++) {
      const dt = timestamps[i + 1] - timestamps[i];
      if (dt >= NORMAL_MAX) {
        gapIndices.push({ idx: i, dt });
      }
    }

    if (gapIndices.length === 0) {
      trip._gapAfter = null;
      result.push(trip);
      continue;
    }

    // 拆分
    let start = 0;
    for (let g = 0; g < gapIndices.length; g++) {
      const { idx, dt } = gapIndices[g];
      const end = idx + 1; // slice 不含 end，所以子段包含 idx
      const segment = {
        mmsi,
        vesselType,
        avgSog,
        path: path.slice(start, end),
        timestamps: timestamps.slice(start, end),
        _gapAfter: dt < INFERRED_MAX ? 'inferred' : 'disconnected',
      };
      result.push(segment);
      start = end;
    }

    // 最後一段
    if (start < timestamps.length) {
      result.push({
        mmsi,
        vesselType,
        avgSog,
        path: path.slice(start),
        timestamps: timestamps.slice(start),
        _gapAfter: null,
      });
    }
  }

  return result;
}

/**
 * 根據 MMSI 查詢船舶在 currentTime 的插值位置。
 * @returns {{ position: [number, number], trip: object } | null}
 */
export function getShipPositionByMmsi(mmsi, tripsData, currentTime) {
  for (const trip of tripsData) {
    if (trip.mmsi !== mmsi) continue;
    const { timestamps, path } = trip;
    const len = timestamps.length;
    if (len === 0) continue;
    if (currentTime < timestamps[0] || currentTime > timestamps[len - 1] + 600) continue;

    let lo = 0, hi = len - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >>> 1;
      if (timestamps[mid] <= currentTime) lo = mid;
      else hi = mid - 1;
    }
    const idx = lo;

    if (idx >= len - 1) {
      if (currentTime - timestamps[len - 1] < 600) {
        return { position: path[len - 1], trip };
      }
      continue;
    }

    const t0 = timestamps[idx];
    const t1 = timestamps[idx + 1];
    const ratio = (t1 > t0) ? (currentTime - t0) / (t1 - t0) : 0;
    const p0 = path[idx];
    const p1 = path[idx + 1];
    return {
      position: [p0[0] + (p1[0] - p0[0]) * ratio, p0[1] + (p1[1] - p0[1]) * ratio],
      trip,
    };
  }
  return null;
}

/**
 * 建立選中船舶的高亮光暈 Layer。
 */
export function createShipHighlightLayer(shipInfo, tripsData, currentTime, theme = 'day') {
  if (!shipInfo) return null;
  const result = getShipPositionByMmsi(shipInfo.mmsi, tripsData, currentTime);
  if (!result) return null;

  const colors = SELECTION_COLORS[theme] || SELECTION_COLORS.day;
  return new ScatterplotLayer({
    id: 'ship-highlight-layer',
    data: [{ position: result.position }],
    getPosition: d => d.position,
    getFillColor: colors.highlight,
    getLineColor: colors.stroke,
    getRadius: 15,
    radiusMinPixels: 15,
    radiusMaxPixels: 20,
    radiusUnits: 'pixels',
    stroked: true,
    lineWidthMinPixels: 2,
    opacity: 1,
    pickable: false,
  });
}

/**
 * 建立選中船舶的完整軌跡 Layers：
 * 1. 實線 PathLayer — 每個子段內部路徑
 * 2. 虛線 PathLayer — inferred gap（4-8hr）的連接線
 * 3. ScatterplotLayer — 每段起點（綠）/ 終點（紅）
 */
export function createSelectedShipTrajectoryLayers(mmsi, tripsData, theme = 'day') {
  const colors = SELECTION_COLORS[theme] || SELECTION_COLORS.day;
  const segments = tripsData
    .filter(t => t.mmsi === mmsi)
    .sort((a, b) => a.timestamps[0] - b.timestamps[0]);
  if (segments.length === 0) return [];

  // 1. 實線：每個子段內部路徑
  const solidData = segments.map(s => ({ path: s.path }));
  const solidLayer = new PathLayer({
    id: 'selected-ship-path-solid',
    data: solidData,
    getPath: d => d.path,
    getColor: [...colors.trajectory, 180],
    getWidth: 3,
    widthMinPixels: 2,
    widthMaxPixels: 5,
    opacity: 0.85,
    pickable: false,
  });

  // 2. 虛線：inferred gap（4-8hr）連接到下一段
  const dashedData = [];
  for (let i = 0; i < segments.length - 1; i++) {
    if (segments[i]._gapAfter === 'inferred') {
      const fromPath = segments[i].path;
      const toPath = segments[i + 1].path;
      dashedData.push({
        path: [fromPath[fromPath.length - 1], toPath[0]],
      });
    }
  }

  const layers = [solidLayer];

  if (dashedData.length > 0) {
    const dashedLayer = new PathLayer({
      id: 'selected-ship-path-dashed',
      data: dashedData,
      getPath: d => d.path,
      getColor: [...colors.trajectory, 100],
      getWidth: 2,
      widthMinPixels: 2,
      widthMaxPixels: 4,
      opacity: 0.6,
      pickable: false,
      getDashArray: [8, 4],
      extensions: [new PathStyleExtension({ dash: true })],
    });
    layers.push(dashedLayer);
  }

  // 3. 起終點標記
  const endpoints = [];
  for (const s of segments) {
    if (s.path.length === 0) continue;
    endpoints.push({ position: s.path[0], color: [76, 175, 80, 220] });                    // 綠：起點
    endpoints.push({ position: s.path[s.path.length - 1], color: [244, 67, 54, 220] });     // 紅：終點
  }

  const endpointLayer = new ScatterplotLayer({
    id: 'selected-ship-endpoints-layer',
    data: endpoints,
    getPosition: d => d.position,
    getFillColor: d => d.color,
    getRadius: 5,
    radiusMinPixels: 4,
    radiusMaxPixels: 8,
    radiusUnits: 'pixels',
    opacity: 0.9,
    pickable: false,
  });
  layers.push(endpointLayer);

  return layers;
}
