"""Rank the ski areas of some countries by their length of downhill runs, to choose which areas get a package.

Pure Python standard library (sqlite3 reads the OpenSkiData GeoPackage directly). Run with `python -I`.

Usage:
    python -I scripts/rank_areas.py DATA/openskidata.gpkg TOP COUNTRY [COUNTRY ...] > ranking.json
    e.g. python -I scripts/rank_areas.py data/openskidata.gpkg 20 FR AT NO

Only operating areas with downhill runs and an OpenStreetMap id (the stable key extract_area.py looks an area up by).
An area across a border belongs to the country where most of its runs are. OpenSkiData has both the big linked areas (Les Trois Vallées) and the resorts inside them (Courchevel, Méribel): an
area is left out when most of its runs already belong to an area ranked above it, so the list is of separate places.
Writes JSON (ASCII-escaped): {"countries": {CC: [{slug, name, country, osm, run_km, lifts, ...}]}, "skipped": [...]}.
"""
import json
import re
import sqlite3
import sys
import unicodedata

SUB_AREA_SHARE = 0.6  # this share of an area's runs inside a bigger, already chosen area makes it a part of that one
MIN_KM = 5
# Lift-pass alliances of separate, unconnected areas: one package would span a whole region, so their members are
# ranked instead. By OpenStreetMap id.
ALLIANCES = {"relation/8896547": "Ski amade"}


def slugify(name):
    """An address-safe name: ASCII (æ, ø, å, ß spelt out), hyphens, at most 40 characters, cut between words."""
    s = name.lower().translate(str.maketrans({"æ": "ae", "ø": "o", "å": "a", "ß": "ss"}))
    s = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()).strip("-")
    if len(s) > 40:
        s = s[:41].rsplit("-", 1)[0]
    return s or "area"


def downhill_km(stats):
    d = (stats.get("runs") or {}).get("byActivity", {}).get("downhill", {}).get("byDifficulty", {})
    return sum(v.get("lengthInKm", 0) for v in d.values())


def lift_count(stats):
    return sum(v.get("count", 0) for v in ((stats.get("lifts") or {}).get("byType") or {}).values())


def ids(value):
    """ski_area_ids as stored: a JSON list or a comma-separated string."""
    if not value:
        return []
    value = value.strip()
    if value.startswith("["):
        return [str(x) for x in json.loads(value)]
    return [x.strip() for x in value.split(",") if x.strip()]


def main():
    gpkg, top, countries = sys.argv[1], int(sys.argv[2]), [c.upper() for c in sys.argv[3:]]
    db = sqlite3.connect(gpkg)
    db.row_factory = sqlite3.Row
    db.text_factory = lambda b: b.decode("utf-8", "replace")
    areas = {}
    for r in db.execute("select feature_id, name, status, sources, country_codes, activities, statistics, websites from ski_areas_point"):
        if r["status"] != "operating" or "downhill" not in (r["activities"] or "").split(","):
            continue
        stats = json.loads(r["statistics"] or "{}")
        osm = next((s["id"] for s in json.loads(r["sources"] or "[]") if s.get("type") == "openstreetmap"), None)
        areas[str(r["feature_id"])] = {
            "feature_id": str(r["feature_id"]), "name": (r["name"] or "").strip(), "osm": osm,
            "countries": [c.strip() for c in re.split(r"[;,]", r["country_codes"] or "") if c.strip()],
            "run_km": round(downhill_km(stats), 1), "lifts": lift_count(stats),
            "website": (json.loads(r["websites"] or "[]") or [None])[0],
        }
    # Which areas each operating downhill run belongs to
    runs_of, where = {}, {}
    for r in db.execute("select uses, status, ski_area_ids, country_codes from runs_linestring"):
        if r["status"] != "operating" or "downhill" not in (r["uses"] or "").split(","):
            continue
        members = ids(r["ski_area_ids"])
        cc = (re.split(r"[;,]", r["country_codes"] or "") or [""])[0].strip()
        for a in members:
            runs_of.setdefault(a, []).append(set(members))
            where.setdefault(a, {}).setdefault(cc, 0)
            where[a][cc] += 1
    for a in areas.values():  # an area across a border belongs to the country with most of its runs
        counts = where.get(a["feature_id"], {})
        a["home"] = max(counts, key=counts.get) if counts else (a["countries"] or [""])[0]
    out, skipped, chosen = {}, [], []
    ranked = sorted(areas.values(), key=lambda a: -a["run_km"])
    for cc in countries:
        out[cc] = []
        for a in ranked:
            if len(out[cc]) >= top:
                break
            if a["home"] != cc or a["run_km"] < MIN_KM:
                continue
            if a["osm"] in ALLIANCES:
                skipped.append({"name": a["name"], "country": cc, "why": "lift-pass alliance of separate areas"})
                continue
            runs = runs_of.get(a["feature_id"], [])
            inside = next((c for c in chosen if runs and sum(c["feature_id"] in m for m in runs) / len(runs) >= SUB_AREA_SHARE), None)
            if inside:
                skipped.append({"name": a["name"], "country": cc, "why": "part of " + inside["name"]})
                continue
            if not a["osm"]:
                skipped.append({"name": a["name"], "country": cc, "why": "no OpenStreetMap id"})
                continue
            entry = {"slug": slugify(a["name"]), "name": a["name"], "country": cc, "osm": a["osm"], "run_km": a["run_km"],
                     "lifts": a["lifts"], "also_in": [c for c in a["countries"] if c != cc], "website": a["website"], "feature_id": a["feature_id"]}
            out[cc].append(entry)
            chosen.append(a)
    json.dump({"countries": out, "skipped": skipped}, sys.stdout, ensure_ascii=True, indent=1)


if __name__ == "__main__":
    main()
