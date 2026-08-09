#!/usr/bin/env python3
"""
Re-query major ports with larger radius and prefer the LARGEST polygon.
Updates existing port_polygons.geojson in-place.
"""

import json
import math
import os
import ssl
import time
import urllib.request
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# Major ports that need re-query (name → search radius in meters)
MAJOR_PORTS = {
    "高雄港": 5000,
    "基隆港": 3000,
    "臺中港": 5000,
    "花蓮港": 3000,
    "台北港": 3000,
    "臺北港": 3000,
    "蘇澳港": 3000,
    "布袋港": 2000,
    "金門水頭港": 2000,
    "澎湖港馬公碼頭區": 2000,
    "澎湖港": 2000,
}


def _query_overpass(query, timeout=120):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for url in OVERPASS_URLS:
        data = urllib.parse.urlencode({"data": query}).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"    [{url.split('/')[2]}] {e}")
    return None


def osm_element_to_polygon(element):
    if element["type"] == "way" and "geometry" in element:
        coords = [[p["lon"], p["lat"]] for p in element["geometry"]]
        if len(coords) < 3:
            return None
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return [coords]
    if element["type"] == "relation" and "members" in element:
        for member in element["members"]:
            if member.get("role") == "outer" and "geometry" in member:
                coords = [[p["lon"], p["lat"]] for p in member["geometry"]]
                if len(coords) < 3:
                    continue
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                return [coords]
    return None


def polygon_area_deg(coords):
    ring = coords[0]
    n = len(ring)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += ring[i][0] * ring[j][1]
        area -= ring[j][0] * ring[i][1]
    return abs(area) / 2.0


def query_port_area(lat, lng, radius):
    """Query for port/harbour AREA polygons (not just piers)."""
    query = f"""
[out:json][timeout:60];
(
  way["landuse"~"port|harbour|industrial"](around:{radius},{lat},{lng});
  relation["landuse"~"port|harbour|industrial"](around:{radius},{lat},{lng});
  way["industrial"="port"](around:{radius},{lat},{lng});
  relation["industrial"="port"](around:{radius},{lat},{lng});
  way["seamark:type"="harbour"](around:{radius},{lat},{lng});
  relation["seamark:type"="harbour"](around:{radius},{lat},{lng});
);
out geom;
"""
    return _query_overpass(query)


def main():
    # Load ports.geojson for coordinates
    ports_path = os.path.join(BASE, "frontend/public/data/ports.geojson")
    with open(ports_path) as f:
        ports_data = json.load(f)

    port_coords = {}
    for feat in ports_data["features"]:
        name = feat["properties"]["name"]
        lng, lat = feat["geometry"]["coordinates"]
        port_coords[name] = (lat, lng)

    # Load existing port_polygons.geojson
    for target_dir in [
        os.path.join(BASE, "frontend/public/data"),
        "/Users/migu/Desktop/資料庫/gen_ai_try/ichef_工作用/GIS/plan-art/public",
    ]:
        poly_path = os.path.join(target_dir, "port_polygons.geojson")
        if not os.path.exists(poly_path):
            print(f"  Skip: {poly_path} not found")
            continue

        with open(poly_path) as f:
            poly_data = json.load(f)

        updated = 0
        for feat in poly_data["features"]:
            name = feat["properties"]["name"]
            if name not in MAJOR_PORTS:
                continue

            radius = MAJOR_PORTS[name]
            if name not in port_coords:
                print(f"  {name}: no coordinate found, skip")
                continue

            lat, lng = port_coords[name]
            print(f"  {name} (r={radius}m)...", end=" ", flush=True)

            result = query_port_area(lat, lng, radius)
            time.sleep(2)

            if not result or not result.get("elements"):
                print("no results")
                continue

            # Find the LARGEST polygon
            best_poly = None
            best_area = 0
            best_tags = {}
            for elem in result["elements"]:
                poly = osm_element_to_polygon(elem)
                if poly:
                    area = polygon_area_deg(poly)
                    if area > best_area:
                        best_poly = poly
                        best_area = area
                        best_tags = elem.get("tags", {})

            if best_poly:
                ring = best_poly[0]
                min_lng = min(c[0] for c in ring)
                max_lng = max(c[0] for c in ring)
                min_lat = min(c[1] for c in ring)
                max_lat = max(c[1] for c in ring)
                w_m = (max_lng - min_lng) * 111320 * math.cos(math.radians(lat))
                h_m = (max_lat - min_lat) * 110540
                feat["geometry"]["coordinates"] = best_poly
                updated += 1
                tag_str = best_tags.get("name", best_tags.get("landuse", "?"))
                print(f"OK ({len(ring)}pts, ~{w_m:.0f}m x {h_m:.0f}m, {tag_str})")
            else:
                print("no polygon found")

        with open(poly_path, "w", encoding="utf-8") as f:
            json.dump(poly_data, f, ensure_ascii=False, indent=2)

        print(f"\n  Updated {updated} ports in {poly_path}")


if __name__ == "__main__":
    main()
