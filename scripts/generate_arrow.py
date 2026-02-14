#!/usr/bin/env python3
"""
從 SQLite 產出 Apache Arrow IPC 檔案，供前端 deck.gl 使用。

產出兩個檔案：
  - positions.arrow: 所有船舶位置（密度/六角/熱力圖模式用）
  - trajectory.arrow: 船舶軌跡，按 MMSI 排序（軌跡動畫用）

切段邏輯（方案 D）：
  - MMSI 切換 → 切（不同船）
  - 速度 > 45kt → 切（GPS 異常 / MMSI 共用）
  - 連線穿越台灣本島 → 切（不可能的路徑）
  - 停在港口圍欄內 + sog≈0 > 1hr → 切（回港停泊）
  - 其他（含外海長時間停泊）→ 不切

用法:
  python3 generate_arrow.py --days 7
  python3 generate_arrow.py --start 2026-02-05 --end 2026-02-12
"""

import argparse
import json
import math
import os
import shutil
import sqlite3
from datetime import datetime, timedelta

import pyarrow as pa
import pyarrow.ipc as ipc

SCRIPT_DIR = os.path.dirname(__file__)
DB_PATH = os.environ.get('DB_PATH', os.path.join(SCRIPT_DIR, '..', 'data', 'ship_data.db'))
OUTPUT_DIR = os.environ.get('ARROW_OUTPUT_DIR', os.path.join(SCRIPT_DIR, '..', 'frontend', 'public', 'data'))
DATA_DIR = os.path.join(SCRIPT_DIR, '..', 'data')

# 地理範圍（台灣海域）
LON_MIN, LON_MAX = 117.0, 127.0
LAT_MIN, LAT_MAX = 20.0, 28.0

INTERVAL_MINUTES = 10
MAX_SPEED_KNOTS = 45   # 速度閾值（節）
PORT_RADIUS_KM = 1.5   # 港口圍欄預設半徑（公里）
PORT_DWELL_SEC = 3600   # 港內停泊超過此秒數才切（1 小時）

# 大港使用較大半徑
LARGE_PORT_RADIUS_KM = 3.0
LARGE_PORTS = {'高雄港', '基隆港', '臺中港', '花蓮港', '台北港', '蘇澳港', '安平港'}

# 無效 MMSI 黑名單
MMSI_BLACKLIST = {
    0, 1, 111111111, 123456789, 200000000,
    666666666, 888888888, 999999999,
}


def is_invalid_mmsi(mmsi_str):
    """判斷 MMSI 是否無效。"""
    try:
        m = int(mmsi_str)
    except (ValueError, TypeError):
        return True
    if m in MMSI_BLACKLIST:
        return True
    if m < 100000000 or m > 799999999:
        return True
    if m % 1000000 == 0:
        return True
    return False


# ============================================================
# 地理工具函式
# ============================================================

def haversine_nm(lon1, lat1, lon2, lat2):
    """計算兩點間距離（海浬）。"""
    R_NM = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return 2 * R_NM * math.asin(math.sqrt(a))


def haversine_km(lon1, lat1, lon2, lat2):
    """計算兩點間距離（公里）。"""
    return haversine_nm(lon1, lat1, lon2, lat2) * 1.852


def point_in_polygon(lon, lat, polygon):
    """Ray casting 判斷點是否在多邊形內。polygon = [[lon,lat], ...]"""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def segments_intersect(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
    """判斷兩條線段是否相交。"""
    def cross(ox, oy, ax, ay, bx, by):
        return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)

    d1 = cross(bx1, by1, bx2, by2, ax1, ay1)
    d2 = cross(bx1, by1, bx2, by2, ax2, ay2)
    d3 = cross(ax1, ay1, ax2, ay2, bx1, by1)
    d4 = cross(ax1, ay1, ax2, ay2, bx2, by2)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def line_crosses_polygon(lon1, lat1, lon2, lat2, polygon):
    """判斷線段是否穿越多邊形邊界。"""
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        if segments_intersect(
            lon1, lat1, lon2, lat2,
            polygon[i][0], polygon[i][1],
            polygon[j][0], polygon[j][1],
        ):
            return True
    return False


# ============================================================
# 載入地理資料
# ============================================================

