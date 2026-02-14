/**
 * 資料轉換模組
 * 將 Arrow Table 轉換為 deck.gl 各 Layer 所需的資料結構。
 */

/**
 * Arrow Table → TripsLayer 資料
 *
 * TripsLayer 需要:
 * [{
 *   mmsi: number,
 *   vesselType: number,
 *   path: [[lon, lat, timestamp], ...],  // 時間排序
 *   timestamps: [t0, t1, ...],
 * }, ...]
 *
 * @param {import('apache-arrow').Table} table - trajectory.arrow Table
 * @returns {Array} trips data array
 */
export function arrowToTrips(table) {
  const numRows = table.numRows;
  const tsCol = table.getChild('timestamp');
  const mmsiCol = table.getChild('mmsi');
  const lonCol = table.getChild('lon');
  const latCol = table.getChild('lat');
  const sogCol = table.getChild('sog');
  const cogCol = table.getChild('cog');
  const vtypeCol = table.getChild('vessel_type');

  const MAX_GAP = 21600;     // 6 小時：短暫停泊靠錨點橋接，長停泊才切斷
  const MAX_SPEED_KT = 40;   // 速度閾值（節）：超過此值視為異常跳躍
  const DEG_PER_NM = 1 / 60; // 1 海浬 ≈ 1/60 度
  const MIN_POINTS = 3;      // 最少 3 個點才保留

  // trajectory.arrow 已按 MMSI 排序，直接線性掃描分組
  const trips = [];
  let currentMmsi = null;
  let currentTrip = null;

  for (let i = 0; i < numRows; i++) {
    const mmsi = mmsiCol.get(i);
    const ts = tsCol.get(i);
    const lon = lonCol.get(i);
    const lat = latCol.get(i);

    let shouldSplit = mmsi !== currentMmsi;

    if (!shouldSplit && currentTrip && currentTrip.path.length > 0) {
      const lastTs = currentTrip.timestamps[currentTrip.timestamps.length - 1];
      const lastPos = currentTrip.path[currentTrip.path.length - 1];
      const dt = ts - lastTs;

      if (dt > MAX_GAP) {
        shouldSplit = true;
      } else if (dt > 0) {
        const dLon = Math.abs(lon - lastPos[0]);
        const dLat = Math.abs(lat - lastPos[1]);
        const distNm = Math.sqrt(dLon * dLon + dLat * dLat) / DEG_PER_NM;
        const dtHours = dt / 3600;
        const speedKt = distNm / dtHours;
        if (speedKt > MAX_SPEED_KT) {
          shouldSplit = true;
        }
      }
    }

    if (shouldSplit) {
      if (currentTrip && currentTrip.path.length >= MIN_POINTS) trips.push(currentTrip);
      currentMmsi = mmsi;
      currentTrip = {
        mmsi,
        vesselType: vtypeCol.get(i),
        path: [],
        timestamps: [],
      };
    }
    currentTrip.path.push([lon, lat]);
    currentTrip.timestamps.push(ts);
  }
  if (currentTrip && currentTrip.path.length >= MIN_POINTS) trips.push(currentTrip);

  console.log(`[transform] arrowToTrips: ${trips.length} 航段`);
  return trips;
}

/**
 * Arrow Table → 按時間幀分組的位置資料
 *
 * 用於密度/六角/熱力圖模式：給定一個 frame 的 timestamp，
 * 返回該幀的所有船舶位置。
 *
 * 回傳一個 FrameIndex 物件，可快速按幀查詢。
 *
 * @param {import('apache-arrow').Table} table - positions.arrow Table
 * @param {number[]} frameTimes - 所有幀的 timestamp 陣列
 * @returns {FrameIndex}
 */
