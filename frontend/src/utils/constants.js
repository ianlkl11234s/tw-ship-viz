// === 地圖配置 ===
export const MAP_CENTER = [121.5, 24.5]; // [lng, lat] for MapLibre (注意順序與 Leaflet 相反)
export const MAP_ZOOM = 7;
export const MAP_MIN_ZOOM = 5;
export const MAP_MAX_ZOOM = 12;

// === 地理範圍（台灣海域）===
export const GEO_BOUNDS = {
  lonMin: 117.0,
  lonMax: 127.0,
  latMin: 20.0,
  latMax: 28.0,
  resolution: 0.05, // ~5.5km
  cols: 200,
  rows: 160,
};

// === 軌跡常數 ===
export const TRAIL_LENGTH_SEC = 3600; // TripsLayer 尾跡長度（秒），約 6 幀 × 600s
export const MAX_DISTANCE_KM = 20;    // 10 分鐘內最大合理移動距離

// === Gap 拆分閾值（秒）===
// 後端 split_trajectory_geo() 已處理港口停泊（1hr+）、陸地穿越、速度異常（>45kt），
// 前端只需補超長 gap，因此閾值可拉高以減少子段數（204K → ~80-100K）。
export const GAP_THRESHOLDS = {
  NORMAL_MAX: 28800,   // 8hr（原 4hr）— 小於此為正常（不切）
  INFERRED_MAX: 57600, // 16hr（原 8hr）— 8~16hr 為推測航段（虛線）；>= 16hr 完全斷開
};

// === 播放速度配置 ===
export const PLAY_SPEEDS = [1, 2, 4, 8];
export const BASE_INTERVALS = {
  density: 1000,
  trajectory: 2000,
  hexbin: 1000,
  heatmap: 1500,
};

// === 船舶類型分類 ===
export const VESSEL_CATEGORIES = {
  fishing:   { label: '漁船',       codes: [30] },
  cargo:     { label: '貨船',       codes: [70,71,72,73,74,75,76,77,78,79] },
  tanker:    { label: '油輪',       codes: [80,81,82,83,84,85,86,87,88,89] },
  passenger: { label: '客輪',       codes: [60,61,62,63,64,65,66,67,68,69] },
  tug:       { label: '拖船',       codes: [31, 32] },
  military:  { label: '軍艦',       codes: [35] },
  sailing:   { label: '帆船/遊艇', codes: [36, 37] },
  service:   { label: '服務船舶',   codes: [50, 51, 52, 53, 55, 33, 34] },
  highspeed: { label: '高速船',     codes: [40] },
  unknown:   { label: '不明',       codes: [0, 20, 90] },
};

// 建立 vessel_type code → category key 的反向查找表
export const VESSEL_CODE_TO_CATEGORY = {};
for (const [key, { codes }] of Object.entries(VESSEL_CATEGORIES)) {
  for (const code of codes) {
    VESSEL_CODE_TO_CATEGORY[code] = key;
  }
}

export const VESSEL_TYPE_NAMES = {
  0: '未知', 30: '漁船', 31: '拖船', 32: '拖船', 33: '疏浚船', 34: '潛水作業',
  35: '軍艦', 36: '帆船', 37: '遊艇', 40: '高速船',
  50: '領航船', 51: '搜救船', 52: '拖船', 53: '港務船', 55: '執法船',
  60: '客輪', 70: '貨船', 80: '油輪', 90: '其他',
};

