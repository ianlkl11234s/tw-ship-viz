import { ScreenGridLayer } from '@deck.gl/aggregation-layers';
import { THEMES, hexToRgb } from '../utils/constants.js';

/**
 * 建立密度格網圖層（ScreenGridLayer）。
 *
 * @param {Array} shipPositions - 當前幀的船舶位置 [{position: [lon,lat], ...}]
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createGridLayers(shipPositions, theme = 'day') {
  const colors = THEMES[theme].density;

  // ScreenGridLayer 的 colorRange（取中間 5 個色階，排除 transparent）
  const colorRange = colors
    .filter(c => c !== 'transparent')
    .slice(1) // 跳過最淡的
    .map(c => hexToRgb(c));

  return [
    new ScreenGridLayer({
      id: 'density-grid-layer',
      data: shipPositions,
      getPosition: d => d.position,
      getWeight: 1,
      cellSizePixels: 12,
      colorRange,
      opacity: 0.75,
      gpuAggregation: true,

      updateTriggers: {
        colorRange: [theme],
      },
    }),
  ];
}
