/**
 * 熱力圖 Layer（HeatmapLayer）
 * WebGL 核密度估計熱力圖。
 *
 * 使用 binary attributes 格式：直接傳 Float32Array 給 GPU，
 * 避免建立 12,000+ 個 JS 物件。
 */
import { HeatmapLayer } from '@deck.gl/aggregation-layers';
import { THEMES, hexToRgb } from '../utils/constants.js';

// 快取 colorRange 避免每次重算
const _colorRangeCache = {};
function getColorRange(theme) {
  if (_colorRangeCache[theme]) return _colorRangeCache[theme];
  const gradient = THEMES[theme].heatGradient;
  const range = Object.entries(gradient)
    .sort(([a], [b]) => parseFloat(a) - parseFloat(b))
    .map(([, hex]) => hexToRgb(hex));
  _colorRangeCache[theme] = range;
  return range;
}

/**
 * @param {{ positions: Float32Array, weights: Float32Array, count: number }} heatData
 *   空間預聚合後的資料（~2,000 個帶權重格子，非原始 12,000 點）
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createHeatmapLayers(heatData, theme = 'day') {
  const colorRange = getColorRange(theme);

  const heatLayer = new HeatmapLayer({
    id: 'heatmap-layer',
    data: {
      length: heatData.count,
      attributes: {
        getPosition: { value: heatData.positions, size: 2 },
        getWeight: { value: heatData.weights, size: 1 },
      },
    },
    radiusPixels: 40,
    intensity: 1,
    threshold: 0.05,
    colorRange,
    opacity: 0.8,
    debounceTimeout: 100,
  });

  return [heatLayer];
}