// === 主題配置 ===
export const THEMES = {
  day: {
    mapStyle: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    density: ['#f0fffe','#80cdc1','#c7e9b4','#ffffcc','#fdb863','#e06c52','#8c2d04'],
    speed:   ['#1d4ed8','#7b2cbf','#e85d04','#c41d3c'],
    heatGradient: {0.0:'#0a1628',0.2:'#0d3b66',0.4:'#1d7874',0.6:'#679436',0.8:'#f5a623',1.0:'#f7f052'},
    heatGradientCSS: 'linear-gradient(to bottom, #f7f052, #f5a623, #679436, #1d7874, #0d3b66, #0a1628)',
  },
  night: {
    mapStyle: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    density: ['transparent','#160b39','#420a68','#932667','#dd513a','#fba40a','#fcffa4'],
    speed:   ['#4cc9f0','#72efdd','#fee440','#ff2d75'],
    heatGradient: {0.0:'#0a1628',0.2:'#0d3b66',0.4:'#1d7874',0.6:'#679436',0.8:'#f5a623',1.0:'#f7f052'},
    heatGradientCSS: 'linear-gradient(to bottom, #f7f052, #f5a623, #679436, #1d7874, #0d3b66, #0a1628)',
  },
};

// === 速度配色方案（全部基於 sog 分級）===
export const SPEED_PALETTES = {
  speed: null,  // 使用 THEMES[theme].speed
  blue:  ['#dbeafe', '#93c5fd', '#3b82f6', '#1e40af'],
  warm:  ['#fef08a', '#fcd34d', '#fb923c', '#ef4444'],
  neon:  ['#67e8f9', '#a78bfa', '#f472b6', '#fb7185'],
};

// === 色彩工具函式 ===

/** hex 色碼轉 [r, g, b] 陣列（deck.gl 用 0-255） */
export function hexToRgb(hex) {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result
    ? [parseInt(result[1], 16), parseInt(result[2], 16), parseInt(result[3], 16)]
    : [128, 128, 128];
}

/** 根據速度取得 RGB 色彩陣列 */
export function getSpeedColor(sog, theme = 'day') {
  const s = THEMES[theme].speed.map(hexToRgb);
  if (sog > 15) return s[3];
  if (sog > 10) return s[2];
  if (sog > 5)  return s[1];
  return s[0];
}

/** 根據速度 + 配色方案取得 RGB 色彩陣列 */
export function getSpeedColorByPalette(sog, theme = 'day', palette = 'speed') {
  const paletteHexes = SPEED_PALETTES[palette];
  const hexes = paletteHexes || THEMES[theme].speed;
  const s = hexes.map(hexToRgb);
  if (sog > 15) return s[3];
  if (sog > 10) return s[2];
  if (sog > 5)  return s[1];
  return s[0];
}

/** 根據密度取得 RGB 色彩陣列 + alpha */
export function getDensityColor(count, theme = 'day') {
  const c = THEMES[theme].density.map(hexToRgb);
  let colorIdx, alpha;
  if (count === 0)  { colorIdx = 0; alpha = 76; }   // 0.3 * 255
  else if (count <= 2)  { colorIdx = 1; alpha = 166; }
  else if (count <= 5)  { colorIdx = 2; alpha = 179; }
  else if (count <= 10) { colorIdx = 3; alpha = 191; }
  else if (count <= 20) { colorIdx = 4; alpha = 204; }
  else if (count <= 50) { colorIdx = 5; alpha = 217; }
  else { colorIdx = 6; alpha = 230; }
  return [...c[colorIdx], alpha];
}

// === 選擇高亮配色 ===
export const SELECTION_COLORS = {
  day:   { highlight: [255,193,7,120], stroke: [255,193,7,255], trajectory: [255,152,0] },
  night: { highlight: [255,214,0,120], stroke: [255,214,0,255], trajectory: [255,193,7] },
};

/** 查詢模式的船舶圓點色彩 */
export function getVesselDotColor(vtype) {
  if (vtype === 30) return [22, 163, 74];
  if (vtype >= 70 && vtype <= 79) return [37, 99, 235];
  if (vtype >= 80 && vtype <= 89) return [220, 38, 38];
  if (vtype >= 60 && vtype <= 69) return [147, 51, 234];
  if (vtype === 35) return [71, 85, 105];
  return [245, 158, 11];
}
