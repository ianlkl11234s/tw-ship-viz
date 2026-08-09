#!/usr/bin/env python3
"""
分析外海船舶軌跡消失原因
查詢 SQLite 資料庫，分析時間間隔、距離、速度等指標
"""
import sqlite3
import math
from collections import defaultdict

DB_PATH = '/Users/migu/Desktop/資料庫/gen_ai_try/ichef_工作用/GIS/ship-gis/data/ship_data.db'

def haversine_nm(lon1, lat1, lon2, lat2):
    """計算兩點之間的距離（海浬）"""
    R_NM = 3440.065  # 地球半徑（海浬）
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R_NM * c

def deg_jump(lon1, lat1, lon2, lat2):
    """計算經緯度最大跳躍（度）"""
    return max(abs(lon2 - lon1), abs(lat2 - lat1))

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ============================================================
# 0. 基本資訊
# ============================================================
print("=" * 80)
print("0. 資料庫基本資訊")
print("=" * 80)
cur.execute("SELECT COUNT(*) FROM ship_positions")
total = cur.fetchone()[0]
print(f"   總筆數: {total:,}")

cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM ship_positions")
ts_min, ts_max = cur.fetchone()
print(f"   時間範圍: {ts_min} ~ {ts_max}")

cur.execute("SELECT COUNT(DISTINCT mmsi) FROM ship_positions")
print(f"   不同 MMSI 數: {cur.fetchone()[0]:,}")

# 外海範圍
cur.execute("""
    SELECT COUNT(*) FROM ship_positions
    WHERE lon BETWEEN 119 AND 121 AND lat BETWEEN 22 AND 24
""")
open_water_count = cur.fetchone()[0]
print(f"   外海 (119-121, 22-24) 筆數: {open_water_count:,}")

cur.execute("""
    SELECT COUNT(DISTINCT mmsi) FROM ship_positions
    WHERE lon BETWEEN 119 AND 121 AND lat BETWEEN 22 AND 24
""")
print(f"   外海不同 MMSI 數: {cur.fetchone()[0]:,}")

# ============================================================
# 1. 外海船舶的時間間隔分析
# ============================================================
print("\n" + "=" * 80)
print("1. 外海船舶的時間間隔分析（經度 119-121, 緯度 22-24）")
print("=" * 80)

# 取出外海所有船的資料，按 MMSI + 時間排序
cur.execute("""
    SELECT mmsi, timestamp, lon, lat, sog
    FROM ship_positions
    WHERE lon BETWEEN 119 AND 121 AND lat BETWEEN 22 AND 24
    ORDER BY mmsi, timestamp
""")
rows_open = cur.fetchall()
print(f"   外海資料筆數: {len(rows_open):,}")

# 計算同 MMSI 相鄰紀錄的時間間隔
gaps_open = []
prev_mmsi = None
prev_ts = None
for mmsi, ts, lon, lat, sog in rows_open:
    if mmsi == prev_mmsi and prev_ts is not None:
        # 將 timestamp 轉為秒差
        # timestamp 格式可能是 ISO 或 unix
        try:
            dt = int(ts) - int(prev_ts)
        except (ValueError, TypeError):
            from datetime import datetime
            t1 = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            t0 = datetime.fromisoformat(prev_ts.replace('Z', '+00:00'))
            dt = (t1 - t0).total_seconds()
        gaps_open.append(dt)
    prev_mmsi = mmsi
    prev_ts = ts

