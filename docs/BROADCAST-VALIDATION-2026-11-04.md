# EarthGlass Broadcast v0.1 — demonstration validation record

**Date:** 2026-11-04 (operator local date)  
**Product:** EarthGlass Broadcast prototype v0.1  
**Release classification:** **Demonstration Validated — PROTOTYPE / NOT FOR AIR**  
**Scope:** Unattended/station production approval **not granted**.  
**Repository:** [5K-bit/Earthglass](https://github.com/5K-bit/Earthglass)  
**Implementation track:** [PR #6](https://github.com/5K-bit/Earthglass/pull/6), [PR #7](https://github.com/5K-bit/Earthglass/pull/7), [PR #8](https://github.com/5K-bit/Earthglass/pull/8), [PR #9](https://github.com/5K-bit/Earthglass/pull/9)

## Evidence classification

- **Operator-reported real OBS test:** The operator confirmed all six checks below passed on 2026-11-04. This is a first-party acceptance report; no OBS recording, performance trace, screen capture, or external-witness sign-off is attached here.
- **Browser integration tests:** The operator also reported preview/TAKE separation, server-loss behavior, and recovery while testing with live NOAA data.
- **Automated tests:** The operator reported 68 frontend tests passing and a clean TypeScript type check after the freshness fixes. GitHub Actions reported passing EarthGlass OBEOS Component CI on the involved PR heads prior to this documentation update. The final merged main-branch result must be checked separately; earlier PR CI is not proof of a post-merge production run.
- **Source review:** The source includes explicit withholding of non-live radar images, a three-part NWS feed freshness rule, and server-only control of the program view.

## OBS acceptance — six operator-confirmed passes

| ID | Action and expected behavior | Result | Evidence type |
|---|---|---|---|
| OBS-01 | Create a Browser Source at `broadcast.html?program=1`; verify that the 3D globe renders. | **PASS** | Operator-reported OBS test |
| OBS-02 | Leave the OBS program on New York; stage Miami in the control interface without pressing TAKE. The OBS program must remain New York. | **PASS** | Operator-reported OBS test |
| OBS-03 | Press TAKE; verify that OBS changes to Miami and that the program follows the server-held state. | **PASS** | Operator-reported OBS test |
| OBS-04 | Change radar / GFS presentation fields; verify product identity and corresponding radar-observation or model-cycle timestamps. | **PASS** | Operator-reported OBS test |
| OBS-05 | Stop the backend; confirm that the program holds its last shot, the operator reports **CONTROL LINK LOST**, TAKE is disabled, and stale/invalid weather information is withheld or explicitly marked unavailable. | **PASS** | Operator-reported OBS test |
| OBS-06 | Restart the backend; confirm that the control link returns and the program recovers its previously committed on-air selection. | **PASS** | Operator-reported OBS test |

**OBS setup:** Browser Source, nominal 1920 × 1080, with initial 30 FPS source configuration. **This is not a measured 30 FPS or 1080p rendering benchmark.**

## Safety fixes and additional verification

1. **Radar must not present stale imagery.** Radar assessment now returns `image: null` and `rectangle: null` for stale cases; the scene removes the imagery overlay and shows `RADAR STALE · NO DATA SHOWN` while retaining the observation timestamp. Unit tests cover non-live cases. **A deliberately aged radar frame was not injected during the live NOAA run.**
2. **Alert banners and polygons must not invent freshness.** To display active alerts or `NO ACTIVE NWS ALERTS`, the client now requires explicit `metadata.cache.stale === false`, a source retrieval timestamp no older than 5 minutes, and a browser fetch no older than 3 minutes. Missing or invalid freshness metadata is unavailable. The operator reported that stopping the server changed the Miami flood-statement display to `ALERT FEED UNAVAILABLE` after approximately three minutes. These safeguards were unit tested; a complete long-duration severe-weather exercise remains open.
3. **Preview must not bypass TAKE.** The program display no longer receives same-browser preview changes through `BroadcastChannel`. It polls authoritative server-held state, with preview/TAKE endpoints and a staged-shot conflict check (HTTP 409). The operator observed stage/TAKE isolation and recovery after restarting the backend with the shot preserved.

## Follow-up engineering gates — not completed

- [ ] Attach an OBS capture/recording and hardware details (GPU, browser/OBS version, output dimensions, render frame times).
- [ ] Force an expired radar frame during an end-to-end browser/OBS test to document removal from the globe.
- [ ] Run extended soak testing (multiple days), network impairment, alert feed loss/recovery and clock-skew scenarios.
- [ ] Measure sustained 1080p/60 and target hardware performance; evaluate 4K separately if required.
- [ ] Have a qualified station meteorologist review severe-weather workflows, alert semantics, geography and data attribution.
- [ ] Implement station-specific authentication/authorization, security audit events, observability, deployment/rollback, monitoring and SLA before production.
- [ ] Test station-specific switching/capture equipment and integrations such as vMix/CasparCG/NDI/SDI where applicable.

## Acceptance decision

**GO for supervised demonstrations and station pilot discussions.**  
**NO-GO for unattended live broadcast, emergency-alert decision-making, production service commitments, or removing the PROTOTYPE / NOT FOR AIR watermark.**

The Apache-2.0 EarthGlass core remains open source. Commercial value is in the station integration, branding, operator workflows, deployment, training and reliability support. This evidence record is a scope-limited demonstration acceptance, not third-party certification.
