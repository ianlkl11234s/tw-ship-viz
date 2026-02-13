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
 * @param {{ positions: Float32Array, count: number }} flatData - TypedArray 格式的位置資料
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl Layer 陣列
 */
export function createHeatmapLayers(flatData, theme = 'day') {
  const colorRange = getColorRange(theme);

  const heatLayer = new HeatmapLayer({
    id: 'heatmap-layer',
    data: {
      length: flatData.count,
      attributes: {
        getPosition: { value: flatData.positions, size: 2 },
      },
    },
    getWeight: 1,
    radiusPixels: 30,
    intensity: 1,
    threshold: 0.05,
    colorRange,
    opacity: 0.8,
  });

  return [heatLayer];
}
