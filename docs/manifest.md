# Package manifest

Every ski area package has a `manifest.json` next to its files. The app reads it before downloading, checks each file
against its SHA-256 after download, and fetches only the files whose checksum changed when a new version appears.

File names carry the build date, so a new build is a new file and caches can keep files for a long time. Only
`manifest.json` and the area index `index.json` are served with `Cache-Control: no-cache`.

```json
{
  "schema": 1,
  "area": "les-3-vallees",
  "name": "Les Trois Vallées",
  "version": "2026-10-21.1",
  "built_at": "2026-10-21T04:00:00Z",
  "data_date": { "osm": "2026-10-20", "openskidata": "2026-10-21", "protomaps": "20261021" },
  "bbox": [6.4847, 45.1942, 6.6863, 45.464],
  "center": [6.58, 45.33],
  "zoom": { "min": 9, "max": 15, "terrain_max": 13 },
  "files": [
    { "kind": "basemap", "path": "les-3-vallees-base-2026-10-21.pmtiles", "bytes": 7340032, "sha256": "…" },
    { "kind": "ski", "path": "les-3-vallees-ski-2026-10-21.pmtiles", "bytes": 330000, "sha256": "…" },
    { "kind": "terrain", "path": "les-3-vallees-terrain-2026-10-21.pmtiles", "bytes": 17091788, "sha256": "…" }
  ],
  "style": "style-1.json",
  "license": "ODbL-1.0 (ski data); see attribution",
  "attribution": [
    { "name": "© OpenStreetMap contributors", "license": "ODbL", "url": "https://www.openstreetmap.org/copyright" },
    { "name": "OpenSkiData / OpenSkiMap.org", "license": "ODbL", "url": "https://openskidata.org" },
    { "name": "Skimap.org", "url": "https://skimap.org" },
    { "name": "Who's On First", "url": "https://whosonfirst.org" },
    { "name": "© Mapterhorn", "url": "https://mapterhorn.com/attribution" }
  ],
  "min_app_version": "0.1.0"
}
```

| Field | Meaning |
|---|---|
| `schema` | Manifest format version. A client that does not know the number keeps its current package |
| `version` | Build date plus a counter for rebuilds on the same day |
| `data_date` | Age of each source, shown in the app ("map data from 20 Oct 2026") |
| `bbox`, `center`, `zoom` | Where the package is valid; the map does not pan or zoom outside it offline |
| `files[].sha256` | Integrity against broken downloads. It is not a signature: it does not protect against someone who can write to the host |
| `attribution` | Shown on the map, also offline |
| `min_app_version` | Oldest app that can read the package |

## The area index

`index.json` lists every published area: `slug`, `name`, `country`, `bbox`, `run_km`, `lifts`, `version`, `bytes`,
`data_date` – and, when the area has one, its lift-status source from `areas.json`: `"status": {"source": "fnugg",
"id": 2}`. Only a source PEAK knows and a number; PEAK builds the source's URL itself and never takes one from here.

**Publishing rule:** a build that loses more than 10 % of an area's runs or lifts compared with the previous version
is not published. OpenSkiData's format is not stable, so the schema is checked on every import.
