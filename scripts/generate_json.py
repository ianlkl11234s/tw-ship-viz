#!/usr/bin/env python3
"""
從 SQLite 產出密度和軌跡 JSON

SQLite 為唯一資料來源，不再直接從 S3 產 JSON。
輸出格式與 update_all.py 完全一致。
"""
import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from grid_utils import DensityGrid

TRAJECTORY_BOUNDS = {
    "lon_min": 117.0,
    "lon_max": 127.0,
    "lat_min": 20.0,
    "lat_max": 28.0,
}


def get_time_range(args):
    """根據參數計算時間範圍"""
    if args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    else:
        end = datetime.now()
        start = end - timedelta(days=args.days)
    return start, end


def align_time_key(timestamp_str, interval):
    """將時間戳對齊到指定間隔（與 update_all.py 邏輯一致）"""
    ts = datetime.fromisoformat(timestamp_str)
    if interval >= 60:
        return ts.strftime("%Y-%m-%d %H:00")
    aligned_minute = (ts.minute // interval) * interval
    return ts.strftime(f"%Y-%m-%d %H:{aligned_minute:02d}")


def generate_density_json(conn, start, end, interval, output_path):
    """產出密度 JSON（格式與 update_all.py 一致）"""
    print("正在產出密度資料...")

    start_str = start.isoformat()
    end_str = end.isoformat()

    rows = conn.execute(
        "SELECT timestamp, lon, lat, vessel_type "
        "FROM ship_positions "
        "WHERE timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp",
        (start_str, end_str)
    ).fetchall()

    print(f"  查詢到 {len(rows):,} 筆資料")

    # 按時間間隔分組
    time_data = {}
    for ts, lon, lat, vtype in rows:
        time_key = align_time_key(ts, interval)
        if time_key not in time_data:
            time_data[time_key] = []
        time_data[time_key].append([lon, lat, vtype or 0])

    # 建構輸出
    grid = DensityGrid()
    geo_info = grid.get_geo_info()
    time_keys = sorted(time_data.keys())

    frames = []
    total_ships = 0
    for time_key in time_keys:
        ships = time_data[time_key]
        total_ships += len(ships)
        frames.append({"time": time_key, "ships": ships})

    output = {
        "metadata": {
            "geo_info": geo_info,
            "total_frames": len(frames),
            "generated_at": datetime.now().isoformat(),
            "interval_minutes": interval,
            "date_range": {
                "start": time_keys[0] if time_keys else None,
                "end": time_keys[-1] if time_keys else None,
            }
        },
        "frames": frames,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  檔案：{output_path}")
    print(f"  大小：{size_mb:.2f} MB")
    print(f"  幀數：{len(frames)}")
    print(f"  總船次：{total_ships:,}")

    return len(frames)


def generate_trajectory_json(conn, start, end, interval, output_path):
    """產出軌跡 JSON（格式與 update_all.py 一致）"""
    print("\n正在產出軌跡資料...")

    start_str = start.isoformat()
    end_str = end.isoformat()

    rows = conn.execute(
        "SELECT timestamp, mmsi, lon, lat, sog, cog, vessel_type "
        "FROM ship_positions "
        "WHERE timestamp >= ? AND timestamp <= ? "
        "  AND sog > 0.5 "
        "ORDER BY timestamp",
        (start_str, end_str)
    ).fetchall()

    print(f"  查詢到 {len(rows):,} 筆移動中船舶資料")

    # 按時間間隔分組，每幀以 MMSI 為 key
    time_data = {}
    for ts, mmsi, lon, lat, sog, cog, vtype in rows:
        if sog is None or cog is None:
            continue

        time_key = align_time_key(ts, interval)
        if time_key not in time_data:
            time_data[time_key] = {}
        time_data[time_key][str(mmsi)] = [
            round(lon, 4),
            round(lat, 4),
            round(sog, 1),
            round(cog, 1),
            vtype or 0,
        ]

    # 建構輸出
    time_keys = sorted(time_data.keys())

    frames = []
    total_ships = 0
    for time_key in time_keys:
        ships = time_data[time_key]
        total_ships += len(ships)
        frames.append({"time": time_key, "ships": ships})

    output = {
        "metadata": {
            "bounds": TRAJECTORY_BOUNDS,
            "total_frames": len(frames),
            "interval_minutes": interval,
            "generated_at": datetime.now().isoformat(),
            "date_range": {
                "start": time_keys[0] if time_keys else None,
                "end": time_keys[-1] if time_keys else None,
            }
        },
        "frames": frames,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  檔案：{output_path}")
    print(f"  大小：{size_mb:.2f} MB")
    print(f"  幀數：{len(frames)}")
    print(f"  總船次（移動中）：{total_ships:,}")

    return len(frames)


def main():
    parser = argparse.ArgumentParser(
        description="從 SQLite 產出密度和軌跡 JSON"
    )
    parser.add_argument("--days", type=int, default=7, help="天數（預設 7）")
    parser.add_argument("--start", help="起始日期 YYYY-MM-DD（覆蓋 --days）")
    parser.add_argument("--end", help="結束日期 YYYY-MM-DD（覆蓋 --days）")
    parser.add_argument("--interval", type=int, default=10, choices=[10, 30, 60],
                        help="時間間隔分鐘（預設 10）")
    parser.add_argument("--db-path",
                        default=os.path.join(os.path.dirname(__file__), "..", "data", "ship_data.db"))
    parser.add_argument("--output-dir",
                        default=os.path.join(os.path.dirname(__file__), "..", "public"))
    args = parser.parse_args()

    db_path = os.path.abspath(args.db_path)
    output_dir = os.path.abspath(args.output_dir)

    if not os.path.exists(db_path):
        print(f"錯誤：資料庫不存在 {db_path}")
        sys.exit(1)

    start, end = get_time_range(args)
    print(f"=== 從 SQLite 產出 JSON ===")
    print(f"資料庫：{db_path}")
    print(f"日期範圍：{start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%Y-%m-%d %H:%M')}")
    print(f"時間間隔：{args.interval} 分鐘")
    print(f"輸出目錄：{output_dir}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA query_only=ON")

    density_path = os.path.join(output_dir, "ship_density_data.json")
    trajectory_path = os.path.join(output_dir, "ship_trajectory_data.json")

    generate_density_json(conn, start, end, args.interval, density_path)
    generate_trajectory_json(conn, start, end, args.interval, trajectory_path)

    conn.close()
    print(f"\n=== 完成 ===")


if __name__ == "__main__":
    main()