def load_ports():
    """載入港口座標，回傳 [(lon, lat, radius_km, name), ...]"""
    port_path = os.path.join(DATA_DIR, 'ports.geojson')
    if not os.path.exists(port_path):
        print(f"[warn] 港口資料不存在: {port_path}，跳過港口圍欄")
        return []

    with open(port_path, encoding='utf-8') as f:
        data = json.load(f)

    ports = []
    for feat in data['features']:
        geom = feat['geometry']
        if geom['type'] != 'Point':
            continue
        lon, lat = geom['coordinates']
        name = feat['properties'].get('PortName', '')
        radius = LARGE_PORT_RADIUS_KM if name in LARGE_PORTS else PORT_RADIUS_KM
        ports.append((lon, lat, radius, name))

    print(f"載入 {len(ports)} 個港口（大港 {LARGE_PORT_RADIUS_KM}km / 小港 {PORT_RADIUS_KM}km）")
    return ports


def load_land_polygons():
    """載入台灣陸地多邊形，回傳 [polygon, ...]（每個 polygon 是 [[lon,lat], ...]）"""
    land_path = os.path.join(DATA_DIR, 'taiwan_land.json')
    if not os.path.exists(land_path):
        print(f"[warn] 陸地資料不存在: {land_path}，跳過陸地穿越檢測")
        return []

    with open(land_path, encoding='utf-8') as f:
        data = json.load(f)

    polygons = []
    for key, value in data.items():
        if key == '_meta':
            continue
        # 判斷是單一多邊形還是多邊形群
        if isinstance(value[0][0], (int, float)):
            # 單一多邊形 [[lon,lat], ...]
            polygons.append(value)
        else:
            # 多邊形群 [[[lon,lat], ...], ...]
            polygons.extend(value)

    total_pts = sum(len(p) for p in polygons)
    print(f"載入 {len(polygons)} 個陸地多邊形（共 {total_pts} 點）")
    return polygons


def is_in_port(lon, lat, ports):
    """判斷座標是否在任一港口圍欄內。"""
    for plng, plat, radius_km, _ in ports:
        if haversine_km(lon, lat, plng, plat) <= radius_km:
            return True
    return False


def crosses_land(lon1, lat1, lon2, lat2, land_polygons):
    """判斷兩點之間的直線是否穿越任一陸地多邊形。
    只檢測台灣本島（第一個多邊形，最大的那個），離島太小不太會被穿越。"""
    if not land_polygons:
        return False
    # 快速篩選：兩點距離很近就跳過（< 0.05 度 ≈ 5km）
    if abs(lon2 - lon1) < 0.05 and abs(lat2 - lat1) < 0.05:
        return False
    # 只檢查前幾個最大的多邊形（台灣本島 + 澎湖主島）
    for poly in land_polygons[:5]:
        if len(poly) < 10:
            continue  # 跳過太小的島
        if line_crosses_polygon(lon1, lat1, lon2, lat2, poly):
            return True
    return False


# ============================================================
# 軌跡處理
# ============================================================

def is_jump(p1, p2):
    """判斷兩點之間是否為異常跳躍（速度 > 45kt）。"""
    dt_hours = (p2[0] - p1[0]) / 3600.0
    if dt_hours <= 0:
        return False
    dist = haversine_nm(p1[1], p1[2], p2[1], p2[2])
    speed = dist / dt_hours
    return speed > MAX_SPEED_KNOTS


def filter_track_outliers(points):
    """過濾 GPS 跳點（純速度判斷，不做時間切分）。"""
    if len(points) <= 1:
        return points

    filtered = [points[0]]
    consecutive_bad = 0

    i = 1
    while i < len(points):
        prev = filtered[-1]
        curr = points[i]

        if not is_jump(prev, curr):
            filtered.append(curr)
            consecutive_bad = 0
            i += 1
            continue

        # curr 看起來是跳點 — 往前看一個點決定
        if i + 1 < len(points):
            nxt = points[i + 1]
            curr_to_nxt_ok = not is_jump(curr, nxt)
            prev_to_nxt_ok = not is_jump(prev, nxt)

            if curr_to_nxt_ok and not prev_to_nxt_ok:
                filtered[-1] = curr
                consecutive_bad = 0
                i += 1
                continue

        consecutive_bad += 1
        if consecutive_bad >= 5:
            break
        i += 1

    return filtered


