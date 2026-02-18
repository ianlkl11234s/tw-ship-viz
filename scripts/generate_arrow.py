#!/usr/bin/env python3
"""
從 SQLite 產出 Apache Arrow IPC 檔案，供前端 deck.gl 使用。

產出兩個檔案：
  - positions.arrow: 所有船舶位置（密度/六角/熱力圖模式用）
  - trajectory.arrow: 船舶軌跡，按 MMSI 排序（軌跡動畫用）

記憶體最佳化：兩階段串流處理，峰值 < 500 MB。
  - Pass 1: positions.arrow — 逐時間幀串流，一次只在記憶體中保留一個 slot
  - Pass 2: trajectory.arrow — 逐船串流（ORDER BY mmsi），一次只處理一艘船

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
import gc
import json
import math
import os
import shutil
import sqlite3
from array import array
from datetime import datetime, timedelta

import numpy as np
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
    """判斷 MMSI 是否無效（含航標 AtoN）。"""
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
    # 99xxxx 開頭 = 航標 (Aid to Navigation)，不是船舶
    if 990000000 <= m <= 999999999:
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
        props = feat['properties']
        name = props.get('name', '')
        port_class = props.get('port_class', '')
        source = props.get('source', '')
        # 依 port_class 決定半徑
        if name in LARGE_PORTS:
            radius = LARGE_PORT_RADIUS_KM
        elif source == 'TDX' or port_class == '客運港':
            radius = PORT_RADIUS_KM
        elif port_class == '第一類漁港':
            radius = 1.0
        else:
            radius = 0.5
        ports.append((lon, lat, radius, name))

    print(f"載入 {len(ports)} 個港口")
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


def point_on_land(lon, lat, land_polygons):
    """判斷點是否落在任一陸地多邊形內。"""
    for poly in land_polygons:
        # 快速 bounding box 篩選
        if not _bbox_contains(poly, lon, lat):
            continue
        if point_in_polygon(lon, lat, poly):
            return True
    return False


def crosses_land(lon1, lat1, lon2, lat2, land_polygons):
    """判斷兩點之間的直線是否穿越任一陸地多邊形。"""
    if not land_polygons:
        return False
    # 線段 bounding box
    min_lon = min(lon1, lon2)
    max_lon = max(lon1, lon2)
    min_lat = min(lat1, lat2)
    max_lat = max(lat1, lat2)
    for poly in land_polygons:
        # 快速 bounding box 篩選：線段 bbox 與多邊形 bbox 不重疊就跳過
        bbox = _get_bbox(poly)
        if max_lon < bbox[0] or min_lon > bbox[1] or max_lat < bbox[2] or min_lat > bbox[3]:
            continue
        if line_crosses_polygon(lon1, lat1, lon2, lat2, poly):
            return True
    return False


# 多邊形 bounding box 快取
_bbox_cache = {}


def _get_bbox(poly):
    """取得多邊形的 bounding box (min_lon, max_lon, min_lat, max_lat)。"""
    pid = id(poly)
    if pid not in _bbox_cache:
        lons = [p[0] for p in poly]
        lats = [p[1] for p in poly]
        _bbox_cache[pid] = (min(lons), max(lons), min(lats), max(lats))
    return _bbox_cache[pid]


def _bbox_contains(poly, lon, lat):
    """快速判斷點是否在多邊形 bounding box 內。"""
    bbox = _get_bbox(poly)
    return bbox[0] <= lon <= bbox[1] and bbox[2] <= lat <= bbox[3]


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
    """
    if len(points) <= 1:
        return [points] if points else []

    segments = []
    current_seg = [points[0]]

    # 追蹤港內停泊狀態
    port_dwell_start = None
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
    """低速點（sog < 0.5）只保留邊界錨點，減少資料量。"""
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
# 共用工具
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


def _query_params(start_ts, end_ts):
    """共用 SQL WHERE 參數。"""
    return (start_ts, end_ts, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)


