#!/usr/bin/env python3
"""
S3 AIS 資料匯入 SQLite
重用 update_all.py 的 S3ShipReader，將船舶位置資料寫入 SQLite 供 API 查詢
"""
import os
import sys
import sqlite3
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from update_all import S3ShipReader

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS ship_positions (
    mmsi TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    lon REAL NOT NULL,
    lat REAL NOT NULL,
    sog REAL,
    cog REAL,
    vessel_type INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mmsi_time ON ship_positions(mmsi, timestamp);
CREATE INDEX IF NOT EXISTS idx_time ON ship_positions(timestamp);
CREATE INDEX IF NOT EXISTS idx_lon_lat ON ship_positions(lon, lat);
"""

BOUNDS = {
    "lon_min": 117.0, "lon_max": 127.0,
    "lat_min": 20.0, "lat_max": 28.0,
}

BATCH_SIZE = 5000


def init_db(db_path):
    """建立資料庫和表結構"""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(DB_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_latest_timestamp(conn):
    """取得資料庫中最新的時間戳記"""
    row = conn.execute("SELECT MAX(timestamp) FROM ship_positions").fetchone()
    if row and row[0]:
        return datetime.fromisoformat(row[0])
    return None


def import_file(conn, reader, key, cursor, batch, stats):
    """處理單一 S3 檔案，將船舶資料加入批次"""
    timestamp = reader.parse_timestamp_from_key(key)
    if not timestamp:
        return batch

    ts_str = timestamp.isoformat()
    data = reader.get_file(key)
    if not data:
        return batch

    ships = data.get("data", [])
    for ship in ships:
        mmsi = ship.get("mmsi")
        lon = ship.get("lon")
        lat = ship.get("lat")
        sog = ship.get("sog")
        cog = ship.get("cog")
        vtype = ship.get("vessel_type", 0)

        if mmsi is None or lon is None or lat is None:
            continue
        if lon < BOUNDS["lon_min"] or lon > BOUNDS["lon_max"]:
            continue
        if lat < BOUNDS["lat_min"] or lat > BOUNDS["lat_max"]:
            continue

        batch.append((str(mmsi), ts_str, round(lon, 4), round(lat, 4),
                       round(sog, 1) if sog is not None else None,
                       round(cog, 1) if cog is not None else None,
                       vtype))
        stats["rows"] += 1

        if len(batch) >= BATCH_SIZE:
            cursor.executemany(
                "INSERT INTO ship_positions (mmsi, timestamp, lon, lat, sog, cog, vessel_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", batch
            )
            conn.commit()
            batch.clear()

    stats["files"] += 1
    return batch


def main():
    parser = argparse.ArgumentParser(description="匯入 S3 AIS 資料到 SQLite")
    parser.add_argument("--days", type=int, default=7, help="匯入天數（預設 7）")
    parser.add_argument("--db-path", default=os.path.join(os.path.dirname(__file__), "..", "data", "ship_data.db"))
    parser.add_argument("--incremental", action="store_true", help="只匯入新資料")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db_path)
    print(f"=== S3 → SQLite 匯入 ===")
    print(f"資料庫：{db_path}")

    conn = init_db(db_path)
    reader = S3ShipReader()

    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.days)

    if args.incremental:
        latest = get_latest_timestamp(conn)
        if latest:
            start_date = latest
            print(f"增量模式：從 {start_date.isoformat()} 開始")

    print(f"日期範圍：{start_date.strftime('%Y-%m-%d %H:%M')} ~ {end_date.strftime('%Y-%m-%d %H:%M')}")

    # 列出檔案
    print("正在列舉 S3 檔案...")
    files = reader.list_files_in_range(start_date, end_date)
    print(f"找到 {len(files)} 個檔案")

    if not files:
        print("沒有找到任何資料檔案")
        conn.close()
        return

    # 增量模式：過濾已匯入的時間
    if args.incremental and get_latest_timestamp(conn):
        latest_ts = get_latest_timestamp(conn)
        original_count = len(files)
        files = [f for f in files
                 if (reader.parse_timestamp_from_key(f) or datetime.min) > latest_ts]
        print(f"過濾後：{len(files)} 個新檔案（跳過 {original_count - len(files)} 個）")

    # 匯入
    cursor = conn.cursor()
    batch = []
    stats = {"files": 0, "rows": 0}

    for i, key in enumerate(files):
        if (i + 1) % 20 == 0:
            print(f"  進度：{i + 1}/{len(files)}（已匯入 {stats['rows']:,} 筆）")
        batch = import_file(conn, reader, key, cursor, batch, stats)

    # 寫入剩餘批次
    if batch:
        cursor.executemany(
            "INSERT INTO ship_positions (mmsi, timestamp, lon, lat, sog, cog, vessel_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", batch
        )
        conn.commit()

    # 統計
    total = conn.execute("SELECT COUNT(*) FROM ship_positions").fetchone()[0]
    mmsi_count = conn.execute("SELECT COUNT(DISTINCT mmsi) FROM ship_positions").fetchone()[0]
    db_size = os.path.getsize(db_path) / (1024 * 1024)

    print(f"\n=== 完成 ===")
    print(f"本次匯入：{stats['files']} 個檔案，{stats['rows']:,} 筆資料")
    print(f"資料庫總計：{total:,} 筆，{mmsi_count:,} 艘船")
    print(f"資料庫大小：{db_size:.1f} MB")

    conn.close()


if __name__ == "__main__":
    main()
