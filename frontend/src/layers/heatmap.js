import { HeatmapLayer } from '@deck.gl/aggregation-layers';
import { THEMES, hexToRgb } from '../utils/constants.js';

/**
 * 建立 KDE 熱力圖圖層（HeatmapLayer）。
 *
 * @param {Array} shipPositions - 當前幀的船舶位置 [{position: [lon,lat], ...}]
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createHeatmapLayers(shipPositions, theme = 'day') {
  const gradient = THEMES[theme].heatGradient;

  // HeatmapLayer 的 colorRange：從 gradient 物件取色
  const colorRange = Object.values(gradient).map(c => hexToRgb(c));

  return [
    new HeatmapLayer({
      id: 'heatmap-layer',
      data: shipPositions,
      getPosition: d => d.position,
      getWeight: 1,
      radiusPixels: 30,
      intensity: 1.5,
      threshold: 0.05,
      colorRange,
      opacity: 0.7,

      updateTriggers: {
        colorRange: [theme],
      },
    }),
  ];
}
