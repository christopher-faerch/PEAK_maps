"""Build the offline packages for some ski areas, end to end: extract the ski data, cut the basemap and the terrain,
write the manifest and the index entry. Pure Python standard library; the cutting is done by the pmtiles CLI
(https://github.com/protomaps/go-pmtiles), which reads only the needed parts of the archives with Range requests.

Usage:
    python -I scripts/build_packages.py DATA/openskidata.gpkg areas.json OUT_DIR PACKAGES_DIR PMTILES SLUG [SLUG ...]
    e.g. python -I scripts/build_packages.py data/openskidata.gpkg areas.json out ../packages pmtiles hemsedal trysil

For each area: scripts/extract_area.py → OUT_DIR/SLUG/overlay.geojson and area.json; the Protomaps basemap of the
newest daily build (zoom 0-15) → base.pmtiles; Mapterhorn's planet terrain (zoom 0-12) → terrain-low.pmtiles and its
regional zoom-13 files the area touches → terrain-z13*.pmtiles; then scripts/write_manifest.py. An area that fails is
reported and the next one is built. Prints a JSON summary. The OpenSkiData GeoPackage is downloaded at most once a
day, by hand, as OpenSkiData asks.
"""
import datetime
import json
import os
import subprocess
import sys
import urllib.request

UA = "PEAK_maps/0.1 (+https://github.com/christopher-faerch/PEAK_maps)"
BUILDS = "https://build-metadata.protomaps.dev/builds.json"
MAPTERHORN_INDEX = "https://download.mapterhorn.com/download_urls.json"
HERE = os.path.dirname(os.path.abspath(__file__))


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
        return json.load(r)


def intersect(a, b):
    w, s, e, n = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return [w, s, e, n] if w < e and s < n else None


def extract(pmtiles, url, out, bbox, maxzoom):
    """pmtiles extract with a bounding box; returns the file's size (0 when nothing was in the box)."""
    box = ",".join(f"{v:.5f}" for v in bbox)
    subprocess.run([pmtiles, "extract", url, out, f"--bbox={box}", f"--maxzoom={maxzoom}"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return os.path.getsize(out) if os.path.exists(out) else 0


def main():
    gpkg, areas_file, out_root, packages, pmtiles = sys.argv[1:6]
    slugs = sys.argv[6:]
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    build = get_json(BUILDS)[-1]["key"].removesuffix(".pmtiles")  # the newest daily Protomaps build
    terrain = get_json(MAPTERHORN_INDEX)["items"]
    planet = next(i for i in terrain if i["name"] == "planet.pmtiles")
    regions = [i for i in terrain if i["name"] != "planet.pmtiles" and i["min_zoom"] <= 13 <= i["max_zoom"]]
    summary = {"date": date, "protomaps": build, "built": [], "failed": []}
    for slug in slugs:
        src = os.path.join(out_root, slug)
        try:
            subprocess.run([sys.executable, "-I", os.path.join(HERE, "extract_area.py"), gpkg, areas_file, slug, out_root],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            area = json.load(open(os.path.join(src, "area.json"), encoding="utf-8"))
            bbox = area["bbox"]
            for old in os.listdir(src):  # a rebuild starts from fresh cuts
                if old.endswith(".pmtiles"):
                    os.remove(os.path.join(src, old))
            extract(pmtiles, f"https://build.protomaps.com/{build}.pmtiles", os.path.join(src, "base.pmtiles"), bbox, 15)
            extract(pmtiles, planet["url"], os.path.join(src, "terrain-low.pmtiles"), bbox, 12)
            for region in regions:
                part = intersect(bbox, [region["min_lon"], region["min_lat"], region["max_lon"], region["max_lat"]])
                if part:
                    out = os.path.join(src, "terrain-z13-" + region["name"].removesuffix(".pmtiles") + ".pmtiles")
                    if extract(pmtiles, region["url"], out, part, 13) < 1024:  # an empty cut (sea, no data) is left out
                        os.remove(out)
            done = subprocess.run([sys.executable, "-I", os.path.join(HERE, "write_manifest.py"), os.path.join(src, "area.json"),
                                   packages, date, build, areas_file], check=True, capture_output=True, text=True)
            summary["built"].append(json.loads(done.stdout.strip().splitlines()[-1]))
        except (subprocess.CalledProcessError, OSError, KeyError, ValueError) as ex:
            detail = getattr(ex, "stderr", "") or ""
            summary["failed"].append({"slug": slug, "error": (str(ex) + " " + (detail if isinstance(detail, str) else detail.decode("utf-8", "replace")))[-400:]})
        print(json.dumps({"slug": slug, "ok": not summary["failed"] or summary["failed"][-1]["slug"] != slug}), flush=True)
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
