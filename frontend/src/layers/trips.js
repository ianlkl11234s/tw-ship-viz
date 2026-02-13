import { TripsLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer } from '@deck.gl/layers';
import { getSpeedColor, TRAIL_LENGTH_SEC } from '../utils/constants.js';

/**
 * 建立軌跡動畫圖層組（TripsLayer + 船頭 ScatterplotLayer）。
 *
 * @param {Array} tripsData - transformTrajectoryArrow() 的輸出
 * @param {number} currentTime - 當前時間（秒，相對於 base）
 * @param {string} theme - 'day' | 'night'
 * @param {Set|null} activeCategories - 啟用的船舶類別，null=全部
 * @returns {Array} deck.gl Layer 陣列
 */
export function createTripsLayers(tripsData, currentTime, theme = 'day', activeCategories = null) {
  const filteredData = activeCategories
    ? tripsData.filter(d => activeCategories.has(d.category))
    : tripsData;

  return [
    new TripsLayer({
      id: 'trips-layer',
      data: filteredData,
      getPath: d => d.path,
      getTimestamps: d => d.timestamps,
      getColor: d => {
        // 用該船的平均速度決定顏色
        const avgSpeed = d.speeds.reduce((a, b) => a + b, 0) / d.speeds.length;
        return getSpeedColor(avgSpeed, theme);
      },
      currentTime,
      trailLength: TRAIL_LENGTH_SEC,
      widthMinPixels: 2,
      widthMaxPixels: 4,
      opacity: 0.7,
      shadowEnabled: false,
      jointRounded: true,
      capRounded: true,

      // 效能優化
      updateTriggers: {
        getColor: [theme],
      },
    }),

    // 船頭位置圓點
    new ScatterplotLayer({
      id: 'ship-heads-layer',
      data: getShipPositionsAtTime(filteredData, currentTime),
      getPosition: d => d.position,
      getFillColor: d => [...getSpeedColor(d.sog, theme), 240],
      getRadius: 3,
      radiusUnits: 'pixels',
      radiusMinPixels: 2,
      radiusMaxPixels: 5,
      opacity: 0.95,

      updateTriggers: {
        getFillColor: [theme],
      },
    }),
  ];
}

/**
 * 從 trips 資料中，找出在 currentTime 時刻每艘船的位置。
 * 使用線性補間計算精確位置。
 */
function getShipPositionsAtTime(tripsData, currentTime) {
  const positions = [];

  for (const trip of tripsData) {
    const { timestamps, path, speeds, vessel_type, category, mmsi } = trip;
    if (timestamps.length === 0) continue;

    // 找到 currentTime 在哪兩個時間點之間
    const lastIdx = timestamps.length - 1;
    if (currentTime < timestamps[0] || currentTime > timestamps[lastIdx]) continue;

    // 二分搜尋
    let lo = 0, hi = lastIdx;
    while (lo < hi - 1) {
      const mid = (lo + hi) >> 1;
      if (timestamps[mid] <= currentTime) lo = mid;
      else hi = mid;
    }

    // 線性補間
    const t0 = timestamps[lo];
    const t1 = timestamps[hi];
    const dt = t1 - t0;
    const t = dt > 0 ? (currentTime - t0) / dt : 0;

    const lon = path[lo][0] + (path[hi][0] - path[lo][0]) * t;
    const lat = path[lo][1] + (path[hi][1] - path[lo][1]) * t;
    const sog = speeds[lo] + (speeds[hi] - speeds[lo]) * t;

    positions.push({
      position: [lon, lat],
      sog,
      vessel_type,
      category,
      mmsi,
    });
  }

  return positions;
}