total_gaps = len(gaps_open)
if total_gaps > 0:
    gaps_open.sort()

    print(f"\n   時間間隔統計（{total_gaps:,} 個間隔）:")
    print(f"   最小值: {min(gaps_open):.0f} 秒")
    print(f"   中位數: {gaps_open[total_gaps//2]:.0f} 秒")
    print(f"   平均值: {sum(gaps_open)/total_gaps:.0f} 秒")
    print(f"   75th:   {gaps_open[int(total_gaps*0.75)]:.0f} 秒")
    print(f"   90th:   {gaps_open[int(total_gaps*0.90)]:.0f} 秒")
    print(f"   95th:   {gaps_open[int(total_gaps*0.95)]:.0f} 秒")
    print(f"   99th:   {gaps_open[int(total_gaps*0.99)]:.0f} 秒")
    print(f"   最大值: {max(gaps_open):.0f} 秒")

    # 關鍵閾值
    gt_10m = sum(1 for g in gaps_open if g > 600)
    gt_30m = sum(1 for g in gaps_open if g > 1800)
    gt_1h = sum(1 for g in gaps_open if g > 3600)
    gt_2h = sum(1 for g in gaps_open if g > 7200)
    gt_4h = sum(1 for g in gaps_open if g > 14400)

    print(f"\n   間隔 > 10 分鐘: {gt_10m:,} ({gt_10m/total_gaps*100:.1f}%)")
    print(f"   間隔 > 30 分鐘: {gt_30m:,} ({gt_30m/total_gaps*100:.1f}%)")
    print(f"   間隔 > 1 小時:  {gt_1h:,} ({gt_1h/total_gaps*100:.1f}%)  ← MAX_GAP_SECONDS=3600 拆段閾值")
    print(f"   間隔 > 2 小時:  {gt_2h:,} ({gt_2h/total_gaps*100:.1f}%)")
    print(f"   間隔 > 4 小時:  {gt_4h:,} ({gt_4h/total_gaps*100:.1f}%)")

    # 間隔分佈直方圖
    print(f"\n   間隔分佈:")
    buckets = [
        (0, 60, "0-1 分"),
        (60, 300, "1-5 分"),
        (300, 600, "5-10 分"),
        (600, 1800, "10-30 分"),
        (1800, 3600, "30-60 分"),
        (3600, 7200, "1-2 小時"),
        (7200, 14400, "2-4 小時"),
        (14400, 86400, "4-24 小時"),
        (86400, float('inf'), "> 24 小時"),
    ]
    for lo, hi, label in buckets:
        cnt = sum(1 for g in gaps_open if lo <= g < hi)
        pct = cnt / total_gaps * 100
        bar = "#" * int(pct / 2)
        print(f"   {label:>12s}: {cnt:>6,} ({pct:>5.1f}%) {bar}")


# ============================================================
# 2. 外海 vs 近岸的間隔比較
# ============================================================
print("\n" + "=" * 80)
print("2. 外海 vs 近岸（高雄港）的時間間隔比較")
print("=" * 80)

cur.execute("""
    SELECT mmsi, timestamp, lon, lat, sog
    FROM ship_positions
    WHERE lon BETWEEN 120.2 AND 120.4 AND lat BETWEEN 22.5 AND 22.7
    ORDER BY mmsi, timestamp
""")
rows_coast = cur.fetchall()
print(f"   近岸（高雄港）資料筆數: {len(rows_coast):,}")

gaps_coast = []
prev_mmsi = None
prev_ts = None
for mmsi, ts, lon, lat, sog in rows_coast:
    if mmsi == prev_mmsi and prev_ts is not None:
        try:
            dt = int(ts) - int(prev_ts)
        except (ValueError, TypeError):
            from datetime import datetime
            t1 = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            t0 = datetime.fromisoformat(prev_ts.replace('Z', '+00:00'))
            dt = (t1 - t0).total_seconds()
        gaps_coast.append(dt)
    prev_mmsi = mmsi
    prev_ts = ts

if gaps_coast:
    gaps_coast.sort()
    total_coast = len(gaps_coast)

    print(f"\n   {'指標':>20s} {'外海':>12s} {'近岸(高雄港)':>12s}")
    print(f"   {'─'*20} {'─'*12} {'─'*12}")
    print(f"   {'間隔數':>20s} {total_gaps:>12,} {total_coast:>12,}")
    print(f"   {'中位數(秒)':>20s} {gaps_open[total_gaps//2]:>12.0f} {gaps_coast[total_coast//2]:>12.0f}")
    print(f"   {'平均值(秒)':>20s} {sum(gaps_open)/total_gaps:>12.0f} {sum(gaps_coast)/total_coast:>12.0f}")
    print(f"   {'90th(秒)':>20s} {gaps_open[int(total_gaps*0.90)]:>12.0f} {gaps_coast[int(total_coast*0.90)]:>12.0f}")

    gt_1h_open = sum(1 for g in gaps_open if g > 3600)
    gt_1h_coast = sum(1 for g in gaps_coast if g > 3600)
    print(f"   {'>1小時 比例':>20s} {gt_1h_open/total_gaps*100:>11.1f}% {gt_1h_coast/total_coast*100:>11.1f}%")

    gt_30m_open = sum(1 for g in gaps_open if g > 1800)
    gt_30m_coast = sum(1 for g in gaps_coast if g > 1800)
    print(f"   {'>30分鐘 比例':>20s} {gt_30m_open/total_gaps*100:>11.1f}% {gt_30m_coast/total_coast*100:>11.1f}%")