export function buildFrameIndex(table, frameTimes) {
  const numRows = table.numRows;
  const tsCol = table.getChild('timestamp');

  // 建立每個 frame 的起始 row index（因為 positions.arrow 按 timestamp 排序）
  // 使用二分搜尋找每個 frame 的邊界
  const frameStartIndices = [];
  let searchFrom = 0;

  for (const ft of frameTimes) {
    // 找第一個 timestamp >= ft 的 row
    let lo = searchFrom;
    let hi = numRows;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (tsCol.get(mid) < ft) lo = mid + 1;
      else hi = mid;
    }
    frameStartIndices.push(lo);
    searchFrom = lo;
  }
  // 加入結尾哨兵
  frameStartIndices.push(numRows);

  return new FrameIndex(table, frameTimes, frameStartIndices);
}

/**
 * 幀索引，支援快速按幀查詢船舶位置。
 */
class FrameIndex {
  constructor(table, frameTimes, frameStartIndices) {
    this._table = table;
    this._frameTimes = frameTimes;
    this._starts = frameStartIndices;
    this._lonCol = table.getChild('lon');
    this._latCol = table.getChild('lat');
    this._sogCol = table.getChild('sog');
    this._cogCol = table.getChild('cog');
    this._vtypeCol = table.getChild('vessel_type');
    this._mmsiCol = table.getChild('mmsi');
  }

  get totalFrames() {
    return this._frameTimes.length;
  }

  get frameTimes() {
    return this._frameTimes;
  }

  /**
   * 取得指定幀的船舶數量（不建立陣列，用於統計面板）。
   */
  getFrameCount(frameIdx) {
    if (frameIdx < 0 || frameIdx >= this._frameTimes.length) return 0;
    return this._starts[frameIdx + 1] - this._starts[frameIdx];
  }

  /**
   * 取得指定幀的所有船舶位置。
   * @param {number} frameIdx - 幀索引
   * @param {Set|null} vesselFilter - 允許的 vessel_type 集合，null 表示不篩選
   * @returns {Array<{position: [number, number], sog: number, cog: number, vesselType: number, mmsi: number}>}
   */
  getFrame(frameIdx, vesselFilter = null) {
    if (frameIdx < 0 || frameIdx >= this._frameTimes.length) return [];

    const start = this._starts[frameIdx];
    const end = this._starts[frameIdx + 1];
    const positions = [];

    for (let i = start; i < end; i++) {
      const vtype = this._vtypeCol.get(i);
      if (vesselFilter && !vesselFilter.has(vtype)) continue;
      positions.push({
        position: [this._lonCol.get(i), this._latCol.get(i)],
        sog: this._sogCol.get(i),
        cog: this._cogCol.get(i),
        vesselType: vtype,
        mmsi: this._mmsiCol.get(i),
      });
    }
    return positions;
  }

  /**
   * 取得指定幀的位置資料（TypedArray 格式，零物件分配）。
   * 供 HeatmapLayer binary attributes 使用。
   * @param {number} frameIdx
   * @returns {{ positions: Float32Array, count: number } | null}
   */
  getFramePositionsFlat(frameIdx) {
    if (frameIdx < 0 || frameIdx >= this._frameTimes.length) return null;
    const start = this._starts[frameIdx];
    const end = this._starts[frameIdx + 1];
    const count = end - start;
    const positions = new Float32Array(count * 2);
    for (let i = start; i < end; i++) {
      const j = (i - start) * 2;
      positions[j] = this._lonCol.get(i);
      positions[j + 1] = this._latCol.get(i);
    }
    return { positions, count };
  }

