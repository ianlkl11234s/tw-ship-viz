/**
 * 資料載入模組
 * 優先載入 Arrow IPC 格式，失敗時 fallback 到 JSON。
 */
import { tableFromIPC } from 'apache-arrow';

/**
 * 載入 Arrow 檔案，返回 Arrow Table。
 * @param {string} url - Arrow 檔案 URL
 * @returns {Promise<import('apache-arrow').Table>}
 */
async function loadArrow(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Failed to fetch ${url}: ${response.status}`);
  const buffer = await response.arrayBuffer();
  return tableFromIPC(buffer);
}

/**
 * 從 Arrow Table 的 schema metadata 提取資訊。
 * @param {import('apache-arrow').Table} table
 * @returns {object} metadata object
 */
export function getArrowMetadata(table) {
  const meta = table.schema.metadata;
  if (!meta) return {};

  const get = (key) => {
    const val = meta.get(key);
    return val || null;
  };

  const baseTimestamp = parseFloat(get('base_timestamp') || '0');
  const frameTimes = (get('frame_times') || '')
    .split(',')
    .filter(Boolean)
    .map(Number);

  return {
    baseTimestamp,
    baseDatetime: get('base_datetime') || '',
    endDatetime: get('end_datetime') || '',
    totalFrames: parseInt(get('total_frames') || '0', 10),
    intervalMinutes: parseInt(get('interval_minutes') || '10', 10),
    frameTimes,
  };
}

/**
 * 載入軌跡資料（Arrow 優先，JSON fallback）。
 * 返回統一的資料結構。
 */
export async function loadTrajectoryData() {
  try {
    console.log('[loader] 嘗試載入 trajectory.arrow...');
    const table = await loadArrow('/data/trajectory.arrow');
    const metadata = getArrowMetadata(table);
    console.log(`[loader] Arrow 載入成功: ${table.numRows} 筆, ${metadata.totalFrames} 幀`);
    return { type: 'arrow', table, metadata };
  } catch (arrowErr) {
    console.warn('[loader] Arrow 載入失敗，嘗試 JSON fallback:', arrowErr.message);
  }

  // JSON fallback
  try {
    const res = await fetch('/ship_trajectory_data.json');
    const json = await res.json();
    console.log(`[loader] JSON fallback 載入成功: ${json.metadata.total_frames} 幀`);
    return { type: 'json', data: json, metadata: json.metadata };
  } catch (jsonErr) {
    console.error('[loader] JSON 也載入失敗:', jsonErr);
    throw new Error('無法載入軌跡資料');
  }
}

/**
 * 載入密度/位置資料（Arrow 優先，JSON fallback）。
 */
export async function loadPositionsData() {
  try {
    console.log('[loader] 嘗試載入 positions.arrow...');
    const table = await loadArrow('/data/positions.arrow');
    const metadata = getArrowMetadata(table);
    console.log(`[loader] Arrow 載入成功: ${table.numRows} 筆, ${metadata.totalFrames} 幀`);
    return { type: 'arrow', table, metadata };
  } catch (arrowErr) {
    console.warn('[loader] Arrow 載入失敗，嘗試 JSON fallback:', arrowErr.message);
  }

  // JSON fallback
  try {
    const res = await fetch('/ship_density_data.json');
    const json = await res.json();
    console.log(`[loader] JSON fallback 載入成功: ${json.metadata.total_frames} 幀`);
    return { type: 'json', data: json, metadata: json.metadata };
  } catch (jsonErr) {
    console.error('[loader] JSON 也載入失敗:', jsonErr);
    throw new Error('無法載入位置資料');
  }
}
