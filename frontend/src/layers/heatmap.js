/**
 * 熱力圖 Layer（HeatmapLayer）
 * WebGL 核密度估計熱力圖。
 */
import { HeatmapLayer } from '@deck.gl/aggregation-layers';
import { THEMES, hexToRgb } from '../utils/constants.js';

/**
 * @param {Array} positions - [{position: [lon,lat], weight: number}, ...]
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createHeatmapLayers(positions, theme = 'day') {
  const gradient = THEMES[theme].heatGradient;
  const colorRange = Object.entries(gradient)
    .sort(([a], [b]) => parseFloat(a) - parseFloat(b))
    .map(([, hex]) => hexToRgb(hex));

  const heatLayer = new HeatmapLayer({
    id: 'heatmap-layer',
    data: positions,
    getPosition: d => d.position,
    getWeight: d => d.weight || 1,
    radiusPixels: 30,
    intensity: 1,
    threshold: 0.05,
    colorRange,
    opacity: 0.8,
  });

  return [heatLayer];
}
