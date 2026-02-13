#!/usr/bin/env python3
"""
優化 SQLite 資料庫：加入複合索引以提升查詢效能。
執行一次即可，冪等操作。

用法: python3 scripts/optimize_db.py
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'ship_data.db')


def optimize():
    db_path = os.path.abspath(DB_PATH)
    if not os.path.exists(db_path):
        print(f"資料庫不存在: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 列出現有索引
    cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
    existing = {row[0]: row[1] for row in cursor.fetchall()}
    print(f"現有索引: {list(existing.keys())}")

    # 要建立的索引（IF NOT EXISTS 保證冪等）
    indexes = [
        # 複合索引：時間 + 空間（圈選查詢用）
        ("idx_time_lon_lat",
         "CREATE INDEX IF NOT EXISTS idx_time_lon_lat ON ship_positions(timestamp, lon, lat)"),
        # 唯一索引：去重（同一艘船同一時間只保留一筆）
        # 注意：如果有重複資料，這會失敗，需要先清理
        # ("idx_unique_mmsi_time",
        #  "CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_mmsi_time ON ship_positions(mmsi, timestamp)"),
    ]

    for name, sql in indexes:
        if name in existing:
            print(f"  索引已存在: {name}")
        else:
            print(f"  建立索引: {name} ...")
            cursor.execute(sql)
            print(f"  完成!")

    # ANALYZE 更新統計資訊（幫助查詢優化器）
    print("執行 ANALYZE...")
    cursor.execute("ANALYZE")

    conn.commit()
    conn.close()
    print("資料庫優化完成!")


if __name__ == '__main__':
    optimize()