def split_trajectory_geo(points, ports, land_polygons):
    """地理感知的軌跡切段。

    切段條件：
    1. 速度 > 45kt → 切（GPS 異常）
    2. 穿越台灣本島 → 切
    3. 在港口內連續停泊 > 1hr → 切

    其他所有情況（含外海長時間停泊）→ 不切。

    Args:
        points: [(ts_sec, lon, lat, sog, cog, vtype), ...]（單一 MMSI，已按時間排序）
        ports: 港口列表
        land_polygons: 陸地多邊形列表
    Returns:
        list of segments，每段也是 [(ts_sec, lon, lat, sog, cog, vtype), ...]
    """
    if len(points) <= 1:
        return [points] if points else []

    segments = []
    current_seg = [points[0]]

    # 追蹤港內停泊狀態
    port_dwell_start = None  # 進入港口且 sog≈0 的時間
    in_port_stopped = False

    for i in range(1, len(points)):
        prev = points[i - 1]
        curr = points[i]
        should_cut = False

        # 條件 1：速度異常
        dt_hours = (curr[0] - prev[0]) / 3600.0
        if dt_hours > 0:
            dist = haversine_nm(prev[1], prev[2], curr[1], curr[2])
            speed = dist / dt_hours
            if speed > MAX_SPEED_KNOTS:
                should_cut = True

        # 條件 2：穿越陸地
        if not should_cut and land_polygons:
            if crosses_land(prev[1], prev[2], curr[1], curr[2], land_polygons):
                should_cut = True

        # 條件 3：港口停泊判斷
        if not should_cut and ports:
            curr_sog = curr[3]
            curr_in_port = is_in_port(curr[1], curr[2], ports)

            if curr_in_port and curr_sog < 0.5:
                if port_dwell_start is None:
                    port_dwell_start = curr[0]
                elif curr[0] - port_dwell_start > PORT_DWELL_SEC:
                    # 港內停泊超過 1 小時 → 切
                    should_cut = True
                    port_dwell_start = curr[0]  # 重置
            else:
                port_dwell_start = None

        if should_cut:
            if len(current_seg) >= 1:
                segments.append(current_seg)
            current_seg = [curr]
            port_dwell_start = None
        else:
            current_seg.append(curr)

    if current_seg:
        segments.append(current_seg)

    return segments


# ============================================================
# 低速錨點策略
# ============================================================

def apply_anchor_strategy(points):
    """低速點（sog < 0.5）只保留邊界錨點，減少資料量。

    - 移動→停 的第一個低速點 → 保留
    - 停→移動 前的最後低速點 → 保留
    - 連續停泊中間 → 跳過
    """
    if len(points) <= 2:
        return points, 0

    filtered = []
    dropped = 0
    for i, pt in enumerate(points):
        sog = pt[3]
        if sog >= 0.5:
            filtered.append(pt)
        else:
            prev_moving = (i > 0 and points[i - 1][3] >= 0.5)
            next_moving = (i < len(points) - 1 and points[i + 1][3] >= 0.5)
            if prev_moving or next_moving:
                filtered.append(pt)
            else:
                dropped += 1
    return filtered, dropped


# ============================================================
# 主流程
# ============================================================

