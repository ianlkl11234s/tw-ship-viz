#!/usr/bin/env python3
"""
一次性腳本：將已有的 ship_trajectory_data.json 轉入 SQLite
之後增量更新改用 import_to_db.py 從 S3 抓
"""
import os
import sys
import json
import sqlite3

sys.path.insert(0, os.path.dirname(__file__))
from import_to_db import init_db, BATCH_SIZE

JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "ship_trajectory_data.json")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ship_data.db")


def main():
    json_path = os.path.abspath(JSON_PATH)
    db_path = os.path.abspath(DB_PATH)

    print(f"來源：{json_path}")
    print(f"目標：{db_path}")

    print("載入 JSON（可能需要幾秒）...")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    frames = data.get("frames", [])
    print(f"共 {len(frames)} 幀")

    conn = init_db(db_path)
    cursor = conn.cursor()
    batch = []
    total = 0

    for i, frame in enumerate(frames):
        # time 格式："2026-02-03 10:00" → 轉成 ISO "2026-02-03T10:00:00"
        time_str = frame["time"].replace(" ", "T") + ":00"
        ships = frame.get("ships", {})

        for mmsi, vals in ships.items():
            # vals = [lon, lat, sog, cog, vessel_type]
            lon, lat, sog, cog = vals[0], vals[1], vals[2], vals[3]
            vtype = vals[4] if len(vals) > 4 else 0

            batch.append((str(mmsi), time_str, lon, lat, sog, cog, vtype))
            total += 1

            if len(batch) >= BATCH_SIZE:
                cursor.executemany(
                    "INSERT INTO ship_positions (mmsi, timestamp, lon, lat, sog, cog, vessel_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", batch
                )
                conn.commit()
                batch.clear()

        if (i + 1) % 50 == 0:
            print(f"  進度：{i + 1}/{len(frames)}（{total:,} 筆）")

    if batch:
        cursor.executemany(
            "INSERT INTO ship_positions (mmsi, timestamp, lon, lat, sog, cog, vessel_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", batch
        )
        conn.commit()

    row_count = conn.execute("SELECT COUNT(*) FROM ship_positions").fetchone()[0]
    mmsi_count = conn.execute("SELECT COUNT(DISTINCT mmsi) FROM ship_positions").fetchone()[0]
    db_size = os.path.getsize(db_path) / (1024 * 1024)

    print(f"\n=== 完成 ===")
    print(f"匯入：{total:,} 筆")
    print(f"資料庫：{row_count:,} 筆，{mmsi_count:,} 艘船")
    print(f"大小：{db_size:.1f} MB")

    conn.close()


if __name__ == "__main__":
    main()
