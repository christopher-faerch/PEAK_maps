"""Extract one ski area from the OpenSkiData GeoPackage into a compact GeoJSON overlay plus a data-quality report.

Pure Python standard library (sqlite3 reads the GeoPackage directly). Run with `python -I`.

Usage:
    python -I scripts/extract_area.py DATA/openskidata.gpkg areas.json SLUG OUT_DIR

Writes OUT_DIR/SLUG/overlay.geojson (runs, lifts, lift stations) and OUT_DIR/SLUG/area.json (bbox and statistics).
The overlay is a Derivative Database of OpenStreetMap: it is licensed under the ODbL like its source.
"""
import collections
import gzip
import json
import math
import os
import sqlite3
import struct
import sys

BBOX_MARGIN_KM = 1.5  # room around the outermost run or lift, so the basemap and terrain don't stop at the piste edge


def read_wkb(b, p):
    """Minimal WKB reader for the geometry types OpenSkiData uses (point, line, polygon, multi*), Z dropped."""
    e = "<" if b[p] == 1 else ">"
    t = struct.unpack_from(e + "I", b, p + 1)[0]
    p += 5
    has_z = bool(t & 0x80000000) or (t % 10000) // 1000 in (1, 3)
    base = (t & 0xFFFF) % 1000
    dims = 3 if has_z else 2

    def points(p):
        n = struct.unpack_from(e + "I", b, p)[0]
        p += 4
        out = []
        for _ in range(n):
            c = struct.unpack_from(e + "d" * dims, b, p)
            out.append([round(c[0], 6), round(c[1], 6)])
            p += 8 * dims
        return out, p

    if base == 1:
        c = struct.unpack_from(e + "d" * dims, b, p)
        return {"type": "Point", "coordinates": [round(c[0], 6), round(c[1], 6)]}, p + 8 * dims
    if base == 2:
        c, p = points(p)
        return {"type": "LineString", "coordinates": c}, p
    if base == 3:
        n = struct.unpack_from(e + "I", b, p)[0]
        p += 4
        rings = []
        for _ in range(n):
            r, p = points(p)
            rings.append(r)
        return {"type": "Polygon", "coordinates": rings}, p
    if base in (5, 6):
        n = struct.unpack_from(e + "I", b, p)[0]
        p += 4
        parts = []
        for _ in range(n):
            g, p = read_wkb(b, p)
            parts.append(g["coordinates"])
        return {"type": "MultiLineString" if base == 5 else "MultiPolygon", "coordinates": parts}, p
    raise ValueError(f"unsupported WKB type {t}")