# ============================================================
# Pass 1: positions.arrow（逐時間幀串流）
# ============================================================

def generate_positions_arrow(conn, start_ts, end_ts, land_polygons, output_dir):
    """產出 positions.arrow。

    串流處理：一次只在記憶體中保留一個時間幀的 ship dict（~6000 entries）。
    使用 array.array 儲存結果（4 bytes/element），比 Python list（~32 bytes/element）省 8 倍記憶體。

    回傳共用 metadata dict，供 Pass 2 使用。
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT mmsi, timestamp, lon, lat, sog, cog, vessel_type
        FROM ship_positions
        WHERE timestamp >= ? AND timestamp <= ?
          AND lon >= ? AND lon <= ?
          AND lat >= ? AND lat <= ?
        ORDER BY timestamp, mmsi
    """, _query_params(start_ts, end_ts))

    # array.array: 每個元素 4 bytes（float32/uint32）或 1 byte（uint8）
    pos_ts = array('f')
    pos_mmsi = array('I')
    pos_lon = array('f')
    pos_lat = array('f')
    pos_sog = array('f')
    pos_cog = array('f')
    pos_vtype = array('B')

    current_slot = None
    slot_ships = {}
    all_slots = []
    base_ts = None
    row_count = 0
    skipped_mmsi = 0
    land_removed = 0

    def flush_slot():
        nonlocal land_removed
        ts_sec = datetime.fromisoformat(current_slot).timestamp() - base_ts
        for mmsi_key, (lo, la, s, c, v) in slot_ships.items():
            if land_polygons and point_on_land(lo, la, land_polygons):
                land_removed += 1
                continue
            mmsi_int = int(mmsi_key) if isinstance(mmsi_key, str) else mmsi_key
            pos_ts.append(ts_sec)
            pos_mmsi.append(mmsi_int)
            pos_lon.append(lo)
            pos_lat.append(la)
            pos_sog.append(s)
            pos_cog.append(c)
            pos_vtype.append(v)

    for mmsi, ts, lon, lat, sog, cog, vtype in cursor:
        if is_invalid_mmsi(mmsi):
            skipped_mmsi += 1
            continue
        row_count += 1

        aligned = align_time(ts)
        slot_key = aligned.isoformat()

        if base_ts is None:
            base_ts = aligned.timestamp()

        if slot_key != current_slot:
            if current_slot is not None:
                flush_slot()
                all_slots.append(current_slot)
            current_slot = slot_key
            slot_ships = {}

        slot_ships[mmsi] = (lon, lat, sog or 0, cog or 0, vtype or 0)

    # Flush last slot
    if current_slot is not None and slot_ships:
        flush_slot()
        all_slots.append(current_slot)

    print(f"原始資料: {row_count} 筆, 時間幀: {len(all_slots)} 個")
    if skipped_mmsi:
        print(f"已過濾無效 MMSI: {skipped_mmsi} 筆")
    if land_removed:
        print(f"positions: 移除陸地上的點 {land_removed} 筆")

    if not all_slots:
        print("無有效資料")
        return None

    # array.array → numpy（零拷貝 view）→ pyarrow
    pos_table = pa.table({
        'timestamp': pa.array(np.frombuffer(pos_ts, dtype=np.float32)),
        'mmsi': pa.array(np.frombuffer(pos_mmsi, dtype=np.uint32)),
        'lon': pa.array(np.frombuffer(pos_lon, dtype=np.float32)),
        'lat': pa.array(np.frombuffer(pos_lat, dtype=np.float32)),
        'sog': pa.array(np.frombuffer(pos_sog, dtype=np.float32)),
        'cog': pa.array(np.frombuffer(pos_cog, dtype=np.float32)),
        'vessel_type': pa.array(np.frombuffer(pos_vtype, dtype=np.uint8)),
    })

    metadata = {
        b'base_timestamp': str(base_ts).encode(),
        b'base_datetime': all_slots[0].encode(),
        b'end_datetime': all_slots[-1].encode(),
        b'total_frames': str(len(all_slots)).encode(),
        b'interval_minutes': str(INTERVAL_MINUTES).encode(),
        b'frame_times': ','.join(
            f"{(datetime.fromisoformat(t).timestamp() - base_ts):.0f}"
            for t in all_slots
        ).encode(),
    }
    pos_table = pos_table.replace_schema_metadata(metadata)

    pos_path = os.path.join(output_dir, 'positions.arrow')
    write_opts = ipc.IpcWriteOptions(compression='zstd')
    with ipc.RecordBatchFileWriter(pos_path, pos_table.schema, options=write_opts) as writer:
        writer.write_table(pos_table)
    pos_size = os.path.getsize(pos_path) / 1024 / 1024
    print(f"positions.arrow: {len(pos_ts)} 筆, {pos_size:.1f} MB")

    return {'base_ts': base_ts, 'all_slots': all_slots, 'metadata': metadata}