# ============================================================
# 3. 外海連續點的距離分析
# ============================================================
print("\n" + "=" * 80)
print("3. 外海連續點的距離分析")
print("=" * 80)

# 重新掃描外海資料，計算距離
distances = []
jump_degs = []
implied_speeds = []
large_jump_cases = []  # 距離 > 15 NM 的案例

prev_mmsi = None
prev_ts = None
prev_lon = None
prev_lat = None

for mmsi, ts, lon, lat, sog in rows_open:
    if mmsi == prev_mmsi and prev_ts is not None:
        try:
            dt = int(ts) - int(prev_ts)
        except (ValueError, TypeError):
            from datetime import datetime
            t1 = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            t0 = datetime.fromisoformat(prev_ts.replace('Z', '+00:00'))
            dt = (t1 - t0).total_seconds()

        dist_nm = haversine_nm(prev_lon, prev_lat, lon, lat)
        jdeg = deg_jump(prev_lon, prev_lat, lon, lat)
        distances.append(dist_nm)
        jump_degs.append(jdeg)

        if dt > 0:
            speed_kt = dist_nm / (dt / 3600)
            implied_speeds.append(speed_kt)
        else:
            speed_kt = 0
            implied_speeds.append(0)

        if dist_nm > 15:
            large_jump_cases.append({
                'mmsi': mmsi,
                'dist_nm': dist_nm,
                'dt_sec': dt,
                'speed_kt': speed_kt,
                'deg_jump': jdeg,
                'from': (prev_lon, prev_lat, prev_ts),
                'to': (lon, lat, ts),
            })

    prev_mmsi = mmsi
    prev_ts = ts
    prev_lon = lon
    prev_lat = lat

if distances:
    distances.sort()
    jump_degs.sort()
    total_d = len(distances)

    print(f"\n   距離統計（{total_d:,} 個間隔）:")
    print(f"   最小值: {distances[0]:.2f} NM")
    print(f"   中位數: {distances[total_d//2]:.2f} NM")
    print(f"   平均值: {sum(distances)/total_d:.2f} NM")
    print(f"   90th:   {distances[int(total_d*0.90)]:.2f} NM")
    print(f"   95th:   {distances[int(total_d*0.95)]:.2f} NM")
    print(f"   99th:   {distances[int(total_d*0.99)]:.2f} NM")
    print(f"   最大值: {distances[-1]:.2f} NM")

    gt_5nm = sum(1 for d in distances if d > 5)
    gt_10nm = sum(1 for d in distances if d > 10)
    gt_15nm = sum(1 for d in distances if d > 15)
    gt_25nm = sum(1 for d in distances if d > 25)

    print(f"\n   距離 > 5 NM:  {gt_5nm:,} ({gt_5nm/total_d*100:.1f}%)")
    print(f"   距離 > 10 NM: {gt_10nm:,} ({gt_10nm/total_d*100:.1f}%)")
    print(f"   距離 > 15 NM: {gt_15nm:,} ({gt_15nm/total_d*100:.1f}%)  ← 相當於 MAX_JUMP_DEG=0.25")
    print(f"   距離 > 25 NM: {gt_25nm:,} ({gt_25nm/total_d*100:.1f}%)")

    # MAX_JUMP_DEG 分析
    gt_025deg = sum(1 for j in jump_degs if j > 0.25)
    gt_05deg = sum(1 for j in jump_degs if j > 0.5)
    print(f"\n   經緯度跳躍 > 0.25°: {gt_025deg:,} ({gt_025deg/total_d*100:.1f}%)  ← MAX_JUMP_DEG 拆段閾值")
    print(f"   經緯度跳躍 > 0.5°:  {gt_05deg:,} ({gt_05deg/total_d*100:.1f}%)")

    # 距離 > 15 NM 的案例分析
    print(f"\n   距離 > 15 NM 的案例分析（共 {len(large_jump_cases)} 個）:")
    if large_jump_cases:
        reasonable = sum(1 for c in large_jump_cases if c['speed_kt'] < 25)
        unreasonable = sum(1 for c in large_jump_cases if c['speed_kt'] >= 25)
        very_fast = sum(1 for c in large_jump_cases if c['speed_kt'] >= 40)

        print(f"   隱含速度 < 25 kt（合理）: {reasonable} ({reasonable/len(large_jump_cases)*100:.1f}%)")
        print(f"   隱含速度 >= 25 kt（偏高）: {unreasonable} ({unreasonable/len(large_jump_cases)*100:.1f}%)")
        print(f"   隱含速度 >= 40 kt（異常）: {very_fast} ({very_fast/len(large_jump_cases)*100:.1f}%)")

        print(f"\n   前 20 個案例:")
        for i, case in enumerate(large_jump_cases[:20]):
            print(f"   [{i+1:2d}] MMSI={case['mmsi']} dist={case['dist_nm']:.1f}NM "
                  f"dt={case['dt_sec']:.0f}s({case['dt_sec']/60:.0f}m) "
                  f"speed={case['speed_kt']:.1f}kt deg_jump={case['deg_jump']:.3f}° "
                  f"({case['from'][0]:.3f},{case['from'][1]:.3f}) → ({case['to'][0]:.3f},{case['to'][1]:.3f})")