def align_time(ts_str, interval_min=INTERVAL_MINUTES):
    """將時間戳對齊到最近的 interval 分鐘邊界。"""
    dt = datetime.fromisoformat(ts_str)
    minutes = (dt.minute // interval_min) * interval_min
    return dt.replace(minute=minutes, second=0, microsecond=0)


def get_time_range(args, cursor):
    """計算查詢時間範圍。"""
    if args.start and args.end:
        return args.start, args.end

    cursor.execute("SELECT MAX(timestamp) FROM ship_positions")
    max_ts = cursor.fetchone()[0]
    if not max_ts:
        raise ValueError("資料庫為空")

    end_dt = datetime.fromisoformat(max_ts)
    start_dt = end_dt - timedelta(days=args.days)
    return start_dt.isoformat(), end_dt.isoformat()


def generate_arrow_files(args):
    db_path = args.db_path or DB_PATH
    output_dir = args.output_dir or OUTPUT_DIR

    os.makedirs(output_dir, exist_ok=True)

    # 載入地理資料
    ports = load_ports()
    land_polygons = load_land_polygons()

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()

    start_ts, end_ts = get_time_range(args, cursor)
    print(f"時間範圍: {start_ts} ~ {end_ts}")

    # 查詢所有資料
    cursor.execute("""
        SELECT mmsi, timestamp, lon, lat, sog, cog, vessel_type
        FROM ship_positions
        WHERE timestamp >= ? AND timestamp <= ?
          AND lon >= ? AND lon <= ?
          AND lat >= ? AND lat <= ?
        ORDER BY timestamp, mmsi
    """, (start_ts, end_ts, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX))

    # 收集並按時間對齊
    time_slots = {}
    row_count = 0
    skipped_mmsi = 0
    for mmsi, ts, lon, lat, sog, cog, vtype in cursor:
        if is_invalid_mmsi(mmsi):
            skipped_mmsi += 1
            continue
        aligned = align_time(ts)
        key = aligned.isoformat()
        if key not in time_slots:
            time_slots[key] = {}
        time_slots[key][mmsi] = (lon, lat, sog or 0, cog or 0, vtype or 0)
        row_count += 1

    conn.close()
    print(f"原始資料: {row_count} 筆, 時間幀: {len(time_slots)} 個")
    if skipped_mmsi > 0:
        print(f"已過濾無效 MMSI: {skipped_mmsi} 筆")

    sorted_times = sorted(time_slots.keys())
    base_dt = datetime.fromisoformat(sorted_times[0])
    base_ts = base_dt.timestamp()

    # === 產出 positions.arrow（所有船舶）===
    pos_timestamps = []
    pos_mmsi = []
    pos_lon = []
    pos_lat = []
    pos_sog = []
    pos_cog = []
    pos_vtype = []

    for ts_key in sorted_times:
        ts_sec = datetime.fromisoformat(ts_key).timestamp() - base_ts
        ships = time_slots[ts_key]
        for mmsi, (lon, lat, sog, cog, vtype) in ships.items():
            pos_timestamps.append(ts_sec)
            pos_mmsi.append(int(mmsi) if isinstance(mmsi, str) else mmsi)
            pos_lon.append(lon)
            pos_lat.append(lat)
            pos_sog.append(sog)
            pos_cog.append(cog)
            pos_vtype.append(vtype)

    pos_table = pa.table({
        'timestamp': pa.array(pos_timestamps, type=pa.float32()),
        'mmsi': pa.array(pos_mmsi, type=pa.uint32()),
        'lon': pa.array(pos_lon, type=pa.float32()),
        'lat': pa.array(pos_lat, type=pa.float32()),
        'sog': pa.array(pos_sog, type=pa.float32()),
        'cog': pa.array(pos_cog, type=pa.float32()),
        'vessel_type': pa.array(pos_vtype, type=pa.uint8()),
    })

    metadata = {
        b'base_timestamp': str(base_ts).encode(),
        b'base_datetime': sorted_times[0].encode(),
        b'end_datetime': sorted_times[-1].encode(),
        b'total_frames': str(len(sorted_times)).encode(),
        b'interval_minutes': str(INTERVAL_MINUTES).encode(),
        b'frame_times': ','.join(
            f"{(datetime.fromisoformat(t).timestamp() - base_ts):.0f}"
            for t in sorted_times
        ).encode(),
    }
    pos_table = pos_table.replace_schema_metadata(metadata)

    pos_path = os.path.join(output_dir, 'positions.arrow')
    with ipc.RecordBatchFileWriter(pos_path, pos_table.schema) as writer:
        writer.write_table(pos_table)
    pos_size = os.path.getsize(pos_path) / 1024 / 1024
    print(f"positions.arrow: {len(pos_timestamps)} 筆, {pos_size:.1f} MB")

    # === 產出 trajectory.arrow ===
    traj_timestamps = []
    traj_mmsi = []
    traj_lon = []
    traj_lat = []
    traj_sog = []
    traj_cog = []
    traj_vtype = []
    traj_seg_id = []

    # 按 MMSI 分組收集所有點（含低速點）
    ship_all_points = {}
    for ts_key in sorted_times:
        ts_sec = datetime.fromisoformat(ts_key).timestamp() - base_ts
        ships = time_slots[ts_key]
        for mmsi, (lon, lat, sog, cog, vtype) in ships.items():
            mmsi_int = int(mmsi) if isinstance(mmsi, str) else mmsi
            if mmsi_int not in ship_all_points:
                ship_all_points[mmsi_int] = []
            ship_all_points[mmsi_int].append((ts_sec, lon, lat, sog, cog, vtype))

    # 處理流程：錨點策略 → 地理切段 → GPS 跳點過濾
    total_anchored_dropped = 0
    total_outliers = 0
    total_land_cuts = 0
    total_port_cuts = 0
    total_speed_cuts = 0
    total_segments = 0

    for mmsi_int in sorted(ship_all_points.keys()):
        raw_points = ship_all_points[mmsi_int]

        # 1. 錨點策略：減少連續停泊的冗餘點
        anchored, dropped = apply_anchor_strategy(raw_points)
        total_anchored_dropped += dropped

        # 2. 地理感知切段
        geo_segments = split_trajectory_geo(anchored, ports, land_polygons)

        for seg in geo_segments:
            # 3. GPS 跳點過濾
            clean = filter_track_outliers(seg)
            total_outliers += len(seg) - len(clean)

            if len(clean) < 2:
                continue

            total_segments += 1
            for pt in clean:
                traj_timestamps.append(pt[0])
                traj_mmsi.append(mmsi_int)
                traj_lon.append(pt[1])
                traj_lat.append(pt[2])
                traj_sog.append(pt[3])
                traj_cog.append(pt[4])
                traj_vtype.append(pt[5])
                traj_seg_id.append(total_segments)

    # 統計
    print(f"已跳過連續停泊點: {total_anchored_dropped} 筆")
    print(f"已過濾 GPS 跳點: {total_outliers} 筆")
    print(f"trajectory.arrow: {len(traj_timestamps)} 筆 ({len(ship_all_points)} 艘船, {total_segments} 段)")

    traj_table = pa.table({
        'timestamp': pa.array(traj_timestamps, type=pa.float32()),
        'mmsi': pa.array(traj_mmsi, type=pa.uint32()),
        'lon': pa.array(traj_lon, type=pa.float32()),
        'lat': pa.array(traj_lat, type=pa.float32()),
        'sog': pa.array(traj_sog, type=pa.float32()),
        'cog': pa.array(traj_cog, type=pa.float32()),
        'vessel_type': pa.array(traj_vtype, type=pa.uint8()),
        'segment_id': pa.array(traj_seg_id, type=pa.uint32()),
    })

    traj_table = traj_table.replace_schema_metadata(metadata)

    traj_path = os.path.join(output_dir, 'trajectory.arrow')
    with ipc.RecordBatchFileWriter(traj_path, traj_table.schema) as writer:
        writer.write_table(traj_table)
    traj_size = os.path.getsize(traj_path) / 1024 / 1024
    print(f"trajectory.arrow: {traj_size:.1f} MB")

    # 複製 ports.geojson 到輸出目錄（前端需要）
    ports_src = os.path.join(DATA_DIR, 'ports.geojson')
    ports_dst = os.path.join(output_dir, 'ports.geojson')
    if os.path.exists(ports_src):
        shutil.copy2(ports_src, ports_dst)
        print(f"ports.geojson → {ports_dst}")


def main():
    parser = argparse.ArgumentParser(description='從 SQLite 產出 Arrow IPC 檔案')
    parser.add_argument('--days', type=int, default=7, help='取最近 N 天資料（預設 7）')
    parser.add_argument('--start', type=str, help='起始時間 (ISO 格式)')
    parser.add_argument('--end', type=str, help='結束時間 (ISO 格式)')
    parser.add_argument('--db-path', type=str, help=f'SQLite 路徑（預設 {DB_PATH}）')
    parser.add_argument('--output-dir', type=str, help=f'輸出目錄（預設 {OUTPUT_DIR}）')
    args = parser.parse_args()

    generate_arrow_files(args)
    print('完成!')


if __name__ == '__main__':
    main()
