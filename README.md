# PEAK_maps

Scripts and method behind the offline ski maps in **PEAK Ski** (the ski product of the PEAK app, joinpeak.eu).

PEAK builds one offline package per ski area from open data and lets the app download it. The ski layer in those
packages is derived from OpenStreetMap, so it is a *Derivative Database* under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/). This repository is how PEAK meets
section 4.6 of the ODbL: it publishes the method that produces the derived data, free of charge.

> **Status (21 October 2026):** pilot. The extraction and measurement scripts work for the four pilot areas below.
> Building the vector tiles and publishing packages is not implemented yet.

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
4. *(Not implemented yet)* Build `overlay.geojson` into vector tiles, cut the basemap and terrain with
   `pmtiles extract --bbox --maxzoom`, write the manifest with SHA-256 checksums and publish.

Everything runs on the Python standard library. No package needs installing.

```bash
python -I scripts/extract_area.py data/openskidata.gpkg areas.json les-3-vallees out
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