# ============================================================
# Pass 1b: positions 按日分檔（漸進式載入用）
# ============================================================

def generate_positions_daily(conn, start_ts, end_ts, land_polygons, output_dir):
    """按日產出 positions_YYYYMMDD.arrow + manifest.json。

    與 generate_positions_arrow() 共用相同的串流邏輯，但每跨日邊界就寫出一個 Arrow 檔。
    最後寫入 manifest.json 供前端漸進式載入。
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT mmsi, timestamp, lon, lat, sog, cog, vessel_type
        FROM ship_positions
        WHERE timestamp >= ? AND timestamp <= ?
          AND lon >= ? AND lon <= ?
          AND lat >= ? AND lat <= ?
        ORDER BY timestamp, mmsi
    """, _query_params(start_ts, end_ts))

    base_ts = None
    current_slot = None
    current_day = None
    slot_ships = {}

    # Per-day accumulators
    day_ts = array('f')
    day_mmsi = array('I')
    day_lon = array('f')
    day_lat = array('f')
    day_sog = array('f')
    day_cog = array('f')
    day_vtype = array('B')
    day_slots = []

    # Global tracking
    manifest_days = []
    all_slots = []
    row_count = 0
    skipped_mmsi = 0
    land_removed = 0

    def flush_slot():
        nonlocal land_removed
        ts_sec = datetime.fromisoformat(current_slot).timestamp() - base_ts
        for mmsi_key, (lo, la, s, c, v) in slot_ships.items():
            if land_polygons and point_on_land(lo, la, land_polygons):
                land_removed += 1
                continue
            mmsi_int = int(mmsi_key) if isinstance(mmsi_key, str) else mmsi_key
            day_ts.append(ts_sec)
            day_mmsi.append(mmsi_int)
            day_lon.append(lo)
            day_lat.append(la)
            day_sog.append(s)
            day_cog.append(c)
            day_vtype.append(v)

    def reset_day():
        nonlocal day_ts, day_mmsi, day_lon, day_lat, day_sog, day_cog, day_vtype, day_slots
        day_ts = array('f')
        day_mmsi = array('I')
        day_lon = array('f')
        day_lat = array('f')
        day_sog = array('f')
        day_cog = array('f')
        day_vtype = array('B')
        day_slots = []

    def flush_day():
        if not day_ts or not day_slots:
            reset_day()
            return

        frame_times = [
            round(datetime.fromisoformat(t).timestamp() - base_ts)
            for t in day_slots
        ]

        filename = f"positions_{current_day.replace('-', '')}.arrow"
        filepath = os.path.join(output_dir, filename)

        pos_table = pa.table({
            'timestamp': pa.array(np.frombuffer(day_ts, dtype=np.float32)),
            'mmsi': pa.array(np.frombuffer(day_mmsi, dtype=np.uint32)),
            'lon': pa.array(np.frombuffer(day_lon, dtype=np.float32)),
            'lat': pa.array(np.frombuffer(day_lat, dtype=np.float32)),
            'sog': pa.array(np.frombuffer(day_sog, dtype=np.float32)),
            'cog': pa.array(np.frombuffer(day_cog, dtype=np.float32)),
            'vessel_type': pa.array(np.frombuffer(day_vtype, dtype=np.uint8)),
        })

        file_meta = {
            b'base_timestamp': str(base_ts).encode(),
            b'frame_times': ','.join(f"{ft:.0f}" for ft in frame_times).encode(),
            b'total_frames': str(len(day_slots)).encode(),
            b'interval_minutes': str(INTERVAL_MINUTES).encode(),
        }
        pos_table = pos_table.replace_schema_metadata(file_meta)

        write_opts = ipc.IpcWriteOptions(compression='zstd')
        with ipc.RecordBatchFileWriter(filepath, pos_table.schema, options=write_opts) as writer:
            writer.write_table(pos_table)

        file_size = os.path.getsize(filepath) / 1024 / 1024
        print(f"  {filename}: {len(day_ts)} 筆, {len(day_slots)} 幀, {file_size:.1f} MB")

        manifest_days.append({
            'date': current_day,
            'file': filename,
            'frames': len(day_slots),
            'frame_times': frame_times,
        })

        reset_day()

    # Main streaming loop
    for mmsi, ts, lon, lat, sog, cog, vtype in cursor:
        if is_invalid_mmsi(mmsi):
            skipped_mmsi += 1
            continue
        row_count += 1

        aligned = align_time(ts)
        slot_key = aligned.isoformat()
        day_key = aligned.date().isoformat()

        if base_ts is None:
            base_ts = aligned.timestamp()

        # Day boundary → flush previous slot + day
        if day_key != current_day:
            if current_slot is not None:
                flush_slot()
                day_slots.append(current_slot)
                all_slots.append(current_slot)
            if current_day is not None:
                flush_day()
            current_day = day_key
            current_slot = None
            slot_ships = {}

        # Slot boundary → flush previous slot
        if slot_key != current_slot:
            if current_slot is not None:
                flush_slot()
                day_slots.append(current_slot)
                all_slots.append(current_slot)
            current_slot = slot_key
            slot_ships = {}

        slot_ships[mmsi] = (lon, lat, sog or 0, cog or 0, vtype or 0)

    # Flush last slot and day
    if current_slot is not None and slot_ships:
        flush_slot()
        day_slots.append(current_slot)
        all_slots.append(current_slot)
    if current_day is not None:
        flush_day()

    print(f"原始資料: {row_count} 筆, 時間幀: {len(all_slots)} 個, {len(manifest_days)} 天")
    if skipped_mmsi:
        print(f"已過濾無效 MMSI: {skipped_mmsi} 筆")
    if land_removed:
        print(f"positions: 移除陸地上的點 {land_removed} 筆")

    if not manifest_days:
        print("無有效資料")
        return None

    # Write manifest.json（最後寫，原子性保證：前端讀不到半成品）
    total_frames = sum(d['frames'] for d in manifest_days)
    manifest = {
        'version': 2,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'base_timestamp': base_ts,
        'base_datetime': all_slots[0] if all_slots else '',
        'end_datetime': all_slots[-1] if all_slots else '',
        'interval_minutes': INTERVAL_MINUTES,
        'trajectory': {'file': 'trajectory.arrow'},
        'positions': {
            'days': manifest_days,
            'total_frames': total_frames,
        },
    }

    manifest_path = os.path.join(output_dir, 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"manifest.json: {len(manifest_days)} 天, {total_frames} 幀")

    # Return metadata for Pass 2（格式與 monolithic 相同）
    pa_metadata = {
        b'base_timestamp': str(base_ts).encode(),
        b'base_datetime': all_slots[0].encode() if all_slots else b'',
        b'end_datetime': all_slots[-1].encode() if all_slots else b'',
        b'total_frames': str(total_frames).encode(),
        b'interval_minutes': str(INTERVAL_MINUTES).encode(),
        b'frame_times': ','.join(
            f"{(datetime.fromisoformat(t).timestamp() - base_ts):.0f}"
            for t in all_slots
        ).encode(),
    }

    return {'base_ts': base_ts, 'all_slots': all_slots, 'metadata': pa_metadata}


