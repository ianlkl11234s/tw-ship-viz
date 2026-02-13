/**
 * 查詢模式 Layer（PathLayer + ScatterplotLayer）
 * 顯示單船/多船歷史軌跡。
 */
import { PathLayer, ScatterplotLayer } from '@deck.gl/layers';
import { getSpeedColor } from '../utils/constants.js';

/**
 * 建立查詢結果軌跡的 layers。
 * @param {Array} queryResults - [{mmsi, vesselType, path: [[lon,lat],...], color: [r,g,b]}, ...]
 * @param {string} theme
 * @returns {Array}
 */
export function createQueryLayers(queryResults, theme = 'day') {
  const pathLayer = new PathLayer({
    id: 'query-path-layer',
    data: queryResults,
    getPath: d => d.path,
    getColor: d => d.color || [0, 119, 182],
    getWidth: 2,
    widthMinPixels: 2,
    widthMaxPixels: 5,
    opacity: 0.8,
    rounded: true,
  });

  // 起終點標記
  const markers = [];
  for (const result of queryResults) {
    if (result.path.length >= 2) {
      markers.push({
        position: result.path[0],
        color: [22, 163, 74, 220], // 綠色起點
        radius: 5,
      });
      markers.push({
        position: result.path[result.path.length - 1],
        color: [220, 38, 38, 220], // 紅色終點
        radius: 5,
      });
    }
  }

  const markerLayer = new ScatterplotLayer({
    id: 'query-markers-layer',
    data: markers,
    getPosition: d => d.position,
    getFillColor: d => d.color,
    getRadius: d => d.radius,
    radiusMinPixels: 4,
    radiusMaxPixels: 8,
    radiusUnits: 'pixels',
  });

  return [pathLayer, markerLayer];
}

/**
 * 建立查詢模式的船舶散點（最新位置）。
 * @param {Array} ships - [{position: [lon,lat], mmsi, vesselType}, ...]
 * @returns {ScatterplotLayer}
 */
export function createQueryShipDots(ships) {
  return new ScatterplotLayer({
    id: 'query-ships-layer',
    data: ships,
    getPosition: d => d.position,
    getFillColor: [0, 119, 182, 180],
    getRadius: 3,
    radiusMinPixels: 3,
    radiusMaxPixels: 6,
    radiusUnits: 'pixels',
    pickable: true,
  });
}
