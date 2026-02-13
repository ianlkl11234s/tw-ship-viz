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
 *
 * 可調參數說明（修改此處即可改變視覺效果）：
 *
 *   heatmap-color 的 stop 值 = heatmap-density（0~1）
 *     - 把暖色 stop 推高 → 需要更高密度才出現深色（延緩飽和）
 *     - 把冷色 stop 壓低 → 低密度就有顏色（漸層更明顯）
 *
 *   heatmap-radius（在 ensureSourceAndLayer 裡）：
 *     - 加大 → 點與點重疊更多 → 邊緣更模糊
 *
 *   heatmap-intensity：
 *     - 降低 → 累加速度慢 → 不會太快進入深色
 */
function buildColorRamp(theme) {
  const g = THEMES[theme].heatGradient;
  const stops = Object.entries(g).sort(([a], [b]) => a - b);

  const expr = ['interpolate', ['linear'], ['heatmap-density']];
  expr.push(0, 'rgba(0,0,0,0)');

  // 對 stop 值做指數映射：讓低密度區佔更大色域，高密度延後飽和
  // 原始 stops: 0, 0.2, 0.4, 0.6, 0.8, 1.0
  // 映射後:      0.02, 0.15, 0.35, 0.55, 0.75, 1.0
  const remapped = [0.02, 0.15, 0.35, 0.55, 0.75, 1.0];
  for (let i = 0; i < stops.length; i++) {
    expr.push(remapped[i] ?? parseFloat(stops[i][0]), stops[i][1]);
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
        // --- heatmap-radius ---
        // 加大半徑讓點與點高度重疊，消除「圓圈感」
        // 調高 → 更模糊柔和；調低 → 更精細但邊緣明顯
        'heatmap-radius': [
          'interpolate', ['linear'], ['zoom'],
          5, 15,   // zoom 5：全台灣
          7, 25,
          9, 40,
          11, 55,  // zoom 11：港口特寫
        ],
        // --- heatmap-intensity ---
        // 控制「多快飽和」：值越低，需要越多船才到深色
        // 調低 → 漸層層次更豐富；調高 → 港口更突出
        'heatmap-intensity': [
          'interpolate', ['linear'], ['zoom'],
          5, 0.1,
          7, 0.3,
          9, 0.6,
          11, 1.2,
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
