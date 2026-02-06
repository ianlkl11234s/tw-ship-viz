#!/usr/bin/env python3
"""
FastAPI 後端：提供船舶軌跡查詢 API + 靜態檔案服務
啟動：cd api && uvicorn main:app --reload --port 8000
"""
import os
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Ship GIS API")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ship_data.db")


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


# ==================== API 端點 ====================

@app.get("/api/ships/latest")
def get_latest_ships():
    """所有船舶最新位置（最近 1 小時內有資料的船）"""
    with get_db() as conn:
        # 先找資料庫中最新的時間點
        row = conn.execute("SELECT MAX(timestamp) as max_ts FROM ship_positions").fetchone()
        if not row or not row["max_ts"]:
            return {"ships": [], "timestamp": None}

        max_ts = row["max_ts"]
        # 取最新時間點前 1 小時的資料中，每艘船最新的位置
        cutoff = (datetime.fromisoformat(max_ts) - timedelta(hours=1)).isoformat()

        ships = conn.execute("""
            SELECT mmsi, lon, lat, sog, cog, vessel_type, MAX(timestamp) as last_seen
            FROM ship_positions
            WHERE timestamp >= ?
            GROUP BY mmsi
            ORDER BY last_seen DESC
        """, (cutoff,)).fetchall()

        return {
            "ships": [
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
            ],
            "timestamp": max_ts,
        }


@app.get("/api/ship/{mmsi}/track")
def get_ship_track(mmsi: str, days: int = Query(default=7, ge=1, le=30)):
    """單船歷史軌跡"""
    with get_db() as conn:
        # 以資料庫最新時間為基準往回推
        row = conn.execute("SELECT MAX(timestamp) as max_ts FROM ship_positions").fetchone()
        if not row or not row["max_ts"]:
            raise HTTPException(status_code=404, detail="無資料")

        max_ts = datetime.fromisoformat(row["max_ts"])
        cutoff = (max_ts - timedelta(days=days)).isoformat()

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
            "points": [
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
        row = conn.execute("SELECT MAX(timestamp) as max_ts FROM ship_positions").fetchone()
        if not row or not row["max_ts"]:
            return {"ships": []}

        max_ts = datetime.fromisoformat(row["max_ts"])
        cutoff_latest = (max_ts - timedelta(hours=1)).isoformat()
        cutoff_track = (max_ts - timedelta(days=days)).isoformat()

        # 先找範圍內最新位置的 MMSI（上限 50）
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
            return {"ships": []}

        # 查各船軌跡
        result = []
        for mr in mmsi_rows:
            positions = conn.execute("""
                SELECT lon, lat, sog, cog, timestamp
                FROM ship_positions
                WHERE mmsi = ? AND timestamp >= ?
                ORDER BY timestamp
            """, (mr["mmsi"], cutoff_track)).fetchall()

            result.append({
                "mmsi": mr["mmsi"],
                "vessel_type": mr["vessel_type"],
                "last_position": {"lon": mr["lon"], "lat": mr["lat"]},
                "points": [
                    {
                        "lon": p["lon"],
                        "lat": p["lat"],
                        "sog": p["sog"],
                        "cog": p["cog"],
                        "timestamp": p["timestamp"],
                    }
                    for p in positions
                ],
            })

        return {"ships": result}


# ==================== 靜態檔案 ====================

public_dir = os.path.join(os.path.dirname(__file__), "..", "public")
app.mount("/", StaticFiles(directory=public_dir, html=True), name="static")
