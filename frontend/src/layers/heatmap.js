/**
 * 熱力圖（MapLibre 原生 heatmap layer）
 *
 * 直接在 MapLibre 的 WebGL pipeline 中渲染，不經 deck.gl overlay，
 * 拖曳/縮放時零額外開銷。
 */
import { THEMES } from '../utils/constants.js';

const SOURCE_ID = 'ship-heatmap-src';
const LAYER_ID = 'ship-heatmap-lyr';

/**
 * 建構 MapLibre heatmap-color 漸層表達式。
 */
function buildColorRamp(theme) {
  const g = THEMES[theme].heatGradient;
  const expr = ['interpolate', ['linear'], ['heatmap-density']];
  expr.push(0, 'rgba(0,0,0,0)'); // density=0 透明

  for (const [stop, color] of Object.entries(g).sort(([a], [b]) => a - b)) {
    const s = parseFloat(stop);
    expr.push(s <= 0 ? 0.01 : s, color);
  }
  return expr;
}

/**
 * 確保 source + layer 存在。
 * 主題切換（setStyle）會移除所有自訂 layer，故每次都需檢查。
 */
function ensureSourceAndLayer(map, theme) {
  if (!map.getSource(SOURCE_ID)) {
    map.addSource(SOURCE_ID, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    });
  }
  if (!map.getLayer(LAYER_ID)) {
    map.addLayer({
      id: LAYER_ID,
      type: 'heatmap',
      source: SOURCE_ID,
      paint: {
        // 隨 zoom 調整：遠看平滑大範圍，近看精細高對比
        'heatmap-radius': [
          'interpolate', ['linear'], ['zoom'],
          5, 8,    // zoom 5：全台灣 → 小半徑避免過曝
          7, 15,
          9, 25,
          11, 40,  // zoom 11：港口特寫 → 大半徑顯示細節
        ],
        'heatmap-intensity': [
          'interpolate', ['linear'], ['zoom'],
          5, 0.3,
          7, 0.8,
          9, 1.5,
          11, 3,
        ],
        'heatmap-color': buildColorRamp(theme),
        'heatmap-opacity': 0.85,
      },
    });
  }
}

/**
 * 更新熱力圖資料（僅在幀變化時呼叫）。
 */
export function updateNativeHeatmap(map, frameIndex, frameIdx, theme) {
  ensureSourceAndLayer(map, theme);

  const flatData = frameIndex.getFramePositionsFlat(frameIdx);
  if (!flatData) return;

  // Float32Array → GeoJSON（12,000 點對 MapLibre 是輕量級）
  const { positions, count } = flatData;
  const features = new Array(count);
  for (let i = 0; i < count; i++) {
    features[i] = {
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [positions[i * 2], positions[i * 2 + 1]],
      },
    };
  }

  map.getSource(SOURCE_ID).setData({ type: 'FeatureCollection', features });
  map.setLayoutProperty(LAYER_ID, 'visibility', 'visible');
}

/**
 * 隱藏熱力圖（切換到其他模式時呼叫）。
 */
export function hideNativeHeatmap(map) {
  if (map.getLayer(LAYER_ID)) {
    map.setLayoutProperty(LAYER_ID, 'visibility', 'none');
  }
}
