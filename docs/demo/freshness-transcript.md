| Step | HTTP | cache.status | stale | age (s) | features | provider state | serving cache |
|---|---|---|---|---|---|---|---|
| 1 cold start, upstream up | 200 | live | False | None | 3 | ready | False |
| 2 +2 min, inside 5 min interval | 200 | cache | False | 120.0 | 3 | ready | True |
| 3 +10 min, upstream down | 200 | cache | True | 600.0 | 3 | degraded | True |
| 4 manual refresh while upstream down | 200 | cache | True | 600.0 | 3 | degraded | True |
| 5 process restarted, upstream still down (disk cache) | 200 | cache | True | 600.0 | 3 | degraded | True |
| 6 upstream recovered | 200 | live | False | None | 3 | ready | False |
| 7 corrupt cache file, upstream down | 503 | None | None | None | None | unavailable | False |
| 8 no cache at all, upstream down | 503 | None | None | None | None | unavailable | False |

Errors reported:

- Step 3: `TimeoutError: upstream timed out (simulated)`
- Step 4: `TimeoutError: upstream timed out (simulated)`
- Step 5: `TimeoutError: upstream timed out (simulated)`
- Step 7: `USGS earthquakes are unavailable and no valid cache exists`
- Step 8: `USGS earthquakes are unavailable and no valid cache exists`
