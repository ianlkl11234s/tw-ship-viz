"""
格網計算工具
"""
import math
from typing import List, Tuple, Dict, Any


class DensityGrid:
    """
    船舶密度格網計算器

    預設範圍：台灣周邊海域
    - 經度：117°E - 127°E (200 格)
    - 緯度：20°N - 28°N (160 格)
    - 解析度：0.05° (~5.5km)
    """

    def __init__(
        self,
        lon_min: float = 117.0,
        lon_max: float = 127.0,
        lat_min: float = 20.0,
        lat_max: float = 28.0,
        resolution: float = 0.05
    ):
        self.lon_min = lon_min
        self.lon_max = lon_max
        self.lat_min = lat_min
        self.lat_max = lat_max
        self.resolution = resolution

        # 計算格網尺寸
        self.cols = int((lon_max - lon_min) / resolution)
        self.rows = int((lat_max - lat_min) / resolution)

    def get_geo_info(self) -> Dict[str, Any]:
        """取得地理資訊"""
        return {
            "bottom_left_lon": self.lon_min,
            "bottom_left_lat": self.lat_min,
            "top_right_lon": self.lon_max,
            "top_right_lat": self.lat_max,
            "resolution_lon": self.resolution,
            "resolution_lat": self.resolution,
            "cols": self.cols,
            "rows": self.rows
        }

    def _get_cell(self, lon: float, lat: float) -> Tuple[int, int]:
        """
        取得座標所在的格網索引

        Returns:
            (col, row) 或 (-1, -1) 如果超出範圍
        """
        if lon < self.lon_min or lon >= self.lon_max:
            return (-1, -1)
        if lat < self.lat_min or lat >= self.lat_max:
            return (-1, -1)

        col = int((lon - self.lon_min) / self.resolution)
        row = int((lat - self.lat_min) / self.resolution)

        # 邊界檢查
        col = min(col, self.cols - 1)
        row = min(row, self.rows - 1)

        return (col, row)

    def calculate_density(self, ships: List[Dict[str, Any]]) -> List[List[int]]:
        """
        計算船舶密度分布

        Args:
            ships: 船舶資料列表，每筆需有 'longitude' 和 'latitude' 欄位

        Returns:
            二維密度陣列 [row][col]，從南到北、從西到東
        """
        # 初始化格網
        grid = [[0 for _ in range(self.cols)] for _ in range(self.rows)]

        # 計算每格船舶數量
        for ship in ships:
            lon = ship.get("longitude") or ship.get("lon")
            lat = ship.get("latitude") or ship.get("lat")

            if lon is None or lat is None:
                continue

            try:
                lon = float(lon)
                lat = float(lat)
            except (ValueError, TypeError):
                continue

            col, row = self._get_cell(lon, lat)
            if col >= 0 and row >= 0:
                grid[row][col] += 1

        return grid

    def compress_grid(self, grid: List[List[int]]) -> List[List[int]]:
        """
        壓縮格網資料（移除連續的零值）

        使用 RLE 編碼：[count, value] 表示連續 count 個 value
        單一非零值直接表示

        Returns:
            壓縮後的資料
        """
        compressed = []

        for row in grid:
            compressed_row = []
            i = 0
            while i < len(row):
                val = row[i]
                count = 1

                # 計算連續相同值的數量
                while i + count < len(row) and row[i + count] == val:
                    count += 1

                # 決定編碼方式
                if count >= 3 or (val == 0 and count >= 2):
                    # 使用 RLE 編碼
                    compressed_row.append([count, val])
                else:
                    # 直接存值
                    for _ in range(count):
                        compressed_row.append(val)

                i += count

            compressed.append(compressed_row)

        return compressed

    def get_stats(self, grid: List[List[int]], total_ships: int) -> Dict[str, Any]:
        """
        計算統計資訊
        """
        non_zero_cells = 0
        max_density = 0
        total_density = 0

        for row in grid:
            for val in row:
                if val > 0:
                    non_zero_cells += 1
                    total_density += val
                    max_density = max(max_density, val)

        return {
            "total_ships": total_ships,
            "ships_in_range": total_density,
            "non_zero_cells": non_zero_cells,
            "max_density": max_density,
            "avg_density": round(total_density / non_zero_cells, 2) if non_zero_cells > 0 else 0
        }
