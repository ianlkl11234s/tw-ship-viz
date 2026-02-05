#!/usr/bin/env python3
"""
船舶密度資料更新腳本
從 S3 讀取 AIS 資料，計算密度格網，產出前端所需的 JSON 檔案
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
from vessel_types import filter_by_category, get_category_name, VESSEL_CATEGORIES


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

    def list_files_in_range(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[str]:
        """
        列出日期範圍內的所有 AIS 資料檔案

        Returns:
            S3 key 列表，按時間排序
        """
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

        # 按時間排序
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
        """
        從 S3 key 解析時間戳記
        格式：ship_ais/YYYY/MM/DD/ship_ais_HHMM.json
        """
        try:
            parts = key.split("/")
            year = int(parts[1])
            month = int(parts[2])
            day = int(parts[3])

            filename = parts[4]  # ship_ais_HHMM.json
            time_part = filename.replace("ship_ais_", "").replace(".json", "")
            hour = int(time_part[:2])
            minute = int(time_part[2:])

            return datetime(year, month, day, hour, minute)
        except Exception:
            return None


def aggregate_by_hour(
    reader: S3ShipReader,
    files: List[str],
    vessel_category: str = "all"
) -> Dict[str, List[Dict]]:
    """
    按小時聚合船舶資料

    Args:
        reader: S3 讀取器
        files: S3 key 列表
        vessel_category: 船舶類別過濾

    Returns:
        {hour_key: [ships]} 字典
    """
    hourly_data = defaultdict(list)

    for i, key in enumerate(files):
        if (i + 1) % 50 == 0:
            print(f"  處理進度：{i + 1}/{len(files)}")

        timestamp = reader.parse_timestamp_from_key(key)
        if not timestamp:
            continue

        # 小時 key
        hour_key = timestamp.strftime("%Y-%m-%d %H:00")

        data = reader.get_file(key)
        if not data:
            continue

        ships = data.get("ships", [])

        # 過濾船舶類別
        if vessel_category != "all":
            ships = filter_by_category(ships, vessel_category)

        # 收集該小時的船舶資料（取最後一筆作為該小時的代表）
        hourly_data[hour_key] = ships

    return hourly_data


def main():
    parser = argparse.ArgumentParser(description="更新船舶密度資料")
    parser.add_argument("--days", type=int, default=7, help="處理天數（預設 7 天）")
    parser.add_argument("--start-date", help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="結束日期 (YYYY-MM-DD)")
    parser.add_argument(
        "--vessel-type",
        default="all",
        choices=["all"] + list(VESSEL_CATEGORIES.keys()),
        help="船舶類別過濾"
    )
    parser.add_argument("--output", default="../public/ship_density_data.json", help="輸出檔案路徑")
    parser.add_argument("--max-frames", type=int, default=168, help="最大幀數（預設 168）")

    args = parser.parse_args()

    # 計算日期範圍
    if args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(hour=23, minute=59)
    else:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)

    print(f"=== 船舶密度資料更新 ===")
    print(f"日期範圍：{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
    print(f"船舶類別：{get_category_name(args.vessel_type)}")
    print(f"最大幀數：{args.max_frames}")

    # 初始化
    reader = S3ShipReader()
    grid = DensityGrid()

    print(f"\n格網設定：")
    geo_info = grid.get_geo_info()
    print(f"  範圍：{geo_info['bottom_left_lon']}°E ~ {geo_info['top_right_lon']}°E, "
          f"{geo_info['bottom_left_lat']}°N ~ {geo_info['top_right_lat']}°N")
    print(f"  解析度：{geo_info['resolution_lon']}° ({grid.cols} x {grid.rows} = {grid.cols * grid.rows} 格)")

    # 列出檔案
    print(f"\n正在列舉 S3 檔案...")
    files = reader.list_files_in_range(start_date, end_date)
    print(f"  找到 {len(files)} 個檔案")

    if not files:
        print("錯誤：沒有找到任何資料檔案")
        sys.exit(1)

    # 按小時聚合
    print(f"\n正在聚合資料...")
    hourly_data = aggregate_by_hour(reader, files, args.vessel_type)
    print(f"  產生 {len(hourly_data)} 個小時的資料")

    # 限制幀數
    hour_keys = sorted(hourly_data.keys())
    if len(hour_keys) > args.max_frames:
        hour_keys = hour_keys[-args.max_frames:]
        print(f"  限制為最近 {args.max_frames} 幀")

    # 計算密度格網
    print(f"\n正在計算密度格網...")
    frames = []

    for i, hour_key in enumerate(hour_keys):
        if (i + 1) % 24 == 0:
            print(f"  進度：{i + 1}/{len(hour_keys)}")

        ships = hourly_data[hour_key]
        density_grid = grid.calculate_density(ships)
        stats = grid.get_stats(density_grid, len(ships))

        # 壓縮格網資料
        compressed_data = grid.compress_grid(density_grid)

        frames.append({
            "time": hour_key,
            "stats": stats,
            "data": compressed_data
        })

    # 組合輸出
    output_data = {
        "metadata": {
            "geo_info": geo_info,
            "total_frames": len(frames),
            "vessel_filter": args.vessel_type,
            "vessel_filter_name": get_category_name(args.vessel_type),
            "generated_at": datetime.now().isoformat(),
            "date_range": {
                "start": hour_keys[0] if hour_keys else None,
                "end": hour_keys[-1] if hour_keys else None
            }
        },
        "frames": frames
    }

    # 輸出檔案
    output_path = os.path.join(os.path.dirname(__file__), args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False)

    # 計算檔案大小
    file_size = os.path.getsize(output_path)
    file_size_mb = file_size / (1024 * 1024)

    print(f"\n=== 完成 ===")
    print(f"輸出檔案：{output_path}")
    print(f"檔案大小：{file_size_mb:.2f} MB")
    print(f"總幀數：{len(frames)}")

    if frames:
        print(f"時間範圍：{frames[0]['time']} ~ {frames[-1]['time']}")
        total_ships = sum(f["stats"]["ships_in_range"] for f in frames)
        print(f"總船次：{total_ships:,}")


if __name__ == "__main__":
    main()
