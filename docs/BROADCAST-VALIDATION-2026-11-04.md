# EarthGlass Broadcast v0.1 — demonstration validation record (OBS acceptance: all six checks on video)

**Date:** 2026-11-04 (operator local date)  
**Product:** EarthGlass Broadcast prototype v0.1  
**Release classification:** **Demonstration candidate — operator reports all 6 OBS checks passed; recorded evidence now covers all six (OBS-01 to OBS-06), including a real GFS model-cycle timestamp — PROTOTYPE / NOT FOR AIR**  
**Scope:** Unattended/station production approval **not granted**.  
**Repository:** [5K-bit/Earthglass](https://github.com/5K-bit/Earthglass)  
**Implementation track:** [PR #6](https://github.com/5K-bit/Earthglass/pull/6), [PR #7](https://github.com/5K-bit/Earthglass/pull/7), [PR #8](https://github.com/5K-bit/Earthglass/pull/8), [PR #9](https://github.com/5K-bit/Earthglass/pull/9)

## Evidence classification

- **Real OBS test: operator reports all six checks passed; video evidence partial (2026-11-04/05, operator-run).** Two OBS recordings were made on the operator machine (`2026-11-04 18-49-49.mp4`, 32 min, and `2026-11-04 19-23-05.mp4`, 3 min 33 s; stored outside Git). Both capture only the program output; the operator page is not visible in either, so checks that depend on seeing the operator interface rest on the operator's report (see the Operator result and Recorded evidence columns below). The operator states that they clicked each shot (New York, Miami, San Francisco, Chicago) in the operator interface. An earlier revision of this record listed all six checks as passed before any OBS run; that was incorrect and was corrected.
- **Hardware / software:** OBS Studio 32.0.4. Graphics: Intel UHD Graphics, driver 31.0.101.2137 (from a system query on the operator machine; operator has not separately confirmed). Frame times not measured.
- **Third recording (2026-11-05, `2026-11-05 10-46-29.mp4`, 2 min 48 s):** NY radar (observed 15:41 UTC) then Miami temperature held to the end, through an API-only outage (stopped 10:47:22, restarted 10:48:55, about 93 s). The program kept showing its last shot; the Coastal Flood Statement stayed, correctly, as the outage was under the 3-minute alert limit. OBS records only the program output, so the operator page is never on video; operator answers for OBS-02, 05 and 06 were given in chat.
- **Browser integration tests (assistant-run, 2026-11-04):** with the operator page and the program page in separate browser tabs against live NOAA data: preview did not change the program; TAKE changed it; stopping the backend disabled TAKE, showed CONTROL LINK LOST and held the program; after about three minutes the alert banner changed to ALERT FEED UNAVAILABLE; restarting the backend restored control with the on-air shot preserved. A radar frame whose cached observation time was aged by two hours was removed from the globe and replaced by a RADAR OUT OF DATE warning. These are not OBS results.
- **Automated tests:** 68 frontend tests passed and a clean TypeScript type check after the freshness fixes. [GitHub Actions run 41921502304](https://github.com/5K-bit/Earthglass/actions/runs/41921502304) completed successfully on integration commit `3e3bb55de5317058ce03339889f99c8ba18be158`: `obeos-earth-client` passed frontend tests and build; `earthglass-api` passed Python pytest, spatial contract verification and manifest checks. This commit included the updated validation documentation and the merged #6/#7/#8 changes. After passing, PR #9 was merged to `main`. These results do not establish a separate production-host or post-deployment test.
- **Source review:** The source includes explicit withholding of non-live radar images, a three-part NWS feed freshness rule, and server-only control of the program view.

## OBS acceptance — operator result and recorded evidence, kept separate

| ID | Check | Operator result | Recorded evidence | Evidence still missing |
|---|---|---|---|---|
| OBS-01 | Browser Source at `broadcast.html?program=1` renders the 3D globe. | PASS | On video: both recordings show the globe; the first runs 32 min with radar observation time advancing (23:48 → 00:18 UTC). | None. |
| OBS-02 | Staging Miami without TAKE leaves the OBS program on New York. | PASS | On video (recording 4, side by side): from 0:00 the operator page has Miami staged while the OBS program stays on New York until 0:26; the cut to Miami follows the TAKE TO AIR press at about 0:26–0:28. The click that staged Miami is before the recording starts. | None for the stay-on-New-York behavior. |
| OBS-03 | TAKE changes the OBS program to the staged shot, following server state. | PASS | On video (recording 4): OBS changes New York → Miami at about 0:26–0:28 with the cursor on TAKE TO AIR; the page then shows ON AIR: MIA / radar. Server state at that time: `mia / radar`, revision 9. Earlier, recording 2: New York → Miami → San Francisco → Chicago. | None. |
| OBS-04 | Product identity and radar-observation / model-cycle timestamps are shown. | PASS | On video: radar identity and observed time (Nov 7, 00:36 UTC in recording 5), alert expiry times, and the stale-radar warning. **Real GFS (recording 5, commit `4059824`): temperature, wind and air pressure shots show "NOAA GFS MODEL ANALYSIS · REVIEW REQUIRED" and "MODEL CYCLE Nov 6, 18:00 UTC", legible at about 0:40, 1:45 and 2:30 of the OBS recording, with PROTOTYPE / NOT FOR AIR visible.** | Other GFS fields (precipitation rate, cloud cover, humidity) were refreshed live but not put on air in a recording. |
| OBS-05 | Backend stopped: program holds its last shot; operator shows **CONTROL LINK LOST** with TAKE disabled; stale data is withheld or marked unavailable. | PASS | On video (recording 4): the API console window is visible at about 5:26–5:30 and closed by mouse about 5:30–5:45 (about 14:41:30–14:41:45). By about 5:52 the operator page shows CONTROL LINK LOST with TAKE TO AIR greyed, and OBS holds Miami. ALERT FEED UNAVAILABLE appears on OBS and the operator page at about 7:30–7:36 (about 14:43:30–14:43:35), roughly 2 min after the API closed; the 3-minute limit is measured from the last successful alert fetch. A red RADAR OUT OF DATE / NO RADAR IS SHOWN box follows at about 8:00–8:05. API confirmed down by a health check at 14:42:24. | None. |
| OBS-06 | Backend restarted: control link returns and the committed on-air selection recovers. | PASS | On video (recording 4): the API was relaunched at 14:47:21 and answered by 14:48:07; on the server the on-air state remained `mia / radar`, revision 9, with nothing staged. TAKE TO AIR is re-enabled by about 12:02–12:10 (about 14:48:01–14:48:09); the flood-statement banner and fresh radar return shortly after. OBS showed Miami throughout. | The control-link text returning to "Server link OK" was not read frame by frame. |

**OBS setup:** Browser Source, nominal 1920 × 1080, with initial 30 FPS source configuration. **This is not a measured 30 FPS or 1080p rendering benchmark.**

### Recording 5 — real GFS in OBS, on merged `main` (2026-11-06)

- **Tested commit:** `4059824` (`main` after PRs #16 and #18: the GFS catalog is served by the main API and refreshes itself). The API was started with no manual weather request; all six layers moved to the 18:00 UTC cycle on their own.
- **Files (stored outside Git):** `GFSrecording.mp4` (full screen, OBS beside the operator page, 4 min 37 s, 1912×1072) and `2026-11-06 19-40-57.mp4` (OBS program output only, 3 min 02 s, 1920×1080). Video time 0:00 is about 19:40:58 local (00:40:58 UTC, Nov 7).
- **Timeline (OBS recording, approximate):** 0:00–0:25 New York radar (observed Nov 7, 00:36 UTC); about 0:25–0:30 cut to the temperature shot; about 1:45–1:50 wind; about 2:10 air pressure through the end at 3:02. The operator page, with its field menu and TAKE TO AIR button, is visible in the full-screen recording.
- Times were read from contact-sheet frames, so allow several seconds either way.

### Recording 4 — side-by-side run on merged `main` (2026-11-06)

- **Tested commit:** `fd159da541dd34766098bd59afd09a6d2a4e025a` (`main`, after PRs #10 and #11).
- **Setup:** OBS Studio 32.0.4 Browser Source `http://127.0.0.1:5180/broadcast.html?program=1` beside the operator page `http://127.0.0.1:5180/broadcast.html`, one screen, Windows 11. API on 127.0.0.1:8000, web app on 5180, cache default.
- **Files (stored outside Git):** `Screen Recording 2026-11-06 144909.mp4` and `OBS screen recording.mp4`, 13 min 10 s, 1918×1078. The two files are byte-identical; the full-screen capture of both windows was copied under both names. Video time 0:00 is 14:35:59 local (19:35:59 UTC).
- **Timeline (video time, approximate):** 0:26–0:28 TAKE and cut to Miami; about 5:30–5:45 API closed; about 5:52 CONTROL LINK LOST and TAKE greyed; about 7:30–7:36 ALERT FEED UNAVAILABLE; 14:47:21 API relaunched; about 12:02–12:10 TAKE re-enabled; program on Miami throughout.
- **Not covered:** a real GFS model field (see OBS-04). A first attempt at 14:30 (not used) failed because the API did not allow the web page's origin; the API was restarted with the correct allowed origin before the run.
- Times were read from contact-sheet frames, so allow a few seconds either way.

**Operator attestation (2026-11-06):** the operator states that every step requested in the OBS tests worked as expected, including the wait for the alert-feed-unavailable state, and asks that the checks be recorded as passed. Recorded as attested, not independently evidenced: the only recording of the planned outage (recording 3) shows an outage of about 93 s, which is below the 3-minute alert threshold, and at that time no recording showed the operator page or the GFS model field (recording 4, below, later supplied the operator page evidence). The Operator result column records that statement; the Recorded evidence and Evidence still missing columns record what the recordings show. OBS-04's GFS timestamp and the alert-unavailable part of OBS-05 rest on the statement alone.

## Safety fixes and additional verification

1. **Radar must not present stale imagery.** Radar assessment now returns `image: null` and `rectangle: null` for stale cases; the scene removes the imagery overlay and shows `RADAR STALE · NO DATA SHOWN` while retaining the observation timestamp. Unit tests cover non-live cases. A deliberately aged radar frame was injected in a browser run on 2026-11-04 and removed from the globe; this has not been repeated in OBS.
2. **Alert banners and polygons must not invent freshness.** To display active alerts or `NO ACTIVE NWS ALERTS`, the client now requires explicit `metadata.cache.stale === false`, a source retrieval timestamp no older than 5 minutes, and a browser fetch no older than 3 minutes. Missing or invalid freshness metadata is unavailable. Stopping the server in a browser run changed the Miami flood-statement display to `ALERT FEED UNAVAILABLE` after approximately three minutes. These safeguards were unit tested; a complete long-duration severe-weather exercise remains open.
3. **Preview must not bypass TAKE.** The program display no longer receives same-browser preview changes through `BroadcastChannel`. It polls authoritative server-held state, with preview/TAKE endpoints and a staged-shot conflict check (HTTP 409). Stage/TAKE isolation and recovery after a backend restart with the shot preserved were observed in a two-tab browser run, not yet in OBS.

## Follow-up engineering gates — not completed

- [ ] Attach the OBS recordings (partly done, stored outside Git) and record hardware details (GPU, driver, OBS version, render frame times).
- [x] Force an expired radar frame in a browser run (done); repeat it inside OBS.
- [x] Full-screen capture with the operator page beside OBS: stage without TAKE, TAKE, API outage with ALERT FEED UNAVAILABLE, recovery (recording 4, commit `fd159da`).
- [x] Capture a real GFS model field with its model-cycle timestamp in OBS (recording 5, commit `4059824`).
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

**GO for supervised demonstrations and station pilot discussions (all six checks now have recorded video evidence).** The operator reports all six checks passed. Recorded evidence now covers all six checks: OBS-01, 02, 03, 05 and 06 (recording 4, commit `fd159da`) and OBS-04 including a real GFS model-cycle timestamp (recording 5, commit `4059824`). Open items remain outside this record: a soak test, target-hardware performance and a meteorologist review. "Demonstration Validated" is not claimed until those are closed.  
**NO-GO for unattended live broadcast, emergency-alert decision-making, production service commitments, or removing the PROTOTYPE / NOT FOR AIR watermark.**

The Apache-2.0 EarthGlass core remains open source. Commercial value is in the station integration, branding, operator workflows, deployment, training and reliability support. This evidence record is a scope-limited demonstration acceptance, not third-party certification.
