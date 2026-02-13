import { PathLayer, ScatterplotLayer } from '@deck.gl/layers';
import { getVesselDotColor } from '../utils/constants.js';

/**
 * 建立查詢模式的軌跡圖層（PathLayer + ScatterplotLayer）。
 *
 * @param {Array} queryResults - [{mmsi, vessel_type, path: [[lon,lat],...], timestamps, speeds}]
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createQueryLayers(queryResults, theme = 'day') {
  if (!queryResults || queryResults.length === 0) return [];

  // 多船用 HSL 色相漸變
  const getPathColor = (d, i) => {
    if (queryResults.length === 1) return [253, 128, 93];
    const hue = (i / queryResults.length) * 360;
    return hslToRgb(hue, 80, 55);
  };

  // 起終點標記資料
  const startEndPoints = [];
  for (const result of queryResults) {
    if (result.path.length >= 2) {
      startEndPoints.push({
        position: result.path[0],
        type: 'start',
        vessel_type: result.vessel_type,
      });
      startEndPoints.push({
        position: result.path[result.path.length - 1],
        type: 'end',
        vessel_type: result.vessel_type,
      });
    }
  }

  return [
    new PathLayer({
      id: 'query-path-layer',
      data: queryResults.map((d, i) => ({ ...d, _index: i })),
      getPath: d => d.path,
      getColor: d => getPathColor(d, d._index),
      getWidth: 3,
      widthUnits: 'pixels',
      widthMinPixels: 2,
      opacity: 0.8,
      jointRounded: true,
      capRounded: true,
    }),

    new ScatterplotLayer({
      id: 'query-endpoints-layer',
      data: startEndPoints,
      getPosition: d => d.position,
      getFillColor: d => d.type === 'start' ? [22, 163, 74, 220] : [220, 38, 38, 220],
      getRadius: 5,
      radiusUnits: 'pixels',
      radiusMinPixels: 4,
      radiusMaxPixels: 8,
    }),
  ];
}

/**
 * 建立查詢模式的船舶散點圖層（顯示最新位置）。
 */
export function createQueryShipDots(ships) {
  return new ScatterplotLayer({
    id: 'query-ships-layer',
    data: ships,
    getPosition: d => d.position,
    getFillColor: d => [...getVesselDotColor(d.vessel_type), 200],
    getRadius: 4,
    radiusUnits: 'pixels',
    radiusMinPixels: 3,
    radiusMaxPixels: 6,
    pickable: true,
  });
}

// HSL 轉 RGB（0-255）
function hslToRgb(h, s, l) {
  s /= 100;
  l /= 100;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r, g, b;
  if (h < 60)       { r = c; g = x; b = 0; }
  else if (h < 120) { r = x; g = c; b = 0; }
  else if (h < 180) { r = 0; g = c; b = x; }
  else if (h < 240) { r = 0; g = x; b = c; }
  else if (h < 300) { r = x; g = 0; b = c; }
  else              { r = c; g = 0; b = x; }
  return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
}
