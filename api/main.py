#!/usr/bin/env python3
"""
FastAPI 後端：提供船舶軌跡查詢 API + Arrow/靜態檔案服務
啟動：cd api && uvicorn main:app --reload --port 8000
"""
import os
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
from functools import lru_cache

from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Ship GIS API")

# CORS（開發環境 Vite dev server 在不同 port）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "ship_data.db"))


@contextmanager
def get_db():
    """取得 SQLite 連線（唯讀模式）"""
    db_path = os.path.abspath(DB_PATH)
    if not os.path.exists(db_path):
        raise HTTPException(status_code=503, detail="資料庫尚未建立，請先執行 import_to_db.py")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_max_timestamp(conn):
    """取得資料庫中最新的時間戳（快取在連線生命週期內）。"""
    row = conn.execute("SELECT MAX(timestamp) as max_ts FROM ship_positions").fetchone()
    if not row or not row["max_ts"]:
        return None
    return row["max_ts"]


# ==================== API 端點 ====================

@app.get("/api/ships/latest")
def get_latest_ships(limit: int = Query(default=500, ge=1, le=5000)):
    """所有船舶最新位置（最近 1 小時內有資料的船）"""
    with get_db() as conn:
        max_ts = get_max_timestamp(conn)
        if not max_ts:
            return []

        cutoff = (datetime.fromisoformat(max_ts) - timedelta(hours=1)).isoformat()

        ships = conn.execute("""
            SELECT mmsi, lon, lat, sog, cog, vessel_type, MAX(timestamp) as last_seen
            FROM ship_positions
            WHERE timestamp >= ?
            GROUP BY mmsi
            ORDER BY last_seen DESC
            LIMIT ?
        """, (cutoff, limit)).fetchall()

        return [
            {
                "mmsi": s["mmsi"],
                "lon": s["lon"],
                "lat": s["lat"],
                "sog": s["sog"],
                "cog": s["cog"],
                "vessel_type": s["vessel_type"],
                "last_seen": s["last_seen"],
            }
            for s in ships
        ]


@app.get("/api/ship/{mmsi}/track")
def get_ship_track(mmsi: str, days: int = Query(default=7, ge=1, le=30)):
    """單船歷史軌跡"""
    with get_db() as conn:
        max_ts = get_max_timestamp(conn)
        if not max_ts:
            raise HTTPException(status_code=404, detail="無資料")

        cutoff = (datetime.fromisoformat(max_ts) - timedelta(days=days)).isoformat()

        positions = conn.execute("""
            SELECT lon, lat, sog, cog, vessel_type, timestamp
            FROM ship_positions
            WHERE mmsi = ? AND timestamp >= ?
            ORDER BY timestamp
        """, (mmsi, cutoff)).fetchall()

        if not positions:
            raise HTTPException(status_code=404, detail=f"找不到 MMSI {mmsi} 的軌跡")

        return {
            "mmsi": mmsi,
            "vessel_type": positions[0]["vessel_type"],
            "track": [
                {
                    "lon": p["lon"],
                    "lat": p["lat"],
                    "sog": p["sog"],
                    "cog": p["cog"],
                    "timestamp": p["timestamp"],
                }
                for p in positions
            ],
        }


class BboxRequest(BaseModel):
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float


@app.post("/api/ships/tracks")
def get_ships_in_bbox(bbox: BboxRequest, days: int = Query(default=7, ge=1, le=30)):
    """圈選範圍內多船軌跡（上限 50 艘）"""
    with get_db() as conn:
        max_ts = get_max_timestamp(conn)
        if not max_ts:
            return []

        max_dt = datetime.fromisoformat(max_ts)
        cutoff_latest = (max_dt - timedelta(hours=1)).isoformat()
        cutoff_track = (max_dt - timedelta(days=days)).isoformat()

        # 找範圍內最新位置的 MMSI（上限 50）
        mmsi_rows = conn.execute("""
            SELECT mmsi, lon, lat, vessel_type, MAX(timestamp) as last_seen
            FROM ship_positions
            WHERE timestamp >= ?
              AND lon BETWEEN ? AND ?
              AND lat BETWEEN ? AND ?
            GROUP BY mmsi
            ORDER BY last_seen DESC
            LIMIT 50
        """, (cutoff_latest, bbox.lon_min, bbox.lon_max, bbox.lat_min, bbox.lat_max)).fetchall()

        if not mmsi_rows:
            return []

        # 批次查詢：用 IN 子句一次查所有船
        mmsi_list = [mr["mmsi"] for mr in mmsi_rows]
        placeholders = ','.join('?' * len(mmsi_list))

        all_positions = conn.execute(f"""
            SELECT mmsi, lon, lat, sog, cog, vessel_type, timestamp
            FROM ship_positions
            WHERE mmsi IN ({placeholders}) AND timestamp >= ?
            ORDER BY mmsi, timestamp
        """, (*mmsi_list, cutoff_track)).fetchall()

        # 按 MMSI 分組
        tracks = {}
        vtype_map = {mr["mmsi"]: mr["vessel_type"] for mr in mmsi_rows}
        for p in all_positions:
            mmsi = p["mmsi"]
            if mmsi not in tracks:
                tracks[mmsi] = []
            tracks[mmsi].append({
                "lon": p["lon"],
                "lat": p["lat"],
                "sog": p["sog"],
                "cog": p["cog"],
                "timestamp": p["timestamp"],
            })

        return [
            {
                "mmsi": mmsi,
                "vessel_type": vtype_map.get(mmsi, 0),
                "track": tracks.get(mmsi, []),
            }
            for mmsi in mmsi_list
            if mmsi in tracks
        ]


# ==================== 靜態檔案 ====================

# Arrow 資料檔案（frontend/public/data/）
arrow_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "data")
if os.path.isdir(arrow_dir):
    app.mount("/data", StaticFiles(directory=arrow_dir), name="arrow-data")

# 前端打包檔案（frontend/dist/）或舊版（public/）
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
public_dir = os.path.join(os.path.dirname(__file__), "..", "public")

if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
elif os.path.isdir(public_dir):
    app.mount("/", StaticFiles(directory=public_dir, html=True), name="static")
