#!/usr/bin/env python3
"""
船舶軌跡資料更新腳本
產生包含位置、速度、航向的資料供前端動畫使用
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict

import boto3
from dotenv import load_dotenv


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

    def get_file(self, key: str) -> Dict[str, Any]:
        """讀取 S3 JSON 檔案"""
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            content = response["Body"].read().decode("utf-8")
            return json.loads(content)
        except Exception as e:
            print(f"警告：讀取 {key} 失敗: {e}")
            return None

    def parse_timestamp_from_key(self, key: str) -> datetime:
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


def process_ships(ships: List[Dict], bounds: Dict) -> Dict[str, List]:
    """
    處理船舶資料，以 MMSI 為 key 組織

    Returns:
        {mmsi: [lon, lat, sog, cog, vessel_type], ...}
    """
    result = {}

    for ship in ships:
        mmsi = ship.get("mmsi")
        lon = ship.get("lon")
        lat = ship.get("lat")
        sog = ship.get("sog")  # 速度（節）
        cog = ship.get("cog")  # 航向（度）
        vtype = ship.get("vessel_type", 0)

        # 跳過無效資料
        if mmsi is None or lon is None or lat is None:
            continue
        if sog is None or cog is None:
            continue

        # 檢查是否在範圍內
        if lon < bounds["lon_min"] or lon > bounds["lon_max"]:
            continue
        if lat < bounds["lat_min"] or lat > bounds["lat_max"]:
            continue

        # 只保留移動中的船舶（速度 > 0.5 節）
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


def main():
    parser = argparse.ArgumentParser(description="更新船舶軌跡資料")
    parser.add_argument("--hours", type=int, default=24, help="處理小時數（預設 24）")
    parser.add_argument("--interval", type=int, default=10, help="時間間隔（分鐘）")
    parser.add_argument("--max-files", type=int, default=0, help="最大檔案數（測試用）")
    parser.add_argument("--output", default="../public/ship_trajectory_data.json", help="輸出檔案路徑")

    args = parser.parse_args()

    # 計算日期範圍
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=args.hours)

    # 地理範圍（台灣周邊）
    bounds = {
        "lon_min": 117.0,
        "lon_max": 127.0,
        "lat_min": 20.0,
        "lat_max": 28.0
    }

    print(f"=== 船舶軌跡資料更新 ===")
    print(f"時間範圍：{start_date.strftime('%Y-%m-%d %H:%M')} ~ {end_date.strftime('%Y-%m-%d %H:%M')}")
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

    # 按時間間隔聚合
    print(f"\n正在處理資料...")
    frames = []

    for i, key in enumerate(files):
        if (i + 1) % 20 == 0:
            print(f"  進度：{i + 1}/{len(files)}")

        timestamp = reader.parse_timestamp_from_key(key)
        if not timestamp:
            continue

        # 對齊到指定間隔
        aligned_minute = (timestamp.minute // args.interval) * args.interval
        time_key = timestamp.strftime(f"%Y-%m-%d %H:{aligned_minute:02d}")

        data = reader.get_file(key)
        if not data:
            continue

        ships = data.get("data", [])
        processed = process_ships(ships, bounds)

        # 同一時間間隔只保留最後一筆
        if frames and frames[-1]["time"] == time_key:
            frames[-1]["ships"] = processed
        else:
            frames.append({
                "time": time_key,
                "ships": processed
            })

    # 組合輸出
    output_data = {
        "metadata": {
            "bounds": bounds,
            "total_frames": len(frames),
            "interval_minutes": args.interval,
            "generated_at": datetime.now().isoformat(),
            "date_range": {
                "start": frames[0]["time"] if frames else None,
                "end": frames[-1]["time"] if frames else None
            }
        },
        "frames": frames
    }

    # 輸出檔案
    output_path = os.path.join(os.path.dirname(__file__), args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False)

    file_size = os.path.getsize(output_path)
    file_size_mb = file_size / (1024 * 1024)

    print(f"\n=== 完成 ===")
    print(f"輸出檔案：{output_path}")
    print(f"檔案大小：{file_size_mb:.2f} MB")
    print(f"總幀數：{len(frames)}")

    if frames:
        total_ships = sum(len(f["ships"]) for f in frames)
        print(f"時間範圍：{frames[0]['time']} ~ {frames[-1]['time']}")
        print(f"總船次（移動中）：{total_ships:,}")


if __name__ == "__main__":
    main()
