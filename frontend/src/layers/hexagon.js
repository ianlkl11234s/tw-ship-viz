import { HexagonLayer } from '@deck.gl/aggregation-layers';
import { THEMES, hexToRgb } from '../utils/constants.js';

/**
 * 建立六角網格密度圖層（HexagonLayer）。
 *
 * @param {Array} shipPositions - 當前幀的船舶位置 [{position: [lon,lat], ...}]
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createHexagonLayers(shipPositions, theme = 'day') {
  const colors = THEMES[theme].density;

  const colorRange = colors
    .filter(c => c !== 'transparent')
    .slice(1)
    .map(c => hexToRgb(c));

  return [
    new HexagonLayer({
      id: 'hexagon-layer',
      data: shipPositions,
      getPosition: d => d.position,
      radius: 5000,           // 5km 半徑
      elevationScale: 0,      // 2D 模式
      extruded: false,
      colorRange,
      opacity: 0.7,
      coverage: 0.9,
      gpuAggregation: true,

      updateTriggers: {
        colorRange: [theme],
      },
    }),
  ];
}
