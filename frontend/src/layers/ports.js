/**
 * 港口圖層
 * 顯示港口位置、名稱、圍欄半徑。
 * 依 port_class 區分半徑與標籤大小。
 */
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';

// 與後端 generate_arrow.py 一致
const LARGE_PORT_RADIUS_M = 3000; // 3.0 km
const LARGE_PORTS = new Set([
  '高雄港', '基隆港', '臺中港', '花蓮港', '台北港', '蘇澳港', '安平港',
]);

// 依 port_class 決定圍欄半徑
function getPortRadius(name, portClass, source) {
  if (LARGE_PORTS.has(name)) return 3000;
  if (source === 'TDX' || portClass === '客運港') return 1500;
  if (portClass === '第一類漁港') return 1000;
  return 500;
}

/**
 * 將 ports.geojson 的 features 轉為圖層資料。
 */
function preparePortData(features) {
  return features.map(f => {
    const name = f.properties.name;
    const portClass = f.properties.port_class || '';
    const source = f.properties.source || '';
    const [lon, lat] = f.geometry.coordinates;
    const radius = getPortRadius(name, portClass, source);
    const isLarge = LARGE_PORTS.has(name);
    const isMajor = isLarge || source === 'TDX' || portClass === '客運港' || portClass === '第一類漁港';
    return { name, position: [lon, lat], radius, isLarge, isMajor, portClass };
  });
}

/**
 * 建立港口視覺化圖層。
 * @param {Array} portFeatures - ports.geojson features
 * @param {string} theme - 'day' | 'night'
 * @param {number} zoom - 當前地圖 zoom level（控制漁港標籤顯示）
 * @returns {Array} deck.gl layers
 */
export function createPortLayers(portFeatures, theme = 'day', zoom = 7) {
  const data = preparePortData(portFeatures);
  const isDark = theme === 'night';

  // 根據 zoom 決定顯示哪些標籤（避免 277 個擠在一起）
  const majorPorts = data.filter(d => d.isMajor);
  const labelData = zoom >= 9 ? data : majorPorts;

  // 圍欄半徑圓（半透明填充 + 描邊）
  const radiusLayer = new ScatterplotLayer({
    id: 'port-radius',
    data,
    getPosition: d => d.position,
    getRadius: d => d.radius,
    radiusUnits: 'meters',
    filled: true,
    stroked: true,
    getFillColor: isDark ? [100, 180, 255, 15] : [30, 120, 220, 20],
    getLineColor: isDark ? [100, 180, 255, 80] : [30, 120, 220, 60],
    getLineWidth: 1,
    lineWidthUnits: 'pixels',
    pickable: false,
  });

  // 港口中心點
  const dotLayer = new ScatterplotLayer({
    id: 'port-dots',
    data,
    getPosition: d => d.position,
    getRadius: d => d.isLarge ? 5 : d.isMajor ? 4 : 3,
    radiusUnits: 'pixels',
    radiusMinPixels: 2,
    radiusMaxPixels: 6,
    filled: true,
    getFillColor: isDark ? [140, 200, 255, 200] : [30, 100, 200, 200],
    pickable: false,
  });

  // 港口名稱（根據 zoom 控制顯示密度）
  const labelLayer = new TextLayer({
    id: 'port-labels',
    data: labelData,
    getPosition: d => d.position,
    getText: d => d.name,
    getSize: d => d.isLarge ? 13 : d.isMajor ? 11 : 10,
    getColor: isDark ? [200, 220, 255, 200] : [20, 60, 140, 200],
    getTextAnchor: 'start',
    getAlignmentBaseline: 'center',
    getPixelOffset: [8, 0],
    fontFamily: '"Noto Sans TC", "PingFang TC", sans-serif',
    fontWeight: 500,
    outlineWidth: 2,
    outlineColor: isDark ? [0, 0, 0, 180] : [255, 255, 255, 200],
    billboard: false,
    sizeUnits: 'pixels',
    sizeMinPixels: 9,
    sizeMaxPixels: 14,
    pickable: false,
  });

  return [radiusLayer, dotLayer, labelLayer];
}
