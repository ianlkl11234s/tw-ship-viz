/**
 * 港口碼頭 Polygon 圖層（MapLibre 原生）
 * 類似 plan-art 車站 stationOverlay — fill + glow 渲染
 */

const SOURCE_ID = 'port-polygons';
const FILL_ID = 'port-poly-fill';
const LINE_ID = 'port-poly-line';
const GLOW_1_ID = 'port-poly-glow-1';
const GLOW_2_ID = 'port-poly-glow-2';

const ALL_LAYERS = [GLOW_2_ID, GLOW_1_ID, FILL_ID, LINE_ID];

/**
 * 初始化港口 polygon 圖層（載入 GeoJSON + 建立圖層）
 */
export function addPortPolygonOverlay(map, theme = 'day') {
  if (map.getSource(SOURCE_ID)) return;

  map.addSource(SOURCE_ID, {
    type: 'geojson',
    data: '/data/port_polygons.geojson',
  });

  _addLayers(map, theme);
}

/**
 * 主題切換時更新樣式
 */
export function updatePortPolygonStyle(map, theme = 'day') {
  if (!map.getSource(SOURCE_ID)) return;
  const isDark = theme === 'night';
  const color = isDark ? '#ffffff' : '#4a90d9';
  const glowColor = isDark ? '#88bbff' : '#3a7bd5';

  map.setPaintProperty(FILL_ID, 'fill-color', color);
  map.setPaintProperty(FILL_ID, 'fill-opacity', isDark ? 0.06 : 0.10);
  map.setPaintProperty(LINE_ID, 'line-color', color);
  map.setPaintProperty(LINE_ID, 'line-opacity', isDark ? 0.25 : 0.40);
  map.setPaintProperty(GLOW_1_ID, 'line-color', glowColor);
  map.setPaintProperty(GLOW_1_ID, 'line-opacity', isDark ? 0.10 : 0.20);
  map.setPaintProperty(GLOW_2_ID, 'line-color', glowColor);
  map.setPaintProperty(GLOW_2_ID, 'line-opacity', isDark ? 0.04 : 0.10);
}

/**
 * 顯示/隱藏
 */
export function setPortPolygonVisible(map, visible) {
  const v = visible ? 'visible' : 'none';
  for (const id of ALL_LAYERS) {
    if (map.getLayer(id)) {
      map.setLayoutProperty(id, 'visibility', v);
    }
  }
}

// ── internal ──

function _addLayers(map, theme) {
  const isDark = theme === 'night';
  const color = isDark ? '#ffffff' : '#4a90d9';
  const glowColor = isDark ? '#88bbff' : '#3a7bd5';

  // 外層光暈
  map.addLayer({
    id: GLOW_2_ID,
    type: 'line',
    source: SOURCE_ID,
    paint: {
      'line-color': glowColor,
      'line-width': 12,
      'line-blur': 8,
      'line-opacity': isDark ? 0.04 : 0.10,
    },
  });

  // 內層光暈
  map.addLayer({
    id: GLOW_1_ID,
    type: 'line',
    source: SOURCE_ID,
    paint: {
      'line-color': glowColor,
      'line-width': 5,
      'line-blur': 3,
      'line-opacity': isDark ? 0.10 : 0.20,
    },
  });

  // 填充
  map.addLayer({
    id: FILL_ID,
    type: 'fill',
    source: SOURCE_ID,
    paint: {
      'fill-color': color,
      'fill-opacity': isDark ? 0.06 : 0.10,
    },
  });

  // 邊框
  map.addLayer({
    id: LINE_ID,
    type: 'line',
    source: SOURCE_ID,
    paint: {
      'line-color': color,
      'line-width': isDark ? 1 : 1.5,
      'line-opacity': isDark ? 0.25 : 0.40,
    },
  });
}
