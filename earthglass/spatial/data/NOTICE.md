# City search attribution

The bundled city index is derived from GeoNames cities15000 and countryInfo, retrieved by tools/build_place_index.py. GeoNames data is licensed under Creative Commons Attribution 4.0: https://creativecommons.org/licenses/by/4.0/. Source: https://download.geonames.org/export/dump/.

OBEOS retains city names, selected aliases, representative coordinates, country labels, population for search ranking, and source identifiers. It normalizes names for local matching. This is a city index, not a street-address geocoder. Retrieval time and the original archive SHA-256 are embedded in the compressed index. No live search requests are sent to GeoNames.
