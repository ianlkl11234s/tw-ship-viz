/**
 * 密度格網 Layer（ScreenGridLayer）
 * 用 GPU 在螢幕空間聚合船舶密度。
 */
import { ScreenGridLayer } from '@deck.gl/aggregation-layers';
import { THEMES, hexToRgb } from '../utils/constants.js';

/**
 * @param {Array} positions - [{position: [lon,lat], ...}, ...]
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createGridLayers(positions, theme = 'day') {
  const colors = THEMES[theme].density;

  // ScreenGridLayer 會自動在 GPU 端聚合
  const gridLayer = new ScreenGridLayer({
    id: 'screen-grid-layer',
    data: positions,
    getPosition: d => d.position,
    getWeight: 1,
    cellSizePixels: 12,
    colorRange: colors.slice(1).map(c => {
      if (c === 'transparent') return [0, 0, 0, 0];
      return [...hexToRgb(c), 200];
    }),
    gpuAggregation: true,
    opacity: 0.8,
  });

  return [gridLayer];
}
