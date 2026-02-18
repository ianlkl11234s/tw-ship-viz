/**
 * 資料載入模組
 * 優先載入 Arrow IPC 格式，失敗時 fallback 到 JSON。
 * 支援 manifest.json 漸進式載入（按日分檔）。
 */
import { tableFromIPC } from 'apache-arrow';
import { MultiDayFrameIndex } from './transform.js';

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

/**
 * 漸進式載入位置資料（manifest.json → 按日分檔）。
 *
 * 三層 Fallback：
 * 1. manifest.json 存在 → MultiDayFrameIndex + 漸進式載入
 * 2. manifest 不存在 + positions.arrow 存在 → 原有 FrameIndex
 * 3. Arrow 全部失敗 → JSON fallback
 *
 * @param {function} onProgress - 進度回調 ({ loaded, total })
 */
export async function loadPositionsProgressive(onProgress) {
  // 嘗試載入 manifest
  let manifest = null;
  try {
    const res = await fetch('/data/manifest.json');
    if (res.ok) manifest = await res.json();
  } catch { /* manifest 不存在，fallback */ }

  if (!manifest || manifest.version < 2) {
    console.log('[loader] manifest.json 不存在或版本不符，fallback 到單檔載入');
    return loadPositionsData();
  }

  const days = manifest.positions.days;
  console.log(`[loader] manifest.json 載入成功, ${days.length} 天, ${manifest.positions.total_frames} 幀`);

  const store = new MultiDayFrameIndex(manifest);

  // Phase 1: 最近 2 天（立即可互動）
  const recentCount = Math.min(2, days.length);
  const recent = days.slice(-recentCount);
  const tables = await Promise.all(recent.map(d => loadArrow(`/data/${d.file}`)));
  recent.forEach((d, i) => store.addDay(d.date, tables[i]));
  if (onProgress) onProgress({ loaded: recentCount, total: days.length });

  // Phase 2: 背景逐日載入其餘天數（不阻塞互動）
  const older = days.slice(0, -recentCount);
  if (older.length > 0) {
    (async () => {
      for (const day of older) {
        try {
          const table = await loadArrow(`/data/${day.file}`);
          store.addDay(day.date, table);
          if (onProgress) onProgress({ loaded: store.loadedDays, total: days.length });
        } catch (err) {
          console.warn(`[loader] 背景載入 ${day.file} 失敗:`, err.message);
        }
      }
      console.log(`[loader] 全部 ${days.length} 天載入完成`);
    })();
  }

  return {
    type: 'multi-day',
    store,
    metadata: {
      baseTimestamp: manifest.base_timestamp,
      baseDatetime: manifest.base_datetime,
      endDatetime: manifest.end_datetime,
      totalFrames: manifest.positions.total_frames,
      intervalMinutes: manifest.interval_minutes,
      frameTimes: store.frameTimes,
    },
  };
}
