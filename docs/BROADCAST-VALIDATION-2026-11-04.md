# EarthGlass Broadcast v0.1 — demonstration validation record (OBS acceptance: six operator passes, recorded evidence incomplete)

**Date:** 2026-11-04 (operator local date)  
**Product:** EarthGlass Broadcast prototype v0.1  
**Release classification:** **Demonstration candidate — operator reports all 6 OBS checks passed; recorded evidence covers 1 fully and the rest partly (see table) — PROTOTYPE / NOT FOR AIR**  
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
| OBS-02 | Staging Miami without TAKE leaves the OBS program on New York. | PASS | Not on video (OBS records only program output). Observed in assistant-run browser tabs. | Full-screen recording with the operator page visible. |
| OBS-03 | TAKE changes the OBS program to the staged shot, following server state. | PASS | On video: program changes New York → Miami → San Francisco → Chicago (recording 2); server state then `chi / radar`, revision 5. TAKE presses not visible. | Operator page visible during the takes. |
| OBS-04 | Product identity and radar-observation / model-cycle timestamps are shown. | PASS | On video: radar identity and observed time (Nov 5, 00:20 and 00:24 UTC); alert expiry times; temperature shot stamped "illustrative data · not a forecast". | A GFS model-cycle timestamp has not been captured in any recording. |
| OBS-05 | Backend stopped: program holds its last shot; operator shows **CONTROL LINK LOST** with TAKE disabled; stale data is withheld or marked unavailable. | PASS | On video: recording 3, API-only stop of about 93 s, program held Miami throughout; alert banner correctly stayed (under the 3-minute limit). Recording 2 (unplanned restart of API and web servers): black gap about 2:15, then ALERT FEED UNAVAILABLE and RADAR UNAVAILABLE / NO CURRENT RADAR about 2:25–2:55. | CONTROL LINK LOST and disabled TAKE are not on video. A planned outage over 3 minutes showing ALERT FEED UNAVAILABLE with the operator page visible has not been recorded. |
| OBS-06 | Backend restarted: control link returns and the committed on-air selection recovers. | PASS | On video: recording 3, program state remained Miami after the API restart; recording 2, radar returned with a fresh observation time and a further shot (Chicago) was taken; alert banner lagged about 1 min (alerts refresh every 60 s). | Control link returning and TAKE re-enabling are not on video. |

**OBS setup:** Browser Source, nominal 1920 × 1080, with initial 30 FPS source configuration. **This is not a measured 30 FPS or 1080p rendering benchmark.**

**Operator attestation (2026-11-06):** the operator states that every step requested in the OBS tests worked as expected, including the wait for the alert-feed-unavailable state, and asks that the checks be recorded as passed. Recorded as attested, not independently evidenced: the only recording of the planned outage (recording 3) shows an outage of about 93 s, which is below the 3-minute alert threshold, and no recording shows the operator page or the GFS model field. The Operator result column records that statement; the Recorded evidence and Evidence still missing columns record what the recordings show. OBS-04's GFS timestamp and the alert-unavailable part of OBS-05 rest on the statement alone.

## Safety fixes and additional verification

1. **Radar must not present stale imagery.** Radar assessment now returns `image: null` and `rectangle: null` for stale cases; the scene removes the imagery overlay and shows `RADAR STALE · NO DATA SHOWN` while retaining the observation timestamp. Unit tests cover non-live cases. A deliberately aged radar frame was injected in a browser run on 2026-11-04 and removed from the globe; this has not been repeated in OBS.
2. **Alert banners and polygons must not invent freshness.** To display active alerts or `NO ACTIVE NWS ALERTS`, the client now requires explicit `metadata.cache.stale === false`, a source retrieval timestamp no older than 5 minutes, and a browser fetch no older than 3 minutes. Missing or invalid freshness metadata is unavailable. Stopping the server in a browser run changed the Miami flood-statement display to `ALERT FEED UNAVAILABLE` after approximately three minutes. These safeguards were unit tested; a complete long-duration severe-weather exercise remains open.
3. **Preview must not bypass TAKE.** The program display no longer receives same-browser preview changes through `BroadcastChannel`. It polls authoritative server-held state, with preview/TAKE endpoints and a staged-shot conflict check (HTTP 409). Stage/TAKE isolation and recovery after a backend restart with the shot preserved were observed in a two-tab browser run, not yet in OBS.

## Follow-up engineering gates — not completed

- [ ] Attach the OBS recordings (partly done, stored outside Git) and record hardware details (GPU, driver, OBS version, render frame times).
- [x] Force an expired radar frame in a browser run (done); repeat it inside OBS.
- [ ] Record a full-screen capture (Windows Win+Shift+R) showing the operator page beside OBS for OBS-02/05/06, with an API outage over 3 minutes to show ALERT FEED UNAVAILABLE; exercise the model field for OBS-04.
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

**GO for supervised demonstrations and station pilot discussions (operator-attested; see attestation above).** The operator reports all six checks passed. Recorded evidence is complete only for OBS-01; the gaps are listed per check in the table above (chiefly: the operator page on video, a GFS model-cycle timestamp, and a planned 3+ minute alert-feed-unavailable outage). "Demonstration Validated" is not claimed until those are closed.  
**NO-GO for unattended live broadcast, emergency-alert decision-making, production service commitments, or removing the PROTOTYPE / NOT FOR AIR watermark.**

The Apache-2.0 EarthGlass core remains open source. Commercial value is in the station integration, branding, operator workflows, deployment, training and reliability support. This evidence record is a scope-limited demonstration acceptance, not third-party certification.