# ============================================================
# Pass 2: trajectory.arrow（逐船串流）
# ============================================================

def generate_trajectory_arrow(conn, start_ts, end_ts, ports, land_polygons, output_dir, meta):
    """產出 trajectory.arrow。

    逐 MMSI 串流處理：每次只在記憶體中保留一艘船的資料（~2000 points）。
    ORDER BY mmsi, timestamp 確保同一艘船的資料連續出現。
    """
    base_ts = meta['base_ts']
    pa_metadata = meta['metadata']

    cursor = conn.cursor()
    cursor.execute("""
        SELECT mmsi, timestamp, lon, lat, sog, cog, vessel_type
        FROM ship_positions
        WHERE timestamp >= ? AND timestamp <= ?
          AND lon >= ? AND lon <= ?
          AND lat >= ? AND lat <= ?
        ORDER BY mmsi, timestamp
    """, _query_params(start_ts, end_ts))

    traj_ts = array('f')
    traj_mmsi = array('I')
    traj_lon = array('f')
    traj_lat = array('f')
    traj_sog = array('f')
    traj_cog = array('f')
    traj_vtype = array('B')
    traj_seg = array('I')

    current_mmsi = None
    mmsi_slots = {}   # {slot_key: (ts_sec, lon, lat, sog, cog, vtype)} — 當前船的時間幀
    total_segments = 0
    total_ships = 0
    total_anchor_dropped = 0
    total_land_removed = 0
    total_outliers = 0

    def process_ship(mmsi_int, slots):
        """處理單一船舶的軌跡：錨點策略 → 陸地過濾 → 地理切段 → 跳點過濾。"""
        nonlocal total_segments, total_anchor_dropped, total_land_removed, total_outliers

        sorted_keys = sorted(slots.keys())
        points = [slots[k] for k in sorted_keys]

        # 1. 錨點策略
        anchored, dropped = apply_anchor_strategy(points)
        total_anchor_dropped += dropped

        # 2. 陸地過濾
        if land_polygons:
            sea = [p for p in anchored if not point_on_land(p[1], p[2], land_polygons)]
            total_land_removed += len(anchored) - len(sea)
            anchored = sea

        # 3. 地理切段
        segments = split_trajectory_geo(anchored, ports, land_polygons)

        for seg in segments:
            # 4. GPS 跳點過濾
            clean = filter_track_outliers(seg)
            total_outliers += len(seg) - len(clean)

            if len(clean) < 2:
                continue

            total_segments += 1
            for pt in clean:
                traj_ts.append(pt[0])
                traj_mmsi.append(mmsi_int)
                traj_lon.append(pt[1])
                traj_lat.append(pt[2])
                traj_sog.append(pt[3])
                traj_cog.append(pt[4])
                traj_vtype.append(pt[5])
                traj_seg.append(total_segments)

    for mmsi, ts, lon, lat, sog, cog, vtype in cursor:
        if is_invalid_mmsi(mmsi):
            continue

        mmsi_int = int(mmsi) if isinstance(mmsi, str) else mmsi

        if mmsi_int != current_mmsi:
            if current_mmsi is not None and mmsi_slots:
                process_ship(current_mmsi, mmsi_slots)
                total_ships += 1
            current_mmsi = mmsi_int
            mmsi_slots = {}

        aligned = align_time(ts)
        slot_key = aligned.isoformat()
        ts_sec = datetime.fromisoformat(slot_key).timestamp() - base_ts
        mmsi_slots[slot_key] = (ts_sec, lon, lat, sog or 0, cog or 0, vtype or 0)

    # 最後一艘船
    if current_mmsi is not None and mmsi_slots:
        process_ship(current_mmsi, mmsi_slots)
        total_ships += 1

    print(f"已跳過連續停泊點: {total_anchor_dropped} 筆")
    print(f"已移除陸地上的點: {total_land_removed} 筆")
    print(f"已過濾 GPS 跳點: {total_outliers} 筆")
    print(f"trajectory: {len(traj_ts)} 筆 ({total_ships} 艘船, {total_segments} 段)")

    if not traj_ts:
        print("無有效軌跡資料")
        return

    traj_table = pa.table({
        'timestamp': pa.array(np.frombuffer(traj_ts, dtype=np.float32)),
        'mmsi': pa.array(np.frombuffer(traj_mmsi, dtype=np.uint32)),
        'lon': pa.array(np.frombuffer(traj_lon, dtype=np.float32)),
        'lat': pa.array(np.frombuffer(traj_lat, dtype=np.float32)),
        'sog': pa.array(np.frombuffer(traj_sog, dtype=np.float32)),
        'cog': pa.array(np.frombuffer(traj_cog, dtype=np.float32)),
        'vessel_type': pa.array(np.frombuffer(traj_vtype, dtype=np.uint8)),
        'segment_id': pa.array(np.frombuffer(traj_seg, dtype=np.uint32)),
    })

    traj_table = traj_table.replace_schema_metadata(pa_metadata)

    traj_path = os.path.join(output_dir, 'trajectory.arrow')
    write_opts = ipc.IpcWriteOptions(compression='zstd')
    with ipc.RecordBatchFileWriter(traj_path, traj_table.schema, options=write_opts) as writer:
        writer.write_table(traj_table)
    traj_size = os.path.getsize(traj_path) / 1024 / 1024
    print(f"trajectory.arrow: {traj_size:.1f} MB")


