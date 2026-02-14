#!/usr/bin/env python3
"""
從 SQLite 產出 Apache Arrow IPC 檔案，供前端 deck.gl 使用。

產出兩個檔案：
  - positions.arrow: 所有船舶位置（密度/六角/熱力圖模式用）
  - trajectory.arrow: 僅移動中船舶（sog > 0.5），按 MMSI 排序（軌跡動畫用）

用法:
  python3 generate_arrow.py --days 7
  python3 generate_arrow.py --start 2026-02-05 --end 2026-02-12
"""

import argparse
import math
import os
import sqlite3
from datetime import datetime, timedelta

import pyarrow as pa
import pyarrow.ipc as ipc

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), '..', 'data', 'ship_data.db'))
OUTPUT_DIR = os.environ.get('ARROW_OUTPUT_DIR', os.path.join(os.path.dirname(__file__), '..', 'frontend', 'public', 'data'))

# 地理範圍（台灣海域）
LON_MIN, LON_MAX = 117.0, 127.0
LAT_MIN, LAT_MAX = 20.0, 28.0

INTERVAL_MINUTES = 10
MAX_SPEED_KNOTS = 40   # 隱含速度閾值（節）— 高速船可達 35 節，留餘量
MAX_GAP_SECONDS = 21600 # 超過 6 小時才拆分（錨點已橋接短暫停泊，6hr 足以涵蓋大部分漁撈作業）

# 無效 MMSI 黑名單：AIS 設備未正確設定或多船共用
MMSI_BLACKLIST = {
    0, 1, 111111111, 123456789, 200000000,
    666666666, 888888888, 999999999,
}
# 格式異常的 MMSI 前綴（如 x00000000，通常是未設定的佔位符）
def is_invalid_mmsi(mmsi_str):
    """判斷 MMSI 是否無效。"""
    try:
        m = int(mmsi_str)
    except (ValueError, TypeError):
        return True
    if m in MMSI_BLACKLIST:
        return True
    if m < 100000000 or m > 799999999:
        return True  # 有效 MMSI 為 9 位數，2xx-7xx 開頭
    # x00000000 佔位符模式
    if m % 1000000 == 0:
        return True
    return False


def haversine_nm(lon1, lat1, lon2, lat2):
    """計算兩點間距離（海浬）。"""
    R_NM = 3440.065  # 地球半徑（海浬）
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(a))


def is_jump(p1, p2):
    """判斷兩點之間是否為異常跳躍（純速度判斷）。"""
    dt_hours = (p2[0] - p1[0]) / 3600.0
    if dt_hours <= 0:
        return False
    dist = haversine_nm(p1[1], p1[2], p2[1], p2[2])
    speed = dist / dt_hours
    return speed > MAX_SPEED_KNOTS


def split_by_gap(points):
    """按時間間隔拆分為多段軌跡，降低 MMSI 共用的交叉汙染。"""
    if not points:
        return []
    segments = []
    current = [points[0]]
    for i in range(1, len(points)):
        if points[i][0] - points[i - 1][0] > MAX_GAP_SECONDS:
            segments.append(current)
            current = []
        current.append(points[i])
    if current:
        segments.append(current)
    return segments


def filter_track_outliers(points):
    """過濾單艘船軌跡中的 GPS 跳點。

    改進策略：
    1. 先按時間間隔拆段（降低 MMSI 共用導致的交叉汙染）
    2. 每段內用滑動窗口過濾：
       - 當前點與前一有效點跳躍 → 檢查下一點來判斷誰是壞點
       - 連續多個跳點 → 全部丟棄直到找到與已知好點連續的位置
    points: [(ts_sec, lon, lat, sog, cog, vtype), ...]（已按時間排序）
    """
    if len(points) <= 1:
        return points

    all_clean = []
    for segment in split_by_gap(points):
        if len(segment) <= 1:
            all_clean.extend(segment)
            continue

        filtered = [segment[0]]
        i = 1
        consecutive_bad = 0  # 連續被判定為壞點的計數

        while i < len(segment):
            prev = filtered[-1]
            curr = segment[i]

            if not is_jump(prev, curr):
                filtered.append(curr)
                consecutive_bad = 0
                i += 1
                continue

            # curr 看起來是跳點 — 往前看一個點決定
            if i + 1 < len(segment):
                nxt = segment[i + 1]
                curr_to_nxt_ok = not is_jump(curr, nxt)
                prev_to_nxt_ok = not is_jump(prev, nxt)

                if curr_to_nxt_ok and not prev_to_nxt_ok:
                    # prev 是壞點，curr→nxt 連續 → 替換 prev
                    filtered[-1] = curr
                    consecutive_bad = 0
                    i += 1
                    continue

            # curr 是壞點，跳過
            consecutive_bad += 1
            # 若連續 5+ 個壞點，表示可能是 MMSI 共用造成的持續跳躍
            # 放棄整段後續（已經無法判斷哪邊是真的）
            if consecutive_bad >= 5:
                break
            i += 1

        all_clean.extend(filtered)

    return all_clean


