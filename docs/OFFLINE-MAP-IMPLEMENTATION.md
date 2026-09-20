# Offline map implementation and acceptance record

## Agreed scope

- Worldwide offline country/city/ocean names, borders, waterways, and major transportation reference layers.
- United States receives priority for finer administrative boundaries, named roads, parks, railways, and available points of interest. Do not substitute one city for nationwide coverage.
- Preserve the existing detailed online imagery and map controls. Offline imagery coverage must be identified separately; online tiles are not an installed offline package.
- Ten GB is an initial planning budget, not a hard ceiling. Report actual package sizes and estimates before large downloads; avoid unbounded tile harvesting.
- Outside the United States, street-level expansion is deferred.
- Show installed data immediately; refresh stale enabled observations while the app is open and connected. Explicit offline mode must prevent external requests.

## Verified starting point

- Working checkout: embedded OBEOS EarthGlass, branch agent/earth-integration. Inspect status each run before editing; the separate Codex project checkout is older.
- BasemapController uses bundled Cesium NaturalEarthII for offline overview, Esri World Imagery for online satellite mode, and OpenStreetMap tiles for online streets.
- FIRMS, CelesTrak, and NASA GIBS integration code already exists. Reuse it and verify actual offline persistence rather than duplicating providers.
- User-supplied Downloads include Natural_Earth_quick_start, 10m_physical, 10m_cultural, NE1_HR_LC_SR_W_DR, HYP_HR_SR_OB_DR, ne_10m_parks_and_protected_lands, ne_10m_railroads, ne_10m_roads, and ne_10m_populated_places.
- Those source directories total approximately 3.3 GB with overlapping collections. Natural Earth 10m is 1:10 million scale, not street-level resolution.

## Implementation sequence

1. Inspect repository instructions and current spatial API, packaging, scene, search, and refresh contracts. Inventory supplied shapefiles, attributes, CRS, and duplicate datasets.
2. Build a reproducible offline import pipeline with provenance, checksums, coverage, attribution, feature counts, and size reporting. Keep generated geographic packages outside source control. Import representative global reference layers first; conversion must not run in the UI thread.
3. Serve bounded reference features or tiles through the existing EarthGlass API. Add zoom-aware labels and border rendering to Cesium, with request cancellation, viewport limits, and label collision handling. Integrate offline place search and selection.
4. Add nationwide U.S. detail from downloadable sources with appropriate redistribution terms. Determine actual source coverage and package size; reuse existing mobility infrastructure. Keep worldwide overview functioning during import.
5. Connect installed-package state and stale enabled-layer refresh to existing cache/network/scheduler behavior. Preserve previous valid packages on failed updates and expose freshness and missing coverage.
6. Verify offline startup, global labels, U.S. coverage, online imagery preservation, performance, and update recovery. Record evidence below. Do not deploy cloud automatically.

## Completion checks

- [ ] Global reference packages imported and validated from supplied resources.
- [ ] Country, city, ocean labels and borders visible at appropriate scales, including Brazil and multiple continents.
- [ ] Offline search and selected-place markers use installed data.
- [ ] U.S. detail coverage inventoried, installed, and verified across the country.
- [ ] Online detailed imagery remains available without visual regression.
- [ ] Explicit offline mode works with external networking blocked.
- [ ] Startup displays cached content without waiting for refresh or conversion.
- [ ] Refresh failure retains valid data; timestamps and missing coverage remain visible.
- [ ] Automated tests and frontend build pass; interactive checks recorded.
- [ ] Storage usage and known limitations documented accurately.

## Progress

- 2026-09-20 continuation: installed global land boundary package at `%LOCALAPPDATA%/OBEOS/Earth/maps/reference/boundaries.geojson`: 590 features, 1,103,586 bytes. Source shapefiles are local Natural Earth land and disputed-area boundary lines. Simplification tolerance is 0.02 degrees for reference overview; this is not high-detail municipal coverage.
- Added local `/api/maps/reference/boundaries` route and Cesium boundary rendering, including dashed disputed-area lines. Production build passed; five importer/API tests passed. No cloud deployment or commits performed.
- Diagnosed the eleven skipped marine records: all have empty names, so they are correctly omitted from labels. No missing names should be invented.
- Next: interactive globe verification including antimeridian and label overlap behavior; layer visibility controls; U.S. state/county/place and road source acquisition with measured size; finer geometry/detail budgets; refresh/offline acceptance tests. Existing online imagery remains unchanged. Runtime restart is needed to load changed server routes and client assets.

- Implemented `python -m earthglass.reference_import --root <cultural-root> --root <physical-root> --output <package.geojson>` with optional `maps` dependencies, source hashes, WGS84 checks, duplicate-source selection, and atomic replacement.
- Real-data import produced `.earthglass-cache/reference/labels.geojson`: 7,895 labels, 1,483,235 bytes; 258 country/territory records, 7,342 populated places, 295 marine areas. Eleven marine records were rejected by label validation; investigate before declaring coverage complete.
- Three coordinate validation tests passed. Ocean labels derive representative points from the largest polygon component. Antimeridian placement and interactive label visibility still need review.
- Connected package serving at `/api/maps/reference/labels` in the existing OBEOS Earth host. Installed generated data in `%LOCALAPPDATA%/OBEOS/Earth/maps/reference/labels.geojson` for the default runtime (custom data directories require their own package installation).
- Added Cesium reference labels with zoom-dependent city ranking, viewport and horizon filtering, overlap rejection, a 250-visible-label cap, and cancellation/cleanup. Existing imagery stays unchanged.
- Frontend production build passed; four importer/API tests passed. Built assets are ready for a relaunched Earth runtime. Interactive visual verification is still outstanding; do not mark visible-map acceptance complete on build evidence alone.
- Borders, nationwide U.S. detail, UI controls, and offline acceptance remain outstanding. Changes are local and uncommitted.

- Initial source inspection and resource inventory completed; implementation and acceptance checks remain outstanding.
- Hourly task continuation registered as obeos-offline-map-completion. Disable it when all agreed acceptance checks are verified, or report a concrete blocker when progress requires user input.