# ============================================================
# 3.5 交叉分析：哪種過濾條件觸發最多拆段？
# ============================================================
print("\n" + "=" * 80)
print("3.5 拆段原因交叉分析（模擬前端 arrowToTrips 邏輯）")
print("=" * 80)

split_time_only = 0  # 只有時間超過閾值
split_dist_only = 0  # 只有距離超過閾值
split_both = 0       # 兩者都超過
split_none = 0       # 都沒超過（正常連續）
total_transitions = 0

prev_mmsi = None
prev_ts = None
prev_lon = None
prev_lat = None

for mmsi, ts, lon, lat, sog in rows_open:
    if mmsi == prev_mmsi and prev_ts is not None:
        try:
            dt = int(ts) - int(prev_ts)
        except (ValueError, TypeError):
            from datetime import datetime
            t1 = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            t0 = datetime.fromisoformat(prev_ts.replace('Z', '+00:00'))
            dt = (t1 - t0).total_seconds()

        dlon = abs(lon - prev_lon)
        dlat = abs(lat - prev_lat)

        time_trigger = dt > 3600
        dist_trigger = dlon > 0.25 or dlat > 0.25

        total_transitions += 1
        if time_trigger and dist_trigger:
            split_both += 1
        elif time_trigger:
            split_time_only += 1
        elif dist_trigger:
            split_dist_only += 1
        else:
            split_none += 1

    prev_mmsi = mmsi
    prev_ts = ts
    prev_lon = lon
    prev_lat = lat

total_splits = split_time_only + split_dist_only + split_both
print(f"\n   總轉換數: {total_transitions:,}")
print(f"   正常連續（不觸發拆段）: {split_none:,} ({split_none/total_transitions*100:.1f}%)")
print(f"   觸發拆段: {total_splits:,} ({total_splits/total_transitions*100:.1f}%)")
print(f"   ├─ 僅時間 > 1h: {split_time_only:,} ({split_time_only/total_transitions*100:.1f}%)")
print(f"   ├─ 僅距離 > 0.25°: {split_dist_only:,} ({split_dist_only/total_transitions*100:.1f}%)")
print(f"   └─ 時間+距離都超過: {split_both:,} ({split_both/total_transitions*100:.1f}%)")

if total_splits > 0:
    print(f"\n   在所有拆段中:")
    print(f"   ├─ 因時間造成（含重疊）: {split_time_only + split_both:,} ({(split_time_only+split_both)/total_splits*100:.1f}%)")
    print(f"   └─ 因距離造成（含重疊）: {split_dist_only + split_both:,} ({(split_dist_only+split_both)/total_splits*100:.1f}%)")


# ============================================================
# 4. 典型外海長途航行案例
# ============================================================
print("\n" + "=" * 80)
print("4. 典型外海長途航行案例")
print("=" * 80)

# 找在外海有最多紀錄的船
cur.execute("""
    SELECT mmsi, COUNT(*) as cnt, MIN(lon) as min_lon, MAX(lon) as max_lon,
           MIN(lat) as min_lat, MAX(lat) as max_lat
    FROM ship_positions
    WHERE lon BETWEEN 119 AND 121 AND lat BETWEEN 22 AND 24
    GROUP BY mmsi
    HAVING cnt >= 20
    ORDER BY (MAX(lon)-MIN(lon)) + (MAX(lat)-MIN(lat)) DESC
    LIMIT 5
""")
long_voyage_ships = cur.fetchall()

