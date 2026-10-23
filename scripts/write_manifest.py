"""Turn one built area into a publishable package: dated file names, SHA-256 checksums, manifest.json, and the area's
entry in the packages' index.json. Pure standard library.

Usage:
    python -I scripts/write_manifest.py OUT_DIR/SLUG/area.json PACKAGES_DIR BUILD_DATE PROTOMAPS_BUILD [AREAS_JSON] [--local]
      OUT_DIR/SLUG/ holds what the other steps made: overlay.geojson, base.pmtiles, terrain-low.pmtiles (zoom 0-12)
      and terrain-z13*.pmtiles (zoom 13 – one per Mapterhorn region the area touches); PACKAGES_DIR/SLUG/ receives the package, PACKAGES_DIR/index.json the entry.
      The resort's own piste map (areas.json 'official_map') is always linked. Its image (OUT_DIR/SLUG/official.webp,
      rendered from the resort's PDF) goes into the package only when 'image_permission' is true – the resort's written
      permission – or with --local, for a package that never leaves the developer's machine.
Manifest format: docs/manifest.md.
"""
import datetime
import glob
import hashlib
import json
import os
import shutil
import sys

ATTRIBUTION = [
    {"name": "© OpenStreetMap contributors", "license": "ODbL", "url": "https://www.openstreetmap.org/copyright"},
    {"name": "OpenSkiData", "license": "ODbL", "url": "https://openskidata.org"},
    {"name": "Protomaps", "url": "https://protomaps.com"},
    {"name": "© Mapterhorn", "url": "https://mapterhorn.com/attribution"},
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def webp_size(path):
    """Width and height of a WebP (VP8 lossy, VP8L or VP8X)."""
    b = open(path, "rb").read(40)
    kind = b[12:16]
    if kind == b"VP8X":
        return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
    if kind == b"VP8L":
        v = int.from_bytes(b[21:25], "little")
        return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
    return int.from_bytes(b[26:28], "little") & 0x3FFF, int.from_bytes(b[28:30], "little") & 0x3FFF


def main():
    args = [a for a in sys.argv[1:] if a != "--local"]
    local = "--local" in sys.argv
    area_file, packages, date, build = args[0:4]
    area = json.load(open(area_file, encoding="utf-8"))
    cfg = {}
    if len(args) > 4:
        cfg = next((x for x in json.load(open(args[4], encoding="utf-8"))["areas"] if x["slug"] == area["slug"]), {})
    src = os.path.dirname(area_file)
    slug = area["slug"]
    dest = os.path.join(packages, slug)
    os.makedirs(dest, exist_ok=True)
    parts = [
        ("basemap", "base.pmtiles", f"{slug}-base-{date}.pmtiles", {}),
        ("terrain", "terrain-low.pmtiles", f"{slug}-terrain-low-{date}.pmtiles", {"layer_maxzoom": 13, "encoding": "terrarium", "tile_size": 512}),
    ] + [
        ("terrain", os.path.basename(p), f"{slug}-{os.path.basename(p)[:-8]}-{date}.pmtiles", {"layer_minzoom": 13, "encoding": "terrarium", "tile_size": 512})
        for p in sorted(glob.glob(os.path.join(src, "terrain-z13*.pmtiles")))
    ] + [
        ("ski", "overlay.geojson", f"{slug}-ski-{date}.geojson", {}),
    ]
    files = []
    for kind, name, target, extra in parts:
        path = os.path.join(src, name)
        if not os.path.exists(path):
            continue
        shutil.copyfile(path, os.path.join(dest, target))
        files.append({"kind": kind, "path": target, "bytes": os.path.getsize(path), "sha256": sha256(path), **extra})
    w, s, e, n = area["bbox"]
    manifest = {
        "schema": 1, "area": slug, "name": area["name"], "version": f"{date}.1",
        "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_date": {"openskidata": date, "protomaps": build}, "bbox": area["bbox"],
        "center": [round((w + e) / 2, 4), round((s + n) / 2, 4)], "zoom": {"min": 9, "max": 16, "terrain_max": 13},
        "files": files, "glyphs": "/maps/glyphs/{fontstack}/{range}.pbf",
        "license": "ODbL-1.0 (ski data); see attribution", "attribution": ATTRIBUTION, "min_app_version": "0.1.0",
    }
    official = cfg.get("official_map")
    if official:
        manifest["official_map"] = {k: official[k] for k in ("credit", "page_url", "pdf_url") if official.get(k)}
        image = os.path.join(src, "official.webp")
        if os.path.exists(image) and (official.get("image_permission") or local):
            target = f"{slug}-official-{date}.webp"
            shutil.copyfile(image, os.path.join(dest, target))
            w, h = official.get("image_size", [0, 0]) if official.get("image_size") else webp_size(image)
            manifest["official_map"]["image"] = {"path": target, "width": w, "height": h, "bytes": os.path.getsize(image), "sha256": sha256(image)}
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    index_path = os.path.join(packages, "index.json")
    index = json.load(open(index_path, encoding="utf-8")) if os.path.exists(index_path) else {"schema": 1, "areas": []}
    index["areas"] = [a for a in index["areas"] if a.get("slug") != slug] + [{
        "slug": slug, "name": area["name"], "country": area.get("country", ""), "bbox": area["bbox"],
        "run_km": area["runs"]["length_km"], "lifts": area["lifts"]["count"], "version": manifest["version"],
        "bytes": sum(f["bytes"] for f in files), "data_date": date,
    }]
    index["areas"].sort(key=lambda a: a["name"])
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(json.dumps({"slug": slug, "files": len(files), "bytes": sum(f["bytes"] for f in files)}))


if __name__ == "__main__":
    main()