def align_time(ts_str, interval_min=INTERVAL_MINUTES):
    """將時間戳對齊到最近的 interval 分鐘邊界。"""
    dt = datetime.fromisoformat(ts_str)
    minutes = (dt.minute // interval_min) * interval_min
    return dt.replace(minute=minutes, second=0, microsecond=0)


def get_time_range(args, cursor):
    """計算查詢時間範圍。"""
    if args.start and args.end:
        return args.start, args.end

    cursor.execute("SELECT MAX(timestamp) FROM ship_positions")
    max_ts = cursor.fetchone()[0]
    if not max_ts:
        raise ValueError("資料庫為空")

    end_dt = datetime.fromisoformat(max_ts)
    start_dt = end_dt - timedelta(days=args.days)
    return start_dt.isoformat(), end_dt.isoformat()


def generate_arrow_files(args):
    db_path = args.db_path or DB_PATH
    output_dir = args.output_dir or OUTPUT_DIR

    os.makedirs(output_dir, exist_ok=True)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()

    start_ts, end_ts = get_time_range(args, cursor)
    print(f"時間範圍: {start_ts} ~ {end_ts}")

    # 查詢所有資料
    cursor.execute("""
        SELECT mmsi, timestamp, lon, lat, sog, cog, vessel_type
        FROM ship_positions
        WHERE timestamp >= ? AND timestamp <= ?
          AND lon >= ? AND lon <= ?
          AND lat >= ? AND lat <= ?
        ORDER BY timestamp, mmsi
    """, (start_ts, end_ts, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX))

    # 收集並按時間對齊
    time_slots = {}  # aligned_ts → {mmsi: (lon, lat, sog, cog, vtype)}
    row_count = 0
    skipped_mmsi = 0
    for mmsi, ts, lon, lat, sog, cog, vtype in cursor:
        if is_invalid_mmsi(mmsi):
            skipped_mmsi += 1
            continue
        aligned = align_time(ts)
        key = aligned.isoformat()
        if key not in time_slots:
            time_slots[key] = {}
        # 同一時間段同一艘船只保留最後一筆
        time_slots[key][mmsi] = (lon, lat, sog or 0, cog or 0, vtype or 0)
        row_count += 1

    conn.close()
    print(f"原始資料: {row_count} 筆, 時間幀: {len(time_slots)} 個")
    if skipped_mmsi > 0:
        print(f"已過濾無效 MMSI: {skipped_mmsi} 筆")

    # 計算 base_timestamp（最小時間的 unix epoch）
    sorted_times = sorted(time_slots.keys())
    base_dt = datetime.fromisoformat(sorted_times[0])
    base_ts = base_dt.timestamp()

    # === 產出 positions.arrow（所有船舶）===
    pos_timestamps = []
    pos_mmsi = []
    pos_lon = []
    pos_lat = []
    pos_sog = []
    pos_cog = []
    pos_vtype = []

    for ts_key in sorted_times:
        ts_sec = datetime.fromisoformat(ts_key).timestamp() - base_ts
        ships = time_slots[ts_key]
        for mmsi, (lon, lat, sog, cog, vtype) in ships.items():
            pos_timestamps.append(ts_sec)
            pos_mmsi.append(int(mmsi) if isinstance(mmsi, str) else mmsi)
            pos_lon.append(lon)
            pos_lat.append(lat)
            pos_sog.append(sog)
            pos_cog.append(cog)
            pos_vtype.append(vtype)

    pos_table = pa.table({
        'timestamp': pa.array(pos_timestamps, type=pa.float32()),
        'mmsi': pa.array(pos_mmsi, type=pa.uint32()),
        'lon': pa.array(pos_lon, type=pa.float32()),
        'lat': pa.array(pos_lat, type=pa.float32()),
        'sog': pa.array(pos_sog, type=pa.float32()),
        'cog': pa.array(pos_cog, type=pa.float32()),
        'vessel_type': pa.array(pos_vtype, type=pa.uint8()),
    })

    # metadata：存入 base_timestamp 和時間幀資訊
    metadata = {
        b'base_timestamp': str(base_ts).encode(),
        b'base_datetime': sorted_times[0].encode(),
        b'end_datetime': sorted_times[-1].encode(),
        b'total_frames': str(len(sorted_times)).encode(),
        b'interval_minutes': str(INTERVAL_MINUTES).encode(),
        b'frame_times': ','.join(f"{(datetime.fromisoformat(t).timestamp() - base_ts):.0f}" for t in sorted_times).encode(),
    }
    pos_table = pos_table.replace_schema_metadata(metadata)

    pos_path = os.path.join(output_dir, 'positions.arrow')
    with ipc.RecordBatchFileWriter(pos_path, pos_table.schema) as writer:
        writer.write_table(pos_table)
    pos_size = os.path.getsize(pos_path) / 1024 / 1024
    print(f"positions.arrow: {len(pos_timestamps)} 筆, {pos_size:.1f} MB")

    # === 產出 trajectory.arrow（僅移動中船舶，按 MMSI 排序）===
    traj_timestamps = []
    traj_mmsi = []
    traj_lon = []
    traj_lat = []
    traj_sog = []
    traj_cog = []
    traj_vtype = []

    # 按 MMSI 分組收集（TripsLayer 需要按船分組的軌跡）
    # 策略：低速點（sog < 0.5）不全部保留，只保留「錨點」—
    #   移動→停 的第一個低速點 + 停→移動 的第一個高速點前的最後低速點
    #   這樣軌跡連續，停泊期間船會停在原地，不會產生時間斷裂
    ship_all_points = {}  # mmsi → [(ts_sec, lon, lat, sog, cog, vtype), ...]
    for ts_key in sorted_times:
        ts_sec = datetime.fromisoformat(ts_key).timestamp() - base_ts
        ships = time_slots[ts_key]
        for mmsi, (lon, lat, sog, cog, vtype) in ships.items():
            mmsi_int = int(mmsi) if isinstance(mmsi, str) else mmsi
            if mmsi_int not in ship_all_points:
                ship_all_points[mmsi_int] = []
            ship_all_points[mmsi_int].append((ts_sec, lon, lat, sog, cog, vtype))

    # 過濾：保留移動中的點 + 停泊錨點
    ship_tracks = {}
    anchored_dropped = 0
    for mmsi_int, points in ship_all_points.items():
        filtered = []
        for i, pt in enumerate(points):
            sog = pt[3]
            if sog >= 0.5:
                # 移動中 → 一律保留
                filtered.append(pt)
            else:
                # 低速點：只保留「邊界」錨點
                prev_moving = (i > 0 and points[i - 1][3] >= 0.5)
                next_moving = (i < len(points) - 1 and points[i + 1][3] >= 0.5)
                if prev_moving or next_moving:
                    filtered.append(pt)
                else:
                    anchored_dropped += 1
        if filtered:
            ship_tracks[mmsi_int] = filtered

    if anchored_dropped > 0:
        print(f"已跳過連續停泊點: {anchored_dropped} 筆（保留錨點）")

    # 按 MMSI 排序，過濾跳點後展開
    outlier_count = 0
    for mmsi_int in sorted(ship_tracks.keys()):
        raw_points = ship_tracks[mmsi_int]
        clean_points = filter_track_outliers(raw_points)
        outlier_count += len(raw_points) - len(clean_points)
        for ts_sec, lon, lat, sog, cog, vtype in clean_points:
            traj_timestamps.append(ts_sec)
            traj_mmsi.append(mmsi_int)
            traj_lon.append(lon)
            traj_lat.append(lat)
            traj_sog.append(sog)
            traj_cog.append(cog)
            traj_vtype.append(vtype)
    if outlier_count > 0:
        print(f"已過濾 GPS 跳點: {outlier_count} 筆")

    traj_table = pa.table({
        'timestamp': pa.array(traj_timestamps, type=pa.float32()),
        'mmsi': pa.array(traj_mmsi, type=pa.uint32()),
        'lon': pa.array(traj_lon, type=pa.float32()),
        'lat': pa.array(traj_lat, type=pa.float32()),
        'sog': pa.array(traj_sog, type=pa.float32()),
        'cog': pa.array(traj_cog, type=pa.float32()),
        'vessel_type': pa.array(traj_vtype, type=pa.uint8()),
    })

    traj_table = traj_table.replace_schema_metadata(metadata)

    traj_path = os.path.join(output_dir, 'trajectory.arrow')
    with ipc.RecordBatchFileWriter(traj_path, traj_table.schema) as writer:
        writer.write_table(traj_table)
    traj_size = os.path.getsize(traj_path) / 1024 / 1024
    print(f"trajectory.arrow: {len(traj_timestamps)} 筆 ({len(ship_tracks)} 艘船), {traj_size:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description='從 SQLite 產出 Arrow IPC 檔案')
    parser.add_argument('--days', type=int, default=7, help='取最近 N 天資料（預設 7）')
    parser.add_argument('--start', type=str, help='起始時間 (ISO 格式)')
    parser.add_argument('--end', type=str, help='結束時間 (ISO 格式)')
    parser.add_argument('--db-path', type=str, help=f'SQLite 路徑（預設 {DB_PATH}）')
    parser.add_argument('--output-dir', type=str, help=f'輸出目錄（預設 {OUTPUT_DIR}）')
    args = parser.parse_args()

    generate_arrow_files(args)
    print('完成!')


if __name__ == '__main__':
    main()