for ship_mmsi, cnt, min_lon, max_lon, min_lat, max_lat in long_voyage_ships:
    print(f"\n   ─── MMSI: {ship_mmsi} ({cnt} 筆) 經度範圍: {min_lon:.3f}-{max_lon:.3f}, 緯度範圍: {min_lat:.3f}-{max_lat:.3f} ───")

    cur.execute("""
        SELECT timestamp, lon, lat, sog
        FROM ship_positions
        WHERE mmsi = ?
        ORDER BY timestamp
    """, (ship_mmsi,))

    ship_rows = cur.fetchall()
    print(f"   {'#':>3s} {'Timestamp':>22s} {'Lon':>9s} {'Lat':>8s} {'SOG':>6s} | {'dt(min)':>8s} {'dist(NM)':>9s} {'deg_jump':>9s} {'spd(kt)':>8s} {'拆段?':>8s}")
    print(f"   {'─'*3} {'─'*22} {'─'*9} {'─'*8} {'─'*6} | {'─'*8} {'─'*9} {'─'*9} {'─'*8} {'─'*8}")

    prev_ts_val = None
    prev_lon_val = None
    prev_lat_val = None

    for idx, (ts, lon, lat, sog) in enumerate(ship_rows):
        dt_str = ""
        dist_str = ""
        deg_str = ""
        spd_str = ""
        flag = ""

        if prev_ts_val is not None:
            try:
                dt = int(ts) - int(prev_ts_val)
            except (ValueError, TypeError):
                from datetime import datetime
                t1 = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                t0 = datetime.fromisoformat(prev_ts_val.replace('Z', '+00:00'))
                dt = (t1 - t0).total_seconds()

            dist = haversine_nm(prev_lon_val, prev_lat_val, lon, lat)
            jdeg = deg_jump(prev_lon_val, prev_lat_val, lon, lat)
            spd = dist / (dt / 3600) if dt > 0 else 0

            dt_str = f"{dt/60:.1f}"
            dist_str = f"{dist:.1f}"
            deg_str = f"{jdeg:.3f}"
            spd_str = f"{spd:.1f}"

            flags = []
            if dt > 3600:
                flags.append("TIME>1h")
            if jdeg > 0.25:
                flags.append("DEG>0.25")
            if spd > 40:
                flags.append("SPD>40kt")
            flag = " ".join(flags)

        # 顯示 timestamp 更可讀的格式
        try:
            ts_display = ts
        except:
            ts_display = str(ts)

        print(f"   {idx+1:>3d} {ts_display:>22s} {lon:>9.4f} {lat:>8.4f} {sog:>6.1f} | {dt_str:>8s} {dist_str:>9s} {deg_str:>9s} {spd_str:>8s} {flag}")

        prev_ts_val = ts
        prev_lon_val = lon
        prev_lat_val = lat

    # 計算此船的拆段數
    num_splits = 0
    prev_ts_val = None
    prev_lon_val = None
    prev_lat_val = None

    for ts, lon, lat, sog in ship_rows:
        if prev_ts_val is not None:
            try:
                dt = int(ts) - int(prev_ts_val)
            except:
                dt = 0
            jdeg = deg_jump(prev_lon_val, prev_lat_val, lon, lat) if prev_lon_val else 0
            if dt > 3600 or jdeg > 0.25:
                num_splits += 1
        prev_ts_val = ts
        prev_lon_val = lon
        prev_lat_val = lat

    total_points = len(ship_rows)
    num_segments = num_splits + 1
    avg_segment_len = total_points / num_segments if num_segments > 0 else total_points
    print(f"   → 拆段數: {num_splits}, 航段數: {num_segments}, 平均每段 {avg_segment_len:.1f} 點")
    min_segment_points = 2
    short_segments = 0
    seg_len = 1
    prev_ts_val = None
    prev_lon_val = None
    prev_lat_val = None

    for ts, lon, lat, sog in ship_rows:
        if prev_ts_val is not None:
            try:
                dt = int(ts) - int(prev_ts_val)
            except:
                dt = 0
            jdeg = deg_jump(prev_lon_val, prev_lat_val, lon, lat) if prev_lon_val else 0
            if dt > 3600 or jdeg > 0.25:
                if seg_len < min_segment_points:
                    short_segments += 1
                seg_len = 1
            else:
                seg_len += 1
        prev_ts_val = ts
        prev_lon_val = lon
        prev_lat_val = lat
    if seg_len < min_segment_points:
        short_segments += 1
    print(f"   → 不足 2 點的短航段（會被丟棄）: {short_segments}")


