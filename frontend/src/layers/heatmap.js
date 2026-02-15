/**
 * 熱力圖（MapLibre 原生 heatmap layer）
 *
 * 使用雙 layer cross-fade 實現幀間平滑過渡：
 * 兩個 heatmap layer (A/B) 交替載入資料，切幀時一個淡入、一個淡出，
 * MapLibre 的 paint transition 自動處理動畫，視覺上連續無跳躍。
 */
import { THEMES } from '../utils/constants.js';

// === 雙 slot 架構 ===
const SLOTS = [
  { src: 'heatmap-src-a', lyr: 'heatmap-lyr-a' },
  { src: 'heatmap-src-b', lyr: 'heatmap-lyr-b' },
];

let activeIdx = 0;
let isFirstUpdate = true;

const TARGET_OPACITY = 0.6;
const FADE_MS = 1000; // cross-fade 時間（毫秒）

const EMPTY_FC = { type: 'FeatureCollection', features: [] };

// === 色彩 ===

function buildColorRamp(theme) {
  const g = THEMES[theme].heatGradient;
  const stops = Object.entries(g).sort(([a], [b]) => a - b);

  const expr = ['interpolate', ['linear'], ['heatmap-density']];
  expr.push(0, 'rgba(0,0,0,0)');

  // 低密度佔更大色域，高密度延後飽和
  const remapped = [0.02, 0.15, 0.35, 0.55, 0.75, 1.0];
  for (let i = 0; i < stops.length; i++) {
    expr.push(remapped[i] ?? parseFloat(stops[i][0]), stops[i][1]);
  }
  return expr;
}

// === Layer 設定 ===

function layerPaint(theme) {
  return {
    'heatmap-radius': [
      'interpolate', ['linear'], ['zoom'],
      5, 15,
      7, 25,
      9, 40,
      11, 55,
    ],
    'heatmap-intensity': [
      'interpolate', ['linear'], ['zoom'],
      5, 0.15,
      7, 0.35,
      9, 0.7,
      11, 1.5,
    ],
    'heatmap-color': buildColorRamp(theme),
    'heatmap-opacity': 0,
    'heatmap-opacity-transition': { duration: FADE_MS, delay: 0 },
  };
}

function ensureLayers(map, theme) {
  for (const { src, lyr } of SLOTS) {
    if (!map.getSource(src)) {
      map.addSource(src, { type: 'geojson', data: EMPTY_FC });
    }
    if (!map.getLayer(lyr)) {
      map.addLayer({
        id: lyr,
        type: 'heatmap',
        source: src,
        paint: layerPaint(theme),
      });
    }
  }
}

// === GeoJSON 建構 ===

function buildGeoJSON(frameIndex, frameIdx, vesselFilter) {
  const flatData = frameIndex.getFramePositionsFlat(frameIdx, vesselFilter);
  if (!flatData) return null;

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
  return { type: 'FeatureCollection', features };
}

// === 公開 API ===

/**
 * 更新熱力圖（幀變化時呼叫）。
 * 雙 layer 交替 + MapLibre paint transition → 平滑 cross-fade。
 */
export function updateNativeHeatmap(map, frameIndex, frameIdx, theme, vesselFilter = null) {
  ensureLayers(map, theme);

  const geojson = buildGeoJSON(frameIndex, frameIdx, vesselFilter);
  if (!geojson) return;

  // 載入新資料到「非活躍」slot
  const nextIdx = 1 - activeIdx;
  const next = SLOTS[nextIdx];
  const prev = SLOTS[activeIdx];

  map.getSource(next.src).setData(geojson);
  map.setLayoutProperty(next.lyr, 'visibility', 'visible');

  if (isFirstUpdate) {
    // 第一幀：直接顯示，不做 cross-fade
    map.setPaintProperty(next.lyr, 'heatmap-opacity', TARGET_OPACITY);
    isFirstUpdate = false;
  } else {
    // Cross-fade：新 slot 淡入、舊 slot 淡出
    map.setPaintProperty(next.lyr, 'heatmap-opacity', TARGET_OPACITY);
    map.setPaintProperty(prev.lyr, 'heatmap-opacity', 0);
  }

  activeIdx = nextIdx;
}

/**
 * 隱藏熱力圖（離開 heatmap 模式時呼叫）。
 */
export function hideNativeHeatmap(map) {
  for (const { lyr } of SLOTS) {
    if (map.getLayer(lyr)) {
      map.setPaintProperty(lyr, 'heatmap-opacity', 0);
      map.setLayoutProperty(lyr, 'visibility', 'none');
    }
  }
  isFirstUpdate = true;
}
