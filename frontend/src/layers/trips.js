/**
 * 軌跡動畫 Layer
 * 使用 deck.gl TripsLayer 渲染船舶軌跡 + ScatterplotLayer 渲染船頭位置。
 */
import { TripsLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer } from '@deck.gl/layers';
import { getSpeedColor, VESSEL_CODE_TO_CATEGORY } from '../utils/constants.js';

/**
 * 建立軌跡動畫的 deck.gl layers。
 *
 * @param {Array} tripsData - arrowToTrips() 的輸出
 * @param {number} currentTime - 當前時間（秒，相對 base_timestamp）
 * @param {string} theme - 'day' | 'night'
 * @param {Set|null} vesselFilter - 允許的 category key 集合，null = 全部
 * @returns {Array} deck.gl Layer 陣列
 */
export function createTrajectoryLayers(tripsData, currentTime, theme = 'day', vesselFilter = null) {
  // 篩選船舶類型
  const filteredData = vesselFilter
    ? tripsData.filter(d => {
        const cat = VESSEL_CODE_TO_CATEGORY[d.vesselType];
        return cat && vesselFilter.has(cat);
      })
    : tripsData;

  const tripsLayer = new TripsLayer({
    id: 'trips-layer',
    data: filteredData,
    getPath: d => d.path,
    getTimestamps: d => d.timestamps,
    getColor: d => {
      // 用該船最後已知的速度決定顏色
      const lastIdx = d.timestamps.findIndex(t => t > currentTime) - 1;
      const idx = lastIdx >= 0 ? lastIdx : d.timestamps.length - 1;
      // 粗略用 path 點間距離估算速度，但直接用固定色也可以
      return getSpeedColor(d.avgSog || 5, theme);
    },
    getWidth: 2,
    widthMinPixels: 2,
    widthMaxPixels: 4,
    trailLength: 1800, // 尾跡 30 分鐘（秒）
    currentTime,
    opacity: 0.8,
    rounded: true,
    updateTriggers: {
      getColor: [theme],
    },
  });

  // 船頭位置（ScatterplotLayer）：顯示在 currentTime 時刻活躍的船舶
  const shipPositions = getShipPositionsAtTime(filteredData, currentTime);

  const scatterLayer = new ScatterplotLayer({
    id: 'ship-positions-layer',
    data: shipPositions,
    getPosition: d => d.position,
    getFillColor: d => [...getSpeedColor(d.sog, theme), 240],
    getRadius: 3,
    radiusMinPixels: 3,
    radiusMaxPixels: 6,
    radiusUnits: 'pixels',
    opacity: 0.95,
    updateTriggers: {
      getFillColor: [theme],
    },
  });

  return [tripsLayer, scatterLayer];
}

/**
 * 根據 currentTime 計算每艘船的插值位置。
 */
function getShipPositionsAtTime(tripsData, currentTime) {
  const positions = [];

  for (const trip of tripsData) {
    const { timestamps, path, mmsi, vesselType } = trip;
    if (timestamps.length === 0) continue;

    // 找到 currentTime 落在哪兩個時間點之間
    if (currentTime < timestamps[0] || currentTime > timestamps[timestamps.length - 1]) {
      continue; // 不在這艘船的時間範圍內
    }

    let idx = -1;
    for (let i = 0; i < timestamps.length - 1; i++) {
      if (timestamps[i] <= currentTime && currentTime <= timestamps[i + 1]) {
        idx = i;
        break;
      }
    }

    if (idx === -1) {
      // 剛好在最後一個時間點
      if (currentTime >= timestamps[timestamps.length - 1] &&
          currentTime - timestamps[timestamps.length - 1] < 600) { // 10 分鐘內
        const last = path[path.length - 1];
        positions.push({
          position: last,
          mmsi,
          vesselType,
          sog: trip.avgSog || 5,
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
    const lon = p0[0] + (p1[0] - p0[0]) * ratio;
    const lat = p0[1] + (p1[1] - p0[1]) * ratio;

    positions.push({
      position: [lon, lat],
      mmsi,
      vesselType,
      sog: trip.avgSog || 5,
    });
  }

  return positions;
}

/**
 * 預處理 trips 資料：計算每艘船的平均速度（用於著色）。
 * 在資料載入後呼叫一次。
 */
export function preprocessTrips(tripsData, arrowTable) {
  if (!arrowTable) return tripsData;

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

  return tripsData;
}