# ============================================================
# 5. 額外分析：短航段問題
# ============================================================
print("\n" + "=" * 80)
print("5. 短航段分析（拆段後不足 2 點的航段 = 完全消失的軌跡）")
print("=" * 80)

# 對所有外海船舶模擬拆段，統計航段長度分佈
segment_lengths = []
prev_mmsi = None
prev_ts = None
prev_lon = None
prev_lat = None
seg_len = 0
total_points_counted = 0

for mmsi, ts, lon, lat, sog in rows_open:
    should_split = (mmsi != prev_mmsi)

    if not should_split and prev_ts is not None:
        try:
            dt = int(ts) - int(prev_ts)
        except:
            dt = 0
        jdeg = deg_jump(prev_lon, prev_lat, lon, lat) if prev_lon else 0
        if dt > 3600 or jdeg > 0.25:
            should_split = True

    if should_split:
        if seg_len > 0:
            segment_lengths.append(seg_len)
        seg_len = 1
        total_points_counted += 1
    else:
        seg_len += 1
        total_points_counted += 1

    prev_mmsi = mmsi
    prev_ts = ts
    prev_lon = lon
    prev_lat = lat

if seg_len > 0:
    segment_lengths.append(seg_len)

total_segs = len(segment_lengths)
short_segs = sum(1 for s in segment_lengths if s < 2)
medium_segs = sum(1 for s in segment_lengths if 2 <= s <= 5)
long_segs = sum(1 for s in segment_lengths if s > 5)
points_in_short = sum(s for s in segment_lengths if s < 2)

print(f"   總航段數: {total_segs:,}")
print(f"   總點數: {total_points_counted:,}")
print(f"   短航段（< 2 點，被丟棄）: {short_segs:,} ({short_segs/total_segs*100:.1f}%)")
print(f"   短航段中的點數（被丟棄）: {points_in_short:,} ({points_in_short/total_points_counted*100:.1f}%)")
print(f"   中等航段（2-5 點）: {medium_segs:,} ({medium_segs/total_segs*100:.1f}%)")
print(f"   長航段（> 5 點）: {long_segs:,} ({long_segs/total_segs*100:.1f}%)")

segment_lengths.sort()
print(f"\n   航段長度分佈:")
len_buckets = [
    (1, 1, "1 點（丟棄）"),
    (2, 2, "2 點"),
    (3, 5, "3-5 點"),
    (6, 10, "6-10 點"),
    (11, 20, "11-20 點"),
    (21, 50, "21-50 點"),
    (51, 100, "51-100 點"),
    (101, float('inf'), "> 100 點"),
]
for lo, hi, label in len_buckets:
    cnt = sum(1 for s in segment_lengths if lo <= s <= hi)
    pct = cnt / total_segs * 100
    bar = "#" * int(pct / 2)
    print(f"   {label:>15s}: {cnt:>6,} ({pct:>5.1f}%) {bar}")


# ============================================================
# 6. 結論
# ============================================================
print("\n" + "=" * 80)
print("6. 結論")
print("=" * 80)

# 統計最終數據
gt_1h_pct = gt_1h / total_gaps * 100 if total_gaps > 0 else 0
gt_025deg_pct = gt_025deg / total_d * 100 if total_d > 0 else 0
short_seg_pct = short_segs / total_segs * 100 if total_segs > 0 else 0

print(f"""
   [a] 時間間隔 > 1小時（MAX_GAP=3600）:
       外海 {gt_1h_pct:.1f}% 的相鄰紀錄間隔超過 1 小時
       每次觸發都會拆段，大量航跡被切碎

   [b] 距離跳躍 > 0.25°（MAX_JUMP_DEG=0.25）:
       外海 {gt_025deg_pct:.1f}% 的相鄰紀錄距離超過 0.25°
       合理航速下長間隔自然會有大距離，但兩個條件疊加

   [c] 速度 > 40 kt:
       前端目前沒有速度過濾（只有 MAX_GAP 和 MAX_JUMP_DEG）

   [d] 短航段被丟棄:
       拆段後 {short_seg_pct:.1f}% 的航段不足 2 點，被 arrowToTrips 丟棄
       這些孤立點在動畫中完全消失

   總結:
   - 外海 AIS 訊號間隔遠大於近岸（AIS 基地台覆蓋不到）
   - MAX_GAP=3600 和 MAX_JUMP_DEG=0.25 在外海會頻繁觸發拆段
   - 拆段後產生大量只有 1 個點的短航段，被丟棄
   - 這是外海船舶「消失」的主因
""")

conn.close()
