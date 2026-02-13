import { VESSEL_CODE_TO_CATEGORY } from '../utils/constants.js';

/**
 * 將 Arrow trajectory table 轉為 TripsLayer 所需的資料結構。
 *
 * Arrow 表結構：timestamp(f32), mmsi(u32), lon(f32), lat(f32), sog(f32), cog(f32), vessel_type(u8)
 * 已按 mmsi 排序，同一艘船的記錄連續排列。
 *
 * 輸出：[{ mmsi, vessel_type, category, path: [[lon, lat, timestamp], ...] }, ...]
 */
export function transformTrajectoryArrow(table) {
  const numRows = table.numRows;
  const tsCol = table.getChild('timestamp');
  const mmsiCol = table.getChild('mmsi');
  const lonCol = table.getChild('lon');
  const latCol = table.getChild('lat');
  const sogCol = table.getChild('sog');
  const cogCol = table.getChild('cog');
  const vtCol = table.getChild('vessel_type');

  const trips = [];
  let currentMmsi = null;
  let currentTrip = null;

  for (let i = 0; i < numRows; i++) {
    const mmsi = mmsiCol.get(i);
    if (mmsi !== currentMmsi) {
      // 新的一艘船
      if (currentTrip) trips.push(currentTrip);
      const vtype = vtCol.get(i);
      currentTrip = {
        mmsi,
        vessel_type: vtype,
        category: VESSEL_CODE_TO_CATEGORY[vtype] || 'unknown',
        path: [],
        timestamps: [],
        speeds: [],
      };
      currentMmsi = mmsi;
    }
    currentTrip.path.push([lonCol.get(i), latCol.get(i)]);
    currentTrip.timestamps.push(tsCol.get(i));
    currentTrip.speeds.push(sogCol.get(i));
  }
  if (currentTrip) trips.push(currentTrip);

  console.log(`[transform] 軌跡: ${trips.length} 艘船`);
  return trips;
}

/**
 * 將 Arrow positions table 轉為 per-frame 資料結構。
 *
 * 輸出：{
 *   frameTimes: [0, 600, 1200, ...],  // 秒（相對於 base）
 *   baseTimestamp: number,             // unix epoch
 *   baseDatetime: string,              // ISO string
 *   frames: Map<number, [{lon, lat, sog, cog, vessel_type, category}, ...]>
 * }
 */
export function transformPositionsArrow(table, metadata) {
  const numRows = table.numRows;
  const tsCol = table.getChild('timestamp');
  const lonCol = table.getChild('lon');
  const latCol = table.getChild('lat');
  const sogCol = table.getChild('sog');
  const cogCol = table.getChild('cog');
  const vtCol = table.getChild('vessel_type');

  // 解析 metadata
  const baseTimestamp = parseFloat(metadata.base_timestamp);
  const baseDatetime = metadata.base_datetime;
  const endDatetime = metadata.end_datetime;
  const frameTimes = metadata.frame_times
    .split(',')
    .map(Number);

  // 按 timestamp 分組
  const frames = new Map();
  for (let i = 0; i < numRows; i++) {
    const ts = tsCol.get(i);
    // 四捨五入到最近的整數秒（避免浮點誤差）
    const tsKey = Math.round(ts);

    if (!frames.has(tsKey)) {
      frames.set(tsKey, []);
    }
    const vtype = vtCol.get(i);
    frames.get(tsKey).push({
      position: [lonCol.get(i), latCol.get(i)],
      sog: sogCol.get(i),
      cog: cogCol.get(i),
      vessel_type: vtype,
      category: VESSEL_CODE_TO_CATEGORY[vtype] || 'unknown',
    });
  }

  console.log(`[transform] 位置: ${frames.size} 幀, ${numRows} 筆`);
  return { frameTimes, baseTimestamp, baseDatetime, endDatetime, frames };
}

/**
 * JSON fallback 轉換：將舊版 trajectory JSON 轉為 TripsLayer 資料。
 */
export function transformTrajectoryJson(data) {
  const frames = data.frames;
  if (!frames || frames.length === 0) return [];

  // 從 metadata 取得 base timestamp
  const baseStr = data.metadata.date_range.start;
  const baseDt = new Date(baseStr.replace(' ', 'T'));
  const baseSec = baseDt.getTime() / 1000;

  // 收集每艘船的軌跡
  const shipMap = new Map(); // mmsi → { path, timestamps, speeds, vessel_type }

  for (const frame of frames) {
    const frameDt = new Date(frame.time.replace(' ', 'T'));
    const frameSec = frameDt.getTime() / 1000 - baseSec;

    for (const [mmsi, shipData] of Object.entries(frame.ships)) {
      const [lon, lat, sog, cog, vtype] = shipData;
      if (!shipMap.has(mmsi)) {
        shipMap.set(mmsi, {
          mmsi: parseInt(mmsi),
          vessel_type: vtype,
          category: VESSEL_CODE_TO_CATEGORY[vtype] || 'unknown',
          path: [],
          timestamps: [],
          speeds: [],
        });
      }
      const ship = shipMap.get(mmsi);
      ship.path.push([lon, lat]);
      ship.timestamps.push(frameSec);
      ship.speeds.push(sog);
    }
  }

  const trips = Array.from(shipMap.values());
  console.log(`[transform] JSON fallback 軌跡: ${trips.length} 艘船`);
  return trips;
}

/**
 * JSON fallback 轉換：將舊版 density JSON 轉為 per-frame 資料。
 */
export function transformPositionsJson(data) {
  const frames = data.frames;
  if (!frames || frames.length === 0) {
    return { frameTimes: [], baseTimestamp: 0, baseDatetime: '', endDatetime: '', frames: new Map() };
  }

  const baseStr = data.metadata.date_range.start;
  const baseDt = new Date(baseStr.replace(' ', 'T'));
  const baseSec = baseDt.getTime() / 1000;

  const frameTimes = [];
  const frameMap = new Map();

  for (const frame of frames) {
    const frameDt = new Date(frame.time.replace(' ', 'T'));
    const frameSec = Math.round(frameDt.getTime() / 1000 - baseSec);
    frameTimes.push(frameSec);

    const ships = frame.ships.map(([lon, lat, vtype]) => ({
      position: [lon, lat],
      sog: 0,
      cog: 0,
      vessel_type: vtype,
      category: VESSEL_CODE_TO_CATEGORY[vtype] || 'unknown',
    }));
    frameMap.set(frameSec, ships);
  }

  const endStr = data.metadata.date_range.end;

  return {
    frameTimes,
    baseTimestamp: baseSec,
    baseDatetime: baseStr,
    endDatetime: endStr,
    frames: frameMap,
  };
}
