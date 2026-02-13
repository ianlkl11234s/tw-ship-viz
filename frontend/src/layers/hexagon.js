/**
 * 六角網格 Layer（HexagonLayer）
 * GPU 端六角形 binning 密度聚合。
 */
import { HexagonLayer } from '@deck.gl/aggregation-layers';
import { THEMES, hexToRgb } from '../utils/constants.js';

/**
 * @param {Array} positions - [{position: [lon,lat], ...}, ...]
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createHexagonLayers(positions, theme = 'day') {
  const colors = THEMES[theme].density;

  const hexLayer = new HexagonLayer({
    id: 'hexagon-layer',
    data: positions,
    getPosition: d => d.position,
    radius: 5000, // 5km 半徑
    elevationScale: 0, // 2D 模式
    colorRange: colors.slice(1).map(c => {
      if (c === 'transparent') return [0, 0, 0, 0];
      return hexToRgb(c);
    }),
    coverage: 0.9,
    opacity: 0.7,
    extruded: false,
    gpuAggregation: true,
  });

  return [hexLayer];
}
