#!/usr/bin/env python3
"""
清理超過指定天數的舊 AIS 資料，避免 SQLite 無限膨脹。
每日排程在 import 之後、generate_arrow 之前執行。
"""
import argparse
import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "ship_data.db"))


def cleanup(days: int):
    db_path = os.path.abspath(DB_PATH)
    if not os.path.exists(db_path):
        print(f"[cleanup] 資料庫不存在: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    # 計算要刪除的筆數
    row = conn.execute("SELECT COUNT(*) FROM ship_positions WHERE timestamp < ?", (cutoff,)).fetchone()
    count = row[0] if row else 0

    if count == 0:
        print(f"[cleanup] 無超過 {days} 天的舊資料")
        conn.close()
        return

    print(f"[cleanup] 刪除 {count:,} 筆超過 {days} 天的資料（cutoff: {cutoff}）")
    conn.execute("DELETE FROM ship_positions WHERE timestamp < ?", (cutoff,))
    conn.commit()

    # 回收空間
    print("[cleanup] VACUUM 回收空間...")
    conn.execute("VACUUM")
    conn.close()
    print("[cleanup] 完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理舊 AIS 資料")
    parser.add_argument("--days", type=int, default=14, help="保留天數（預設 14）")
    args = parser.parse_args()
    cleanup(args.days)
