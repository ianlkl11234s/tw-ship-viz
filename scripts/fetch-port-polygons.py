#!/usr/bin/env python3
"""
Download OSM dock/port/harbour polygons for Taiwan ports.
Strategy:
  1. Broad Overpass query to fetch ALL port/dock/harbour polygons in Taiwan
  2. Match each polygon to the nearest port coordinate
  3. For unmatched ports, generate circular fallback polygons

Output: frontend/public/data/port_polygons.geojson
"""

import json
import math
import os
import ssl
import urllib.request
import urllib.parse
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# Match radius (meters) — how far an OSM polygon center can be from a port coordinate
MATCH_RADIUS_M = 2000

# Fallback circle parameters
FALLBACK_CIRCLE_POINTS = 32

# Large ports get bigger fallback radius
LARGE_PORTS = {
    "高雄港", "基隆港", "臺中港", "花蓮港", "台北港", "蘇澳港", "安平港",
}


def load_geojson(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def haversine_m(lat1, lon1, lat2, lon2):
    """Haversine distance in meters."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def polygon_centroid(coords):
    """Approximate centroid of polygon ring."""
    ring = coords[0]
    n = len(ring)
    if n == 0:
        return 0, 0
    lng = sum(p[0] for p in ring) / n
    lat = sum(p[1] for p in ring) / n
    return lng, lat


def polygon_area_deg(coords):
    """Shoelace area in degree^2 (for ranking only)."""
    ring = coords[0]
    n = len(ring)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += ring[i][0] * ring[j][1]
        area -= ring[j][0] * ring[i][1]
    return abs(area) / 2.0


def osm_element_to_polygon(element):
    """Convert OSM way/relation geometry to GeoJSON polygon coordinates."""
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


def make_circle_polygon(lng, lat, radius_m, n_points=32):
    """Create a circular polygon approximation."""
    coords = []
    for i in range(n_points):
        angle = 2 * math.pi * i / n_points
        dlng = radius_m * math.cos(angle) / (111320 * math.cos(math.radians(lat)))
        dlat = radius_m * math.sin(angle) / 110540
        coords.append([lng + dlng, lat + dlat])
    coords.append(coords[0])  # close ring
    return [coords]


def get_fallback_radius(name, port_class):
    """Fallback circle radius based on port importance."""
    if name in LARGE_PORTS:
        return 800
    if port_class == "客運港":
        return 400
    if port_class == "第一類漁港":
        return 300
    return 150


def _query_overpass(query, timeout=300):
    """Try multiple Overpass servers."""
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
            print(f"    [{url.split('/')[2]}] error: {e}")
    return None


def query_overpass_broad():
    """
    Broad query: fetch ALL port/dock/harbour/pier polygons in Taiwan.
    Taiwan bounding box: roughly 21.8-25.4 N, 119.3-122.1 E
    """
    query = """
[out:json][timeout:180];
(
  way["landuse"~"port|harbour"](21.8,119.3,25.5,122.2);
  relation["landuse"~"port|harbour"](21.8,119.3,25.5,122.2);
  way["leisure"="marina"](21.8,119.3,25.5,122.2);
  relation["leisure"="marina"](21.8,119.3,25.5,122.2);
  way["industrial"="port"](21.8,119.3,25.5,122.2);
  relation["industrial"="port"](21.8,119.3,25.5,122.2);
  way["man_made"="pier"](21.8,119.3,25.5,122.2);
  way["man_made"="breakwater"](21.8,119.3,25.5,122.2);
  way["waterway"="dock"](21.8,119.3,25.5,122.2);
  relation["waterway"="dock"](21.8,119.3,25.5,122.2);
  way["amenity"="ferry_terminal"](21.8,119.3,25.5,122.2);
  way["seamark:type"="harbour"](21.8,119.3,25.5,122.2);
  relation["seamark:type"="harbour"](21.8,119.3,25.5,122.2);
);
out geom;
"""
    print("Querying Overpass API for all port/dock polygons in Taiwan...")
    result = _query_overpass(query, timeout=300)
    if result:
        print(f"  Got {len(result.get('elements', []))} OSM elements")
    return result


def query_overpass_individual(lat, lng, radius=1000):
    """Individual query for a single port (fallback if broad missed it)."""
    query = f"""
[out:json][timeout:30];
(
  way["landuse"~"port|harbour"](around:{radius},{lat},{lng});
  relation["landuse"~"port|harbour"](around:{radius},{lat},{lng});
  way["leisure"="marina"](around:{radius},{lat},{lng});
  way["man_made"="pier"](around:{radius},{lat},{lng});
  way["man_made"="breakwater"](around:{radius},{lat},{lng});
  way["waterway"="dock"](around:{radius},{lat},{lng});
  way["industrial"="port"](around:{radius},{lat},{lng});
  way["amenity"="ferry_terminal"](around:{radius},{lat},{lng});
);
out geom;
"""
    return _query_overpass(query, timeout=60)


def main():
    # Load port data
    ports_path = os.path.join(BASE, "frontend/public/data/ports.geojson")
    ports_data = load_geojson(ports_path)
    ports = ports_data["features"]
    print(f"Loaded {len(ports)} ports from ports.geojson")

    # Phase 1: Broad query
    broad_result = query_overpass_broad()
    osm_polygons = []

    if broad_result and broad_result.get("elements"):
        for elem in broad_result["elements"]:
            poly = osm_element_to_polygon(elem)
            if poly:
                clng, clat = polygon_centroid(poly)
                area = polygon_area_deg(poly)
                tags = elem.get("tags", {})
                osm_polygons.append({
                    "polygon": poly,
                    "centroid": (clng, clat),
                    "area": area,
                    "tags": tags,
                    "osm_id": elem.get("id"),
                })

    print(f"Extracted {len(osm_polygons)} valid polygons from broad query")

    # Phase 2: Match each port to nearest OSM polygon
    features = []
    osm_matched = 0
    individual_found = 0
    fallback_count = 0
    used_osm_ids = set()  # avoid reusing same polygon

    # Determine which ports are "major" (will get individual query if broad missed)
    major_port_names = set(LARGE_PORTS)

    for i, port in enumerate(ports):
        props = port["properties"]
        name = props.get("name", "")
        port_class = props.get("port_class", "")
        lng = port["geometry"]["coordinates"][0]
        lat = port["geometry"]["coordinates"][1]

        is_major = (name in LARGE_PORTS or
                    port_class == "客運港" or
                    props.get("tdx_port_class") == "客運港" or
                    port_class == "第一類漁港")

        print(f"[{i+1}/{len(ports)}] {name} ({port_class})...", end=" ", flush=True)

        # Try to find best matching OSM polygon
        best_poly = None
        best_dist = float("inf")
        best_osm_id = None

        for osm in osm_polygons:
            if osm["osm_id"] in used_osm_ids:
                continue
            clng, clat = osm["centroid"]
            dist = haversine_m(lat, lng, clat, clng)
            if dist < MATCH_RADIUS_M and dist < best_dist:
                best_dist = dist
                best_poly = osm["polygon"]
                best_osm_id = osm["osm_id"]

        if best_poly:
            used_osm_ids.add(best_osm_id)
            osm_matched += 1
            print(f"OSM match ({best_dist:.0f}m)")
        elif is_major:
            # Individual query for major ports that were missed
            print("individual query...", end=" ", flush=True)
            result = query_overpass_individual(lat, lng, radius=2000 if name in LARGE_PORTS else 1000)
            time.sleep(1.5)

            if result and result.get("elements"):
                best_area = 0
                for elem in result["elements"]:
                    poly = osm_element_to_polygon(elem)
                    if poly:
                        area = polygon_area_deg(poly)
                        if area > best_area:
                            best_poly = poly
                            best_area = area

            if best_poly:
                individual_found += 1
                print(f"found ({len(best_poly[0])} pts)")
            else:
                radius = get_fallback_radius(name, port_class)
                best_poly = make_circle_polygon(lng, lat, radius)
                fallback_count += 1
                print(f"fallback circle ({radius}m)")
        else:
            radius = get_fallback_radius(name, port_class)
            best_poly = make_circle_polygon(lng, lat, radius)
            fallback_count += 1
            print(f"fallback circle ({radius}m)")

        features.append({
            "type": "Feature",
            "properties": {
                "name": name,
                "port_class": port_class,
                "county": props.get("county", ""),
                "source": props.get("source", ""),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": best_poly,
            },
        })

    output = {
        "type": "FeatureCollection",
        "features": features,
    }

    out_path = os.path.join(BASE, "frontend/public/data/port_polygons.geojson")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone!")
    print(f"  OSM broad match: {osm_matched}")
    print(f"  OSM individual:  {individual_found}")
    print(f"  Fallback circle: {fallback_count}")
    print(f"  Total:           {len(features)}")
    print(f"  Output: {out_path}")


if __name__ == "__main__":
    main()
