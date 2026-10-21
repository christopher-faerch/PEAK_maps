"""Measure how big an offline package for one ski area will be, without downloading any tiles.

Reads only PMTiles headers and directories with HTTP Range requests and sums the tile sizes inside the area's bbox:
the Protomaps basemap (z0-15) and Mapterhorn terrain (planet z0-12, regional files z13+). Pure standard library.

Usage:
    python -I scripts/measure_package.py OUT_DIR/SLUG/area.json PROTOMAPS_BUILD [TERRAIN_MAX_ZOOM]
    e.g. PROTOMAPS_BUILD = 20261021  (see https://build-metadata.protomaps.dev/builds.json)
"""
import gzip
import json
import math
import struct
import sys
import urllib.request

UA = "PEAK_maps/0.1 (+https://github.com/christopher-faerch/PEAK_maps)"
MAPTERHORN_INDEX = "https://download.mapterhorn.com/download_urls.json"


def get(url, rng=None):
    headers = {"User-Agent": UA}
    if rng:
        headers["Range"] = f"bytes={rng[0]}-{rng[0] + rng[1] - 1}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        if rng and r.status != 206:
            raise RuntimeError(f"{url}: expected 206 Partial Content, got {r.status}")
        return r.read()


def varint(buf, pos):
    shift = result = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, pos
        shift += 7


def parse_dir(buf):
    n, p = varint(buf, 0)
    cols = [[], [], [], []]
    last = 0
    for _ in range(n):
        d, p = varint(buf, p)
        last += d
        cols[0].append(last)
    for k in (1, 2):
        for _ in range(n):
            v, p = varint(buf, p)
            cols[k].append(v)
    for i in range(n):
        v, p = varint(buf, p)
        cols[3].append(cols[3][i - 1] + cols[2][i - 1] if v == 0 and i > 0 else v - 1)
    return list(zip(*cols))  # (tile_id, run_length, length, offset)


def hilbert(n, x, y):
    d, s = 0, n // 2
    while s > 0:
        rx, ry = int(x & s > 0), int(y & s > 0)
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        s //= 2
    return d


def tile_id(z, x, y):
    return sum(4 ** i for i in range(z)) + hilbert(1 << z, x, y)


def xy(lon, lat, z):
    n = 1 << z
    r = math.radians(lat)
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


class Archive:
    def __init__(self, url):
        self.url = url
        h = get(url, (0, 16384))
        if h[:7] != b"PMTiles" or h[7] != 3:
            raise RuntimeError(f"{url}: not PMTiles v3")
        (root_off, root_len, _mo, _ml, self.leaf_off, _ll, _do, _dl, *_rest) = struct.unpack_from("<11Q", h, 8)
        self.icomp = h[97]
        self.root = parse_dir(self._dec(h[root_off:root_off + root_len]))
        self.leaves = {}

    def _dec(self, b):
        return gzip.decompress(b) if self.icomp == 2 else b

    def find(self, tid):
        d = self.root
        for _ in range(4):
            lo, hi, hit = 0, len(d) - 1, None
            while lo <= hi:
                m = (lo + hi) // 2
                if d[m][0] <= tid:
                    hit, lo = m, m + 1
                else:
                    hi = m - 1
            if hit is None:
                return None
            ident, run, length, off = d[hit]
            if run == 0:
                if off not in self.leaves:
                    self.leaves[off] = parse_dir(self._dec(get(self.url, (self.leaf_off + off, length))))
                d = self.leaves[off]
                continue
            return (off, length) if tid < ident + run else None
        return None

    def measure(self, bbox, zmin, zmax):
        w, s, e, n = bbox
        seen, total, count = set(), 0, 0
        for z in range(zmin, zmax + 1):
            x0, y0 = xy(w, n, z)
            x1, y1 = xy(e, s, z)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    hit = self.find(tile_id(z, x, y))
                    if hit:
                        count += 1
                        if hit not in seen:
                            seen.add(hit)
                            total += hit[1]
        return {"tiles": count, "bytes": total}


def intersect(a, b):
    w, s, e, n = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return [w, s, e, n] if w < e and s < n else None


def main():
    area = json.load(open(sys.argv[1], encoding="utf-8"))
    build = sys.argv[2]
    tmax = int(sys.argv[3]) if len(sys.argv) > 3 else 13
    bbox = area["bbox"]
    result = {"slug": area["slug"], "bbox": bbox, "protomaps_build": build, "terrain_max_zoom": tmax}
    result["basemap"] = Archive(f"https://build.protomaps.com/{build}.pmtiles").measure(bbox, 0, 15)
    index = json.loads(get(MAPTERHORN_INDEX))["items"]
    planet = next(i for i in index if i["name"] == "planet.pmtiles")
    terrain = Archive(planet["url"]).measure(bbox, 0, min(12, tmax))
    if tmax >= 13:
        for item in index:
            if item["name"] == "planet.pmtiles" or item["min_zoom"] > tmax:
                continue
            part = intersect(bbox, [item["min_lon"], item["min_lat"], item["max_lon"], item["max_lat"]])
            if part:
                m = Archive(item["url"]).measure(part, max(13, item["min_zoom"]), tmax)
                terrain["tiles"] += m["tiles"]
                terrain["bytes"] += m["bytes"]
    result["terrain"] = terrain
    overlay = area.get("overlay_bytes", {}).get("gzip", 0)
    result["ski_overlay_gzip_bytes"] = overlay
    result["total_mb"] = round((result["basemap"]["bytes"] + terrain["bytes"] + overlay) / 1048576, 1)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
