/**
 * 港口圖層
 * 顯示港口位置、名稱、圍欄半徑。
 */
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';

// 與後端 generate_arrow.py 一致
const PORT_RADIUS_M = 1500;       // 1.5 km
const LARGE_PORT_RADIUS_M = 3000; // 3.0 km
const LARGE_PORTS = new Set([
  '高雄港', '基隆港', '臺中港', '花蓮港', '台北港', '蘇澳港', '安平港',
]);

/**
 * 將 ports.geojson 的 features 轉為圖層資料。
 */
function preparePortData(features) {
  return features.map(f => {
    const name = f.properties.PortName;
    const [lon, lat] = f.geometry.coordinates;
    const radius = LARGE_PORTS.has(name) ? LARGE_PORT_RADIUS_M : PORT_RADIUS_M;
    return { name, position: [lon, lat], radius };
  });
}

/**
 * 建立港口視覺化圖層。
 * @param {Array} portFeatures - ports.geojson features
 * @param {string} theme - 'day' | 'night'
 * @returns {Array} deck.gl layers
 */
export function createPortLayers(portFeatures, theme = 'day') {
  const data = preparePortData(portFeatures);
  const isDark = theme === 'night';

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
    getRadius: 4,
    radiusUnits: 'pixels',
    radiusMinPixels: 3,
    radiusMaxPixels: 6,
    filled: true,
    getFillColor: isDark ? [140, 200, 255, 200] : [30, 100, 200, 200],
    pickable: false,
  });

  // 港口名稱
  const labelLayer = new TextLayer({
    id: 'port-labels',
    data,
    getPosition: d => d.position,
    getText: d => d.name,
    getSize: 12,
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
    sizeMinPixels: 10,
    sizeMaxPixels: 14,
    pickable: false,
  });

  return [radiusLayer, dotLayer, labelLayer];
}
