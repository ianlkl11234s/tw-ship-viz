/**
 * 軌跡動畫 Layer
 * 使用 deck.gl TripsLayer 渲染船舶軌跡 + ScatterplotLayer 渲染船頭位置。
 */
import { TripsLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer } from '@deck.gl/layers';
import { getSpeedColor } from '../utils/constants.js';

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
  });

  return [tripsLayer, scatterLayer];
}

/**
 * 根據 currentTime 用二分搜尋計算每艘船的插值位置。
 */
function getShipPositionsAtTime(tripsData, currentTime) {
  const positions = [];

  for (const trip of tripsData) {
    const { timestamps, path, mmsi, vesselType, _dotColor } = trip;
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
      _bakeColors(trip, 'day');
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

  // 預烘焙顏色（初始用 day 主題，切換時會重新烘焙）
  bakeAllColors(tripsData, 'day');

  return tripsData;
}

/**
 * 為所有 trips 預烘焙顏色。主題切換時呼叫。
 */
export function bakeAllColors(tripsData, theme) {
  for (const trip of tripsData) {
    _bakeColors(trip, theme);
  }
}

function _bakeColors(trip, theme) {
  const rgb = getSpeedColor(trip.avgSog || 5, theme);
  const alpha = trip.path.length < 6 ? 120 : 200;
  trip._color = [rgb[0], rgb[1], rgb[2], alpha];
  trip._dotColor = [rgb[0], rgb[1], rgb[2], 240];
}
