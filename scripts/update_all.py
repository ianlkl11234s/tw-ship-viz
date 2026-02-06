#!/usr/bin/env python3
"""
統一更新腳本：一次讀取 S3 資料，分別產出密度和軌跡兩份 JSON
整合 update_data.py 和 update_trajectory.py 的功能
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict

import boto3
from dotenv import load_dotenv

from grid_utils import DensityGrid
from vessel_types import VESSEL_CATEGORIES


class S3ShipReader:
    """S3 船舶資料讀取器"""

    def __init__(self):
        load_dotenv()

        self.bucket = os.getenv("S3_BUCKET")
        self.region = os.getenv("S3_REGION", "ap-northeast-1")
        self.endpoint = os.getenv("S3_ENDPOINT")

        if not self.bucket:
            raise ValueError("S3_BUCKET 環境變數未設定")

        self.s3 = boto3.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
            endpoint_url=self.endpoint
        )

        self.prefix = "ship_ais"

    def list_files_in_range(self, start_date: datetime, end_date: datetime) -> List[str]:
        """列出日期範圍內的所有 AIS 資料檔案"""
        files = []
        current_date = start_date.date()
        end_date_only = end_date.date()

        while current_date <= end_date_only:
            prefix = f"{self.prefix}/{current_date.year:04d}/{current_date.month:02d}/{current_date.day:02d}/"

            try:
                paginator = self.s3.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                    for obj in page.get("Contents", []):
                        key = obj["Key"]
                        if key.endswith(".json") and "latest" not in key:
                            files.append(key)
            except Exception as e:
                print(f"警告：列舉 {prefix} 失敗: {e}")

            current_date += timedelta(days=1)

        files.sort()
        return files

    def get_file(self, key: str) -> Optional[Dict[str, Any]]:
        """讀取 S3 JSON 檔案"""
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            content = response["Body"].read().decode("utf-8")
            return json.loads(content)
        except Exception as e:
            print(f"警告：讀取 {key} 失敗: {e}")
            return None

    def parse_timestamp_from_key(self, key: str) -> Optional[datetime]:
        """從 S3 key 解析時間戳記"""
        try:
            parts = key.split("/")
            year = int(parts[1])
            month = int(parts[2])
            day = int(parts[3])
            filename = parts[4]
            time_part = filename.replace("ship_ais_", "").replace(".json", "")
            hour = int(time_part[:2])
            minute = int(time_part[2:])
            return datetime(year, month, day, hour, minute)
        except Exception:
            return None


# ==================== 密度資料處理 ====================

def build_density_data(time_data: Dict[str, List], max_frames: int) -> Dict:
    """從聚合資料產生密度 JSON"""
    grid = DensityGrid()
    geo_info = grid.get_geo_info()

    time_keys = sorted(time_data.keys())
    if len(time_keys) > max_frames:
        time_keys = time_keys[-max_frames:]

    frames = []
    total_ships = 0

    for time_key in time_keys:
        ships = time_data[time_key]
        total_ships += len(ships)
        frames.append({
            "time": time_key,
            "ships": ships  # [lon, lat, vessel_type]
        })

    return {
        "metadata": {
            "geo_info": geo_info,
            "total_frames": len(frames),
            "generated_at": datetime.now().isoformat(),
            "interval_minutes": 10,
            "date_range": {
                "start": time_keys[0] if time_keys else None,
                "end": time_keys[-1] if time_keys else None
            }
        },
        "frames": frames
    }, total_ships


# ==================== 軌跡資料處理 ====================

TRAJECTORY_BOUNDS = {
    "lon_min": 117.0,
    "lon_max": 127.0,
    "lat_min": 20.0,
    "lat_max": 28.0
}


def process_trajectory_ships(ships: List[Dict]) -> Dict[str, List]:
    """
    處理船舶資料，以 MMSI 為 key 組織

    Returns:
        {mmsi: [lon, lat, sog, cog, vessel_type], ...}
    """
    result = {}
    bounds = TRAJECTORY_BOUNDS

    for ship in ships:
        mmsi = ship.get("mmsi")
        lon = ship.get("lon")
        lat = ship.get("lat")
        sog = ship.get("sog")
        cog = ship.get("cog")
        vtype = ship.get("vessel_type", 0)

        if mmsi is None or lon is None or lat is None:
            continue
        if sog is None or cog is None:
            continue
        if lon < bounds["lon_min"] or lon > bounds["lon_max"]:
            continue
        if lat < bounds["lat_min"] or lat > bounds["lat_max"]:
            continue
        if sog < 0.5:
            continue

        result[str(mmsi)] = [
            round(lon, 4),
            round(lat, 4),
            round(sog, 1),
            round(cog, 1),
            vtype
        ]

    return result


def build_trajectory_data(time_data: Dict[str, Dict]) -> Dict:
    """從聚合資料產生軌跡 JSON"""
    time_keys = sorted(time_data.keys())

    frames = []
    total_ships = 0

    for time_key in time_keys:
        ships = time_data[time_key]
        total_ships += len(ships)
        frames.append({
            "time": time_key,
            "ships": ships
        })

    return {
        "metadata": {
            "bounds": TRAJECTORY_BOUNDS,
            "total_frames": len(frames),
            "interval_minutes": 10,
            "generated_at": datetime.now().isoformat(),
            "date_range": {
                "start": time_keys[0] if time_keys else None,
                "end": time_keys[-1] if time_keys else None
            }
        },
        "frames": frames
    }, total_ships


# ==================== 主程式 ====================

def main():
    parser = argparse.ArgumentParser(description="統一更新船舶密度與軌跡資料")
    parser.add_argument("--days", type=int, default=7, help="處理天數（預設 7）")
    parser.add_argument("--interval", type=int, default=10, choices=[10, 30, 60], help="時間間隔（分鐘），預設 10")
    parser.add_argument("--max-frames", type=int, default=1008, help="密度最大幀數（預設 1008）")
    parser.add_argument("--max-files", type=int, default=0, help="最大檔案數（0=不限制，測試用）")
    parser.add_argument("--density-output", default="../public/ship_density_data.json")
    parser.add_argument("--trajectory-output", default="../public/ship_trajectory_data.json")

    args = parser.parse_args()

    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.days)

    print(f"=== 統一資料更新 ===")
    print(f"日期範圍：{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
    print(f"時間間隔：{args.interval} 分鐘")

    reader = S3ShipReader()

    # 列出檔案
    print(f"\n正在列舉 S3 檔案...")
    files = reader.list_files_in_range(start_date, end_date)
    print(f"  找到 {len(files)} 個檔案")

    if args.max_files > 0 and len(files) > args.max_files:
        files = files[:args.max_files]
        print(f"  限制為前 {args.max_files} 個檔案（測試模式）")

    if not files:
        print("錯誤：沒有找到任何資料檔案")
        sys.exit(1)

    # 一次讀取，分別聚合
    print(f"\n正在處理資料...")
    density_time_data = defaultdict(list)     # {time_key: [[lon, lat, vtype], ...]}
    trajectory_time_data = {}                  # {time_key: {mmsi: [lon,lat,sog,cog,vtype]}}

    for i, key in enumerate(files):
        if (i + 1) % 20 == 0:
            print(f"  進度：{i + 1}/{len(files)}")

        timestamp = reader.parse_timestamp_from_key(key)
        if not timestamp:
            continue

        # 對齊到指定間隔
        if args.interval >= 60:
            time_key = timestamp.strftime("%Y-%m-%d %H:00")
        else:
            aligned_minute = (timestamp.minute // args.interval) * args.interval
            time_key = timestamp.strftime(f"%Y-%m-%d %H:{aligned_minute:02d}")

        data = reader.get_file(key)
        if not data:
            continue

        ships = data.get("data", [])

        # 密度：[lon, lat, vessel_type]
        minimal_ships = []
        for ship in ships:
            lon = ship.get("lon")
            lat = ship.get("lat")
            vtype = ship.get("vessel_type", 0)
            if lon is not None and lat is not None:
                minimal_ships.append([lon, lat, vtype])
        density_time_data[time_key] = minimal_ships

        # 軌跡：{mmsi: [lon, lat, sog, cog, vessel_type]}
        trajectory_time_data[time_key] = process_trajectory_ships(ships)

    # 產出密度 JSON
    print(f"\n正在產出密度資料...")
    density_output, density_ships = build_density_data(density_time_data, args.max_frames)
    density_path = os.path.join(os.path.dirname(__file__), args.density_output)
    os.makedirs(os.path.dirname(density_path), exist_ok=True)
    with open(density_path, "w", encoding="utf-8") as f:
        json.dump(density_output, f, ensure_ascii=False)
    density_size = os.path.getsize(density_path) / (1024 * 1024)
    print(f"  檔案：{density_path}")
    print(f"  大小：{density_size:.2f} MB")
    print(f"  幀數：{density_output['metadata']['total_frames']}")
    print(f"  總船次：{density_ships:,}")

    # 產出軌跡 JSON
    print(f"\n正在產出軌跡資料...")
    trajectory_output, trajectory_ships = build_trajectory_data(trajectory_time_data)
    trajectory_path = os.path.join(os.path.dirname(__file__), args.trajectory_output)
    os.makedirs(os.path.dirname(trajectory_path), exist_ok=True)
    with open(trajectory_path, "w", encoding="utf-8") as f:
        json.dump(trajectory_output, f, ensure_ascii=False)
    trajectory_size = os.path.getsize(trajectory_path) / (1024 * 1024)
    print(f"  檔案：{trajectory_path}")
    print(f"  大小：{trajectory_size:.2f} MB")
    print(f"  幀數：{trajectory_output['metadata']['total_frames']}")
    print(f"  總船次（移動中）：{trajectory_ships:,}")

    print(f"\n=== 完成 ===")


if __name__ == "__main__":
    main()
