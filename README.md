# PEAK_maps

Scripts and method behind the offline ski maps in **PEAK Ski** (the ski product of the PEAK app, joinpeak.eu).

PEAK builds one offline package per ski area from open data and lets the app download it. The ski layer in those
packages is derived from OpenStreetMap, so it is a *Derivative Database* under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/). This repository is how PEAK meets
section 4.6 of the ODbL: it publishes the method that produces the derived data, free of charge.

> **Status (23 October 2026):** packages are built end to end for 60 ski areas – the 20 largest in France, Austria and
> Norway (see [Areas](#areas)). Publishing them to PEAK's server is not automated yet. The ski layer is GeoJSON for
> now; vector tiles (`<area>-ski-<date>.pmtiles`) come later without a change to the manifest's format.

## What a package contains

| File | Source | Licence |
|---|---|---|
| `<area>-base-<date>.pmtiles` | [Protomaps basemap](https://docs.protomaps.com/basemaps/downloads), cut to the area, zoom 0–15 | ODbL (produced work of OSM) |
| `<area>-ski-<date>.pmtiles` | Runs, lifts and lift stations from [OpenSkiData](https://openskidata.org), zoom 8–15 | **ODbL** (derivative database of OSM) |
| `<area>-terrain-<date>.pmtiles` | [Mapterhorn](https://mapterhorn.com) terrain, cut to the area, zoom 0–13 | Per source, see [attribution](https://download.mapterhorn.com/attribution.json) |
| `manifest.json` | Generated | – see [docs/manifest.md](docs/manifest.md) |

## Method

1. Download the OpenSkiData GeoPackage (`https://tiles.openskimap.org/openskidata.gpkg`), **at most once a day** as
   OpenSkiData asks.
2. `scripts/extract_area.py`: find the ski area by its **OpenStreetMap id** in [areas.json](areas.json). OpenSkiData
   feature ids change with every build, OSM ids do not. Then:
   - keep operating downhill runs (lines and areas), operating lifts and lift stations that belong to the area;
   - keep only the fields the map needs: name, ref, difficulty, grooming, lift type, occupancy, capacity, duration,
     the French lift register number (`ref_fr_cairn`) and the OSM id;
   - compute the bounding box from the runs and lifts plus a 1.5 km margin;
   - write `overlay.geojson` and a data-quality report `area.json`.
3. `scripts/measure_package.py`: read only the headers and directories of the Protomaps build and of Mapterhorn's
   archives with HTTP Range requests, and sum the tile sizes inside the bounding box. No tiles are downloaded.
4. `scripts/build_packages.py`: for each area, run step 2, cut the basemap of the newest daily Protomaps build (zoom
   0–15) and Mapterhorn's terrain (the planet file to zoom 12, and each regional zoom-13 file the area touches) with
   `pmtiles extract --bbox --maxzoom`, then `scripts/write_manifest.py`: dated file names, SHA-256 checksums,
   `manifest.json` and the area's entry in the packages' `index.json`.

Choosing areas: `scripts/rank_areas.py` ranks the operating ski areas of some countries by their length of downhill
runs. It leaves out an area when most of its runs belong to a bigger area ranked above it (Courchevel inside Les Trois
Vallées), leaves out lift-pass alliances of separate areas (Ski amadé – its members are ranked instead), and puts an
area across a border in the country where most of its runs are.

Everything runs on the Python standard library, plus the [pmtiles CLI](https://github.com/protomaps/go-pmtiles) for
cutting archives. No package needs installing.

```bash
python -I scripts/rank_areas.py data/openskidata.gpkg 20 FR AT NO > out/ranking.json
python -I scripts/build_packages.py data/openskidata.gpkg areas.json out ../packages pmtiles hemsedal trysil
python -I scripts/measure_package.py out/les-3-vallees/area.json 20261021 13
```

`data/` and `out/` are ignored by git: the input is 410 MB, and the output is published as packages, not here.

## Pilot results (OpenSkiData and OSM as of 20–21 October 2026)

| Area | Runs | Run length | Runs with a name | Lifts | Lifts with both stations mapped | Package size |
|---|---|---|---|---|---|---|
| Les Trois Vallées | 872 | 539 km | 56 % | 169 | 27 % | 23.6 MB |
| Ski Arlberg | 513 | 272 km | 88 % | 92 | 95 % | 19.7 MB |
| Sölden | 161 | 102 km | 99 % | 39 | 74 % | 8.0 MB |
| Hemsedal | 94 | 48 km | 63 % | 22 | 32 % | 5.5 MB |

The package size is measured with terrain to zoom 13. Mapterhorn tiles are 512 px, so zoom 13 carries the detail of
zoom 14 at 256 px, and the map overzooms from there. Terrain is about two thirds of every package. Les Trois Vallées
covers 539 of the 600 km the resort publishes, about 90 %. Red and black runs are the least complete, at about 75 %.

Where stations are missing, the app uses the first and last point of the lift line, since OSM draws aerialways
bottom to top.

## Areas

`areas.json` lists the areas PEAK builds packages for, by OpenStreetMap id. They are added in waves:

1. **France, Austria and Norway** – the 20 largest in each (23 October 2026).
2. Italy, Germany and Sweden.
3. The smaller countries of Europe (Switzerland, Andorra, Spain, Slovenia, Finland and others).
4. The United States.

## Licences

- **Scripts** in this repository: [MIT](LICENSE).
- **Derived ski data** (the overlay and the ski layer in the packages): ODbL 1.0, like its source.
- **Attribution** shown on the map and in the app:
  "© OpenStreetMap contributors · OpenSkiData / OpenSkiMap.org · Skimap.org · Who's On First · © Mapterhorn",
  plus the terrain sources an area uses.

What we do **not** use: tiles from `tile.openstreetmap.org` (offline use is not permitted), the vector tiles at
`tiles.openskimap.org` (direct use is not permitted), the openskidata-processor code (it has no licence), and official
resort piste maps (copyrighted).

## Questions and corrections

Errors in runs or lifts are best fixed in [OpenStreetMap](https://www.openstreetmap.org) itself. They reach the next
package after OpenSkiData's daily build. Issues about the method are welcome here.
