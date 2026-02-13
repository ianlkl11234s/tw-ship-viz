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
import os
import sqlite3
from datetime import datetime, timedelta

import pyarrow as pa
import pyarrow.ipc as ipc

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'ship_data.db')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'public', 'data')

# 地理範圍（台灣海域）
LON_MIN, LON_MAX = 117.0, 127.0
LAT_MIN, LAT_MAX = 20.0, 28.0

INTERVAL_MINUTES = 10


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
    time_slots = {}  # aligned_ts → [(mmsi, lon, lat, sog, cog, vtype), ...]
    row_count = 0
    for mmsi, ts, lon, lat, sog, cog, vtype in cursor:
        aligned = align_time(ts)
        key = aligned.isoformat()
        if key not in time_slots:
            time_slots[key] = {}
        # 同一時間段同一艘船只保留最後一筆
        time_slots[key][mmsi] = (lon, lat, sog or 0, cog or 0, vtype or 0)
        row_count += 1

    conn.close()
    print(f"原始資料: {row_count} 筆, 時間幀: {len(time_slots)} 個")

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
    ship_tracks = {}  # mmsi → [(ts_sec, lon, lat, sog, cog, vtype), ...]
    for ts_key in sorted_times:
        ts_sec = datetime.fromisoformat(ts_key).timestamp() - base_ts
        ships = time_slots[ts_key]
        for mmsi, (lon, lat, sog, cog, vtype) in ships.items():
            if sog < 0.5:
                continue
            mmsi_int = int(mmsi) if isinstance(mmsi, str) else mmsi
            if mmsi_int not in ship_tracks:
                ship_tracks[mmsi_int] = []
            ship_tracks[mmsi_int].append((ts_sec, lon, lat, sog, cog, vtype))

    # 按 MMSI 排序後展開
    for mmsi_int in sorted(ship_tracks.keys()):
        for ts_sec, lon, lat, sog, cog, vtype in ship_tracks[mmsi_int]:
            traj_timestamps.append(ts_sec)
            traj_mmsi.append(mmsi_int)
            traj_lon.append(lon)
            traj_lat.append(lat)
            traj_sog.append(sog)
            traj_cog.append(cog)
            traj_vtype.append(vtype)

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
