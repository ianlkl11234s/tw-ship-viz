import { tableFromIPC } from 'apache-arrow';

/**
 * 載入 Arrow IPC 檔案，失敗時 fallback 到 JSON。
 *
 * @param {'positions' | 'trajectory'} type
 * @returns {{ table, metadata }}
 */
export async function loadArrowData(type) {
  const arrowUrl = `./data/${type}.arrow`;
  const jsonFallbacks = {
    positions: '/ship_density_data.json',
    trajectory: '/ship_trajectory_data.json',
  };

  try {
    const res = await fetch(arrowUrl);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buffer = await res.arrayBuffer();
    const table = tableFromIPC(buffer);

    // 從 Arrow schema metadata 取出自訂 metadata
    const rawMeta = table.schema.metadata;
    const metadata = {};
    if (rawMeta) {
      for (const [k, v] of rawMeta) {
        metadata[k] = v;
      }
    }

    console.log(`[loader] ${type}.arrow 載入成功: ${table.numRows} 筆`);
    return { table, metadata, format: 'arrow' };
  } catch (err) {
    console.warn(`[loader] Arrow 載入失敗 (${err.message})，嘗試 JSON fallback...`);
    return loadJsonFallback(type, jsonFallbacks[type]);
  }
}

/**
 * JSON fallback 載入（相容舊版資料格式）。
 */
async function loadJsonFallback(type, url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`JSON fallback 也失敗: HTTP ${res.status}`);
  const data = await res.json();
  console.log(`[loader] ${type} JSON fallback 載入成功: ${data.frames?.length || 0} 幀`);
  return { data, metadata: data.metadata, format: 'json' };
}