  /**
   * 取得指定幀的熱力圖資料（空間預聚合 + TypedArray）。
   *
   * 將 ~12,000 個點聚合為 ~2,000 個帶權重的格子，大幅降低 GPU KDE 負擔。
   * cellSize 0.03° ≈ 3.3km，在 HeatmapLayer radiusPixels=40 下聚合效果平滑。
   *
   * @param {number} frameIdx
   * @param {number} cellSize - 聚合格子大小（度）
   * @returns {{ positions: Float32Array, weights: Float32Array, count: number } | null}
   */
  getFrameHeatmapData(frameIdx, cellSize = 0.03) {
    if (frameIdx < 0 || frameIdx >= this._frameTimes.length) return null;
    const start = this._starts[frameIdx];
    const end = this._starts[frameIdx + 1];
    if (start >= end) return null;

    const cellInv = 1 / cellSize;
    const grid = new Map();

    for (let i = start; i < end; i++) {
      const lon = this._lonCol.get(i);
      const lat = this._latCol.get(i);
      // 整數格子 key（數值 key 比字串快）
      const cx = Math.round(lon * cellInv);
      const cy = Math.round(lat * cellInv);
      const key = cx * 100000 + cy;

      const cell = grid.get(key);
      if (cell) {
        cell[0] += lon;
        cell[1] += lat;
        cell[2]++;
      } else {
        grid.set(key, [lon, lat, 1]);
      }
    }

    const count = grid.size;
    const positions = new Float32Array(count * 2);
    const weights = new Float32Array(count);
    let idx = 0;
    for (const cell of grid.values()) {
      const w = cell[2];
      positions[idx * 2] = cell[0] / w;     // centroid lon
      positions[idx * 2 + 1] = cell[1] / w; // centroid lat
      weights[idx] = w;
      idx++;
    }

    return { positions, weights, count };
  }

  /**
   * 取得指定幀的 [lon, lat, weight] 陣列（HeatmapLayer 用）。
   */
  getFrameHeatData(frameIdx, vesselFilter = null) {
    if (frameIdx < 0 || frameIdx >= this._frameTimes.length) return [];

    const start = this._starts[frameIdx];
    const end = this._starts[frameIdx + 1];
    const data = [];

    for (let i = start; i < end; i++) {
      const vtype = this._vtypeCol.get(i);
      if (vesselFilter && !vesselFilter.has(vtype)) continue;
      data.push({
        position: [this._lonCol.get(i), this._latCol.get(i)],
        weight: 1,
      });
    }
    return data;
  }
}

/**
 * JSON fallback: 將舊版 trajectory JSON 轉為 TripsLayer 格式。
 * @param {object} jsonData - 舊版 ship_trajectory_data.json
 * @returns {Array} trips data
 */
export function jsonToTrips(jsonData) {
  const frames = jsonData.frames;
  const baseDt = new Date(frames[0].time);
  const baseTs = baseDt.getTime() / 1000;

  // 按 MMSI 收集所有幀的位置
  const shipMap = new Map();
  for (const frame of frames) {
    const ts = (new Date(frame.time).getTime() / 1000) - baseTs;
    for (const [mmsi, data] of Object.entries(frame.ships)) {
      const [lon, lat, sog, cog, vtype] = data;
      if (!shipMap.has(mmsi)) {
        shipMap.set(mmsi, { mmsi: parseInt(mmsi), vesselType: vtype, path: [], timestamps: [] });
      }
      const trip = shipMap.get(mmsi);
      trip.path.push([lon, lat]);
      trip.timestamps.push(ts);
    }
  }

  const trips = Array.from(shipMap.values());
  console.log(`[transform] jsonToTrips: ${trips.length} 艘船`);
  return trips;
}

/**
 * JSON fallback: 將舊版 density JSON 建立成簡易 FrameIndex。
 */
export function jsonToFrameIndex(jsonData) {
  const frames = jsonData.frames;
  const baseDt = new Date(frames[0].time);
  const baseTs = baseDt.getTime() / 1000;

  const frameTimes = frames.map(f => (new Date(f.time).getTime() / 1000) - baseTs);

  return {
    totalFrames: frames.length,
    frameTimes,
    getFrame(frameIdx, vesselFilter = null) {
      if (frameIdx < 0 || frameIdx >= frames.length) return [];
      return frames[frameIdx].ships
        .filter(s => !vesselFilter || vesselFilter.has(s[2]))
        .map(([lon, lat, vtype]) => ({
          position: [lon, lat],
          sog: 0,
          cog: 0,
          vesselType: vtype,
          mmsi: 0,
        }));
    },
    getFrameHeatData(frameIdx, vesselFilter = null) {
      if (frameIdx < 0 || frameIdx >= frames.length) return [];
      return frames[frameIdx].ships
        .filter(s => !vesselFilter || vesselFilter.has(s[2]))
        .map(([lon, lat]) => ({ position: [lon, lat], weight: 1 }));
    },
  };
}
