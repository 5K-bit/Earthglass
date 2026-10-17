# Offline map verification

## 2026-10-04: Network-failure label recovery

- Corrected the scene status handler to show local labels and boundaries when
  online satellite/street tiles enter fallback, not only in explicit offline mode.
- Online-ready state hides local references again to avoid duplicate labels.
- Added three state-transition policy tests; full frontend suite: 41 passed in
  13 files. Local production build passed, including TypeScript and asset copying.
- Existing large-chunk warning remains. No imagery downloads or cloud deployment.
- Browser/native visual acceptance remains outstanding; unit tests are not a
  substitute for verifying rendered labels while disconnected.

## 2026-10-04: State label preparation

- Added optional `--include-us-states` to the label importer and state-label
  visibility between 50 km and 5,000 km camera altitude.
- Temporary source conversion: 7,946 labels, including 51 state/DC records;
  1,493,869 bytes. All 7,895 existing global label features were unchanged.
- Validation detected that Natural Earth's English name calls DC Washington;
  state labels now prefer the administrative name to avoid ambiguity.
- Corrected package installed into the default local runtime reference root:
  7,946 labels, 51 distinct state/DC names, 1,493,879 bytes. Original global
  labels compared unchanged before atomic replacement. Backup retained as
  `labels.pre-us-states.faebbdfad62c.geojson` beside the installed package.
- Frontend suite: 38 tests passed across 12 files. This is regression coverage,
  not interactive map visual acceptance.
- Local `npm run build` completed on 2026-10-04, including TypeScript build,
  Vite bundling, and Cesium asset copying. Desktop development assets now contain
  the state zoom guard. Output: 406 files, 11,636,935 bytes.
- Build warns about the 4.18 MB scene-controller chunk (1.13 MB gzip); no build
  errors. No tracked files were changed by the build itself.
- Existing online satellite/road imagery remains remote; offline mode still uses
  the bundled Natural Earth overview. This build does not add offline satellite
  resolution. Interactive visual acceptance and richer US detail remain pending.
- Existing reference/offline suite passed 10 tests before the naming correction.

## 2026-09-30: US state outline package

- Added opt-in `--include-us-states` to the existing boundary importer.
- Uses supplied Natural Earth admin-1 polygons filtered to USA; no downloads.
- Exports line geometry through the existing boundaries API and renderer.
- Source hashes and attribution remain in package metadata.
- Local conversion verified 590 original border features unchanged, plus 51
  state/DC outlines. Expanded package: 1,524,174 bytes. Baseline generated
  package: 1,109,486 bytes.
- Reference import/API and offline regression tests: 10 passed.
- Optional local-source integration regression added separately.
- Installed into the default local runtime reference assets on 2026-09-30.
  Interactive rendering remains unverified.
- State outlines include coastlines. They are not street data or satellite
  imagery. State-name labels and broader US detail remain outstanding.
- No cloud deployment, imagery changes, or canonical authority changes.

Build using the existing Python environment from the EarthGlass directory:

```powershell
python -m earthglass.boundary_import --root "$HOME/Downloads/10m_cultural" --output "<reference-root>/boundaries.geojson" --include-us-states
```

Resolve the active reference asset root before installing. This command
atomically replaces only the generated boundary package, not label/imagery data.

### Runtime installation verification

- Target: `%LOCALAPPDATA%/OBEOS/Earth/maps/reference/boundaries.geojson`.
- Original package backed up beside it as
  `boundaries.pre-us-states.0c41e6dda965.geojson`.
- Compared original feature IDs, geometry, and disputed flags after install:
  all preserved. Label file SHA-256 unchanged; imagery not touched.
- Existing router exercised against installed files via isolated TestClient:
  boundaries HTTP 200, 641 features including 51 US state/DC outlines;
  labels HTTP 200, 7,895 labels.
- This is installed-asset/API verification, not a live desktop visual test.
  Existing browser responses may retain the prior package for up to one hour
  under the current cache header; reload with cache disabled to inspect sooner.