def gpkg_geometry(blob):
    """GeoPackage geometry = 'GP' header (+ optional envelope) + WKB."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry")
    envelope = (blob[3] >> 1) & 7
    return read_wkb(blob, 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope])[0]


def all_points(g):
    c = g["coordinates"]
    depth = {"Point": 0, "LineString": 1, "Polygon": 2, "MultiLineString": 2, "MultiPolygon": 3}[g["type"]]
    pts = [c]
    for _ in range(depth):
        pts = [q for p in pts for q in p]
    return pts


def length_km(g):
    def line(c):
        s = 0.0
        for (x1, y1), (x2, y2) in zip(c, c[1:]):
            dx = math.radians(x2 - x1) * math.cos(math.radians((y1 + y2) / 2))
            s += 6371.0 * math.hypot(dx, math.radians(y2 - y1))
        return s
    if g["type"] == "LineString":
        return line(g["coordinates"])
    if g["type"] == "MultiLineString":
        return sum(line(c) for c in g["coordinates"])
    return 0.0


def first_osm_id(sources):
    for s in json.loads(sources or "[]"):
        if s.get("type") == "openstreetmap":
            return s["id"]
    return None


def main():
    gpkg, areas_file, slug, out_root = sys.argv[1:5]
    area_cfg = next(a for a in json.load(open(areas_file, encoding="utf-8"))["areas"] if a["slug"] == slug)
    db = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row

    # The OpenSkiData feature id changes every build: look the area up by its stable OSM id.
    area = db.execute("select * from ski_areas_point where sources like ?", (f'%"{area_cfg["osm"]}"%',)).fetchone()
    if not area:
        sys.exit(f"{slug}: no ski area with source {area_cfg['osm']} in this build")
    aid = area["feature_id"]
    like = f"%{aid}%"  # ski_area_ids is a comma-separated list

    def rows(table):
        return [dict(r) for r in db.execute(f'select * from "{table}" where ski_area_ids like ?', (like,))]

    runs = [r for r in rows("runs_linestring") if "downhill" in (r["uses"] or "").split(",") and r["status"] == "operating"]
    run_areas = [r for r in rows("runs_multipolygon") if "downhill" in (r["uses"] or "").split(",") and r["status"] == "operating"]
    lifts = [r for r in rows("lifts_linestring") if r["status"] == "operating"]
    stations = [r for r in rows("spots_point") if r["spot_type"] == "lift_station"]

    feats = []
    for r in runs:
        g = gpkg_geometry(r["geometry"])
        r["_km"] = length_km(g)
        feats.append({"type": "Feature", "geometry": g, "properties": {
            "kind": "run", "name": r["name"], "ref": r["ref"], "difficulty": r["difficulty"],
            "grooming": r["grooming"], "osm": first_osm_id(r["sources"])}})
    for r in run_areas:
        feats.append({"type": "Feature", "geometry": gpkg_geometry(r["geometry"]), "properties": {
            "kind": "run_area", "name": r["name"], "difficulty": r["difficulty"], "osm": first_osm_id(r["sources"])}})
    for r in lifts:
        feats.append({"type": "Feature", "geometry": gpkg_geometry(r["geometry"]), "properties": {
            "kind": "lift", "name": r["name"], "ref": r["ref"], "ref_fr_cairn": r["ref_fr_cairn"], "lift_type": r["lift_type"],
            "occupancy": r["occupancy"], "capacity": r["capacity"], "duration": r["duration"], "osm": first_osm_id(r["sources"])}})
    for r in stations:
        feats.append({"type": "Feature", "geometry": gpkg_geometry(r["geometry"]), "properties": {
            "kind": "station", "position": r["position"], "name": r["name"], "osm": first_osm_id(r["sources"])}})

    pts = [p for f in feats if f["properties"]["kind"] in ("run", "lift") for p in all_points(f["geometry"])]
    if not pts:
        sys.exit(f"{slug}: no runs or lifts")
    lat0 = sum(p[1] for p in pts) / len(pts)
    dlat = BBOX_MARGIN_KM / 111.0
    dlon = BBOX_MARGIN_KM / (111.0 * math.cos(math.radians(lat0)))
    bbox = [round(min(p[0] for p in pts) - dlon, 4), round(min(p[1] for p in pts) - dlat, 4),
            round(max(p[0] for p in pts) + dlon, 4), round(max(p[1] for p in pts) + dlat, 4)]

    # Lift ends as stations: OSM draws aerialways bottom to top, and mapped station nodes are often missing.
    def near(a, b, m=60):
        dx = math.radians(b[0] - a[0]) * math.cos(math.radians(a[1]))
        return 6371000 * math.hypot(dx, math.radians(b[1] - a[1])) <= m
    st_pts = [gpkg_geometry(s["geometry"])["coordinates"] for s in stations]
    both_mapped = 0
    for r in lifts:
        g = gpkg_geometry(r["geometry"])
        if g["type"] == "LineString":
            c = g["coordinates"]
            if any(near(c[0], s) for s in st_pts) and any(near(c[-1], s) for s in st_pts):
                both_mapped += 1

    named = [r for r in runs if r["name"]]
    report = {
        "slug": slug, "name": area_cfg["name"], "osm": area_cfg["osm"], "openskidata_name": area["name"],
        "bbox": bbox, "elevation": [area["min_elevation"], area["max_elevation"]],
        "runs": {
            "count": len(runs), "length_km": round(sum(r["_km"] for r in runs)), "areas": len(run_areas),
            "named": len(named), "with_ref": sum(1 for r in runs if r["ref"]),
            "difficulty": dict(collections.Counter(r["difficulty"] or "none" for r in runs)),
            "names_on_several_segments": sum(1 for n, k in collections.Counter(r["name"] for r in named).items() if k > 1),
            "under_3_points": sum(1 for f in feats if f["properties"]["kind"] == "run" and f["geometry"]["type"] == "LineString" and len(f["geometry"]["coordinates"]) < 3),
        },
        "lifts": {
            "count": len(lifts), "named": sum(1 for r in lifts if r["name"]),
            "type": dict(collections.Counter(r["lift_type"] for r in lifts)),
            "with_occupancy": sum(1 for r in lifts if r["occupancy"]), "with_ref_fr_cairn": sum(1 for r in lifts if r["ref_fr_cairn"]),
            "both_stations_mapped": both_mapped,
        },
        "stations": dict(collections.Counter(r["position"] for r in stations)),
    }
    out = os.path.join(out_root, slug)
    os.makedirs(out, exist_ok=True)
    data = json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"), ensure_ascii=False).encode()
    with open(os.path.join(out, "overlay.geojson"), "wb") as f:
        f.write(data)
    report["overlay_bytes"] = {"raw": len(data), "gzip": len(gzip.compress(data, 9))}
    with open(os.path.join(out, "area.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