# ============================================================
# 主流程
# ============================================================

def generate_arrow_files(args):
    db_path = args.db_path or DB_PATH
    output_dir = args.output_dir or OUTPUT_DIR
    daily = getattr(args, 'daily', False) and not getattr(args, 'monolithic', False)

    os.makedirs(output_dir, exist_ok=True)

    # 載入地理資料（< 10 MB，可安全常駐記憶體）
    ports = load_ports()
    land_polygons = load_land_polygons()

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()

    try:
        start_ts, end_ts = get_time_range(args, cursor)
    except ValueError as e:
        print(f"[warn] {e}")
        conn.close()
        return

    print(f"時間範圍: {start_ts} ~ {end_ts}")

    # === Pass 1: positions ===
    if daily:
        print("\n=== Pass 1: positions (daily) ===")
        meta = generate_positions_daily(conn, start_ts, end_ts, land_polygons, output_dir)
    else:
        print("\n=== Pass 1: positions.arrow ===")
        meta = generate_positions_arrow(conn, start_ts, end_ts, land_polygons, output_dir)

    if meta is None:
        print("無資料可處理")
        conn.close()
        return

    # 釋放 Pass 1 的記憶體
    gc.collect()

    # === Pass 2: trajectory.arrow ===
    print("\n=== Pass 2: trajectory.arrow ===")
    generate_trajectory_arrow(conn, start_ts, end_ts, ports, land_polygons, output_dir, meta)

    conn.close()

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
    parser.add_argument('--daily', action='store_true', help='按日分檔 positions + manifest.json（漸進式載入）')
    parser.add_argument('--monolithic', action='store_true', help='產出單一 positions.arrow（舊模式）')
    args = parser.parse_args()

    generate_arrow_files(args)
    print('完成!')


if __name__ == '__main__':
    main()
