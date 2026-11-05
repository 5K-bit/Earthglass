# EarthGlass Broadcast v0.1 — demonstration validation record (OBS acceptance partially recorded)

**Date:** 2026-11-04 (operator local date)  
**Product:** EarthGlass Broadcast prototype v0.1  
**Release classification:** **Demonstration candidate — OBS acceptance partially recorded (2 of 6 checks passed, 4 still open) — PROTOTYPE / NOT FOR AIR**  
**Scope:** Unattended/station production approval **not granted**.  
**Repository:** [5K-bit/Earthglass](https://github.com/5K-bit/Earthglass)  
**Implementation track:** [PR #6](https://github.com/5K-bit/Earthglass/pull/6), [PR #7](https://github.com/5K-bit/Earthglass/pull/7), [PR #8](https://github.com/5K-bit/Earthglass/pull/8), [PR #9](https://github.com/5K-bit/Earthglass/pull/9)

## Evidence classification

- **Real OBS test: PARTIALLY RECORDED (2026-11-04, operator-run).** Two OBS recordings were made on the operator machine (`2026-11-04 18-49-49.mp4`, 32 min, and `2026-11-04 19-23-05.mp4`, 3 min 33 s; stored outside Git). Both capture only the program output; the operator page is not visible in either, so checks that depend on seeing the operator interface are not claimed. The operator states that they clicked each shot (New York, Miami, San Francisco, Chicago) in the operator interface. An earlier revision of this record listed all six checks as passed before any OBS run; that was incorrect and was corrected.
- **Hardware / software not yet captured:** GPU, driver and OBS version were not recorded; these are required before the evidence is complete.
- **Browser integration tests (assistant-run, 2026-11-04):** with the operator page and the program page in separate browser tabs against live NOAA data: preview did not change the program; TAKE changed it; stopping the backend disabled TAKE, showed CONTROL LINK LOST and held the program; after about three minutes the alert banner changed to ALERT FEED UNAVAILABLE; restarting the backend restored control with the on-air shot preserved. A radar frame whose cached observation time was aged by two hours was removed from the globe and replaced by a RADAR OUT OF DATE warning. These are not OBS results.
- **Automated tests:** 68 frontend tests passed and a clean TypeScript type check after the freshness fixes. [GitHub Actions run 41921502304](https://github.com/5K-bit/Earthglass/actions/runs/41921502304) completed successfully on integration commit `3e3bb55de5317058ce03339889f99c8ba18be158`: `obeos-earth-client` passed frontend tests and build; `earthglass-api` passed Python pytest, spatial contract verification and manifest checks. This commit included the updated validation documentation and the merged #6/#7/#8 changes. After passing, PR #9 was merged to `main`. These results do not establish a separate production-host or post-deployment test.
- **Source review:** The source includes explicit withholding of non-live radar images, a three-part NWS feed freshness rule, and server-only control of the program view.

## OBS acceptance — two checks passed, four open

| ID | Action and expected behavior | Result | Evidence |
|---|---|---|---|
| OBS-01 | Create a Browser Source at `broadcast.html?program=1`; verify that the 3D globe renders. | **PASS** | Both OBS recordings show the globe rendering. The first runs 32 minutes with the radar observation time advancing (23:48 → 00:18 UTC) and no visible failure. |
| OBS-02 | Leave the OBS program on New York; stage Miami in the control interface without pressing TAKE. The OBS program must remain New York. | **OPEN** | Operator page not in the recording. Previously observed only in assistant-run browser tabs. |
| OBS-03 | Press TAKE; verify that OBS changes to Miami and that the program follows the server-held state. | **PASS (operator-confirmed)** | Recording 2 shows the program change New York → Miami → San Francisco → Chicago; the operator confirms each was selected in the operator interface. Server state afterwards was `chi / radar`, revision 5. The TAKE button presses themselves are not visible in the recording. |
| OBS-04 | Change radar / GFS presentation fields; verify product identity and corresponding radar-observation or model-cycle timestamps. | **PARTIAL** | Radar identity and observed time (Nov 5, 00:20 and 00:24 UTC) are shown on screen, and NWS alerts show expiry times. A model field (GFS) was not exercised; in a fresh-load frame the temperature shot is stamped "illustrative data · not a forecast". |
| OBS-05 | Stop the backend; confirm that the program holds its last shot, the operator reports **CONTROL LINK LOST**, TAKE is disabled, and stale/invalid weather information is withheld or explicitly marked unavailable. | **OPEN (partial evidence)** | An unplanned restart of both the API and web servers during recording 2 produced a black gap (about 2:15 into the recording), then a page reload showing ALERT FEED UNAVAILABLE and a red RADAR UNAVAILABLE / NO RADAR IS SHOWN warning with "NO CURRENT RADAR" (about 2:25 to 2:55). This is not the planned test: the web server restarted too, so the operator CONTROL LINK LOST message and disabled TAKE are not shown, and the program did not visibly hold its last shot. |
| OBS-06 | Restart the backend; confirm that the control link returns and the program recovers its previously committed on-air selection. | **OPEN (partial evidence)** | Radar returned with a fresh observation time and a further shot (Chicago) was taken afterwards; server on-air state persisted across the restart. The alert banner stayed ALERT FEED UNAVAILABLE for about a minute after radar returned (alerts refresh every 60 s). A clean API-only restart with the operator page visible has not been recorded. |

**OBS setup:** Browser Source, nominal 1920 × 1080, with initial 30 FPS source configuration. **This is not a measured 30 FPS or 1080p rendering benchmark.**

## Safety fixes and additional verification

1. **Radar must not present stale imagery.** Radar assessment now returns `image: null` and `rectangle: null` for stale cases; the scene removes the imagery overlay and shows `RADAR STALE · NO DATA SHOWN` while retaining the observation timestamp. Unit tests cover non-live cases. A deliberately aged radar frame was injected in a browser run on 2026-11-04 and removed from the globe; this has not been repeated in OBS.
2. **Alert banners and polygons must not invent freshness.** To display active alerts or `NO ACTIVE NWS ALERTS`, the client now requires explicit `metadata.cache.stale === false`, a source retrieval timestamp no older than 5 minutes, and a browser fetch no older than 3 minutes. Missing or invalid freshness metadata is unavailable. Stopping the server in a browser run changed the Miami flood-statement display to `ALERT FEED UNAVAILABLE` after approximately three minutes. These safeguards were unit tested; a complete long-duration severe-weather exercise remains open.
3. **Preview must not bypass TAKE.** The program display no longer receives same-browser preview changes through `BroadcastChannel`. It polls authoritative server-held state, with preview/TAKE endpoints and a staged-shot conflict check (HTTP 409). Stage/TAKE isolation and recovery after a backend restart with the shot preserved were observed in a two-tab browser run, not yet in OBS.

## Follow-up engineering gates — not completed

- [ ] Attach the OBS recordings (partly done, stored outside Git) and record hardware details (GPU, driver, OBS version, render frame times).
- [x] Force an expired radar frame in a browser run (done); repeat it inside OBS.
- [ ] Re-record OBS-02, 05, 06 (and the model-field part of OBS-04) with the operator page visible beside OBS: stage without TAKE, TAKE, stop only the API, then restart it. OBS-01 and OBS-03 are done.
- [ ] Run extended soak testing (multiple days), network impairment, alert feed loss/recovery and clock-skew scenarios.
- [ ] Measure sustained 1080p/60 and target hardware performance; evaluate 4K separately if required.
- [ ] Have a qualified station meteorologist review severe-weather workflows, alert semantics, geography and data attribution.
- [ ] Implement station-specific authentication/authorization, security audit events, observability, deployment/rollback, monitoring and SLA before production.
- [ ] Test station-specific switching/capture equipment and integrations such as vMix/CasparCG/NDI/SDI where applicable.

## Merge record (verified on GitHub)

All four PRs are **merged to `main`** in dependency-safe order:

| PR | Scope | Merge commit |
|---|---|---|
| [#8](https://github.com/5K-bit/Earthglass/pull/8) | Optional maps integration-test skip | `850e9e74eac1d846ad2335edc90776d60c45b6f9` |
| [#6](https://github.com/5K-bit/Earthglass/pull/6) | 16:9 Cesium broadcast prototype | `356a3bfee02470a882303549ab6e9859e5999617` |
| [#7](https://github.com/5K-bit/Earthglass/pull/7) | NWS active-alerts provider | `64c86f6d1c40a3320d3400d09c5db4e89cbde119` |
| [#9](https://github.com/5K-bit/Earthglass/pull/9) | Radar, alert presentation, authoritative preview/TAKE, freshness fixes and pilot documentation | `b239592a4016160a8a6204446f6712041fc7fd74` |

PR #9 was reconciled with the newly merged `main` before its final CI run. The conflict resolution preserved both its broadcast enhancements and PR #8's optional-dependency test repair. The integration CI passed before the final merge; the completed merge was subsequently verified on GitHub.

## Acceptance decision

**CONDITIONAL GO for supervised demonstrations and station pilot discussions, effective once the four open OBS checks above (OBS-02, 04 model field, 05, 06) are recorded as passed.** OBS-01 and OBS-03 have passed.  
**NO-GO for unattended live broadcast, emergency-alert decision-making, production service commitments, or removing the PROTOTYPE / NOT FOR AIR watermark.**

The Apache-2.0 EarthGlass core remains open source. Commercial value is in the station integration, branding, operator workflows, deployment, training and reliability support. This evidence record is a scope-limited demonstration acceptance, not third-party certification.
