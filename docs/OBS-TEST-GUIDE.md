# OBS acceptance test guide

Purpose: prove the clean program output works as an **OBS Browser Source** and is controlled from a **separate operator page**. Takes about 30 minutes. Record the screen while you do it: the recording is the evidence.

Result of this test is written into the table at the bottom. Do not mark a check PASS unless you saw it happen.

## 0. What you need

- Windows PC with Git, Node 22+, pnpm and Python 3.11+ (already used to build this project).
- [OBS Studio](https://obsproject.com/) (free). Install it and open it once.
- Internet access (live NOAA data).

## 1. Start EarthGlass (two PowerShell windows)

**Window A — the API (radar, alerts, program control):**

```powershell
cd path\to\Earthglass
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn earthglass.web.app:app --host 127.0.0.1 --port 8000
```

Leave it running. Check `http://127.0.0.1:8000/health` in a browser shows `{"status":"ok"...}`.

**Window B — the web app:**

```powershell
cd path\to\Earthglass
$env:VITE_BROADCAST_API_ORIGIN="http://127.0.0.1:8000"
pnpm --dir obeos-earth install --frozen-lockfile
pnpm --dir obeos-earth dev
```

Note the address it prints (usually `http://localhost:5173`). If port 5173 is busy it will pick another; use whatever it prints below.

## 2. Open the operator page

In your normal browser open `http://127.0.0.1:5173/broadcast.html`. You should see the control panel on the right with **PREVIEW** shot buttons, a weather field menu and a red **TAKE TO AIR** button. The line under the menu should say "Server link OK".

Pick **New York**, set the field to **Radar (observed)** and press **TAKE TO AIR**. The panel should say `ON AIR: NYC / radar`.

## 3. Add the program output to OBS

1. In OBS, under **Sources**, click **+** and choose **Browser**. Name it `EarthGlass Program`. OK.
2. URL: `http://127.0.0.1:5173/broadcast.html?program=1`
3. Width **1920**, Height **1080**, FPS **30**. Leave "Shutdown source when not visible" **off**. OK.
4. You should see the globe, New York, and live radar in the OBS preview.
5. If the picture is black: OBS menu **Settings → Advanced** and turn on browser hardware acceleration (wording differs by version), restart OBS. If still black, note it and your graphics card in the table below; that is a useful finding.

## 4. Start recording

OBS **Controls → Start Recording**. Keep the operator page visible next to OBS (or record the whole screen) so the video shows both. Stop recording when finished. Recordings are saved under **Settings → Output → Recording Path**.

## 5. The six checks

Do them in order. Say what you see out loud while recording.

| ID | What to do | What must happen |
|---|---|---|
| OBS-01 | Look at OBS after adding the source. | The 3D globe renders in OBS. |
| OBS-02 | On the operator page click **MIAMI** (do **not** press TAKE). | OBS stays on New York. Operator shows `PREVIEW: MIAMI … not on air`. |
| OBS-03 | Press **TAKE TO AIR**. | Within about 2 seconds OBS changes to Miami. Operator shows `ON AIR: MIA`. |
| OBS-04 | Change the weather field to **Radar (observed)** and, if available, another field. Press TAKE. | OBS shows the matching product. Radar shows an **observed time** on screen; model fields show a **model cycle** time or are labelled illustrative. |
| OBS-05 | In Window A press **Ctrl+C** to stop the API. Wait one minute, then wait 3+ minutes. | Operator shows **CONTROL LINK LOST** and TAKE is disabled. OBS keeps the last shot. After about 3 minutes the alert box reads **ALERT FEED UNAVAILABLE** (never "no alerts"). |
| OBS-06 | Restart the API with the same `uvicorn` command. | Operator link returns within a few seconds. OBS still shows the shot that was on air before the restart. |

Optional extra (documents the radar safeguard): the radar warning is easiest to see by stopping the API for 15+ minutes; a stale frame must disappear and a red **RADAR OUT OF DATE** box must appear.

## 6. Record the result

Fill in, then commit this file with the recording linked (or stored outside Git and referenced here).

| ID | Result (PASS / FAIL / NOTES) |
|---|---|
| OBS-01 | |
| OBS-02 | |
| OBS-03 | |
| OBS-04 | |
| OBS-05 | |
| OBS-06 | |

- Date and tester:
- Computer, GPU, driver:
- OBS version:
- Browser Source size / FPS:
- Recording file:
- Anything that looked wrong (even if minor):

## Troubleshooting

- **Operator says "Connecting to program control" forever:** the web app cannot reach the API. Check Window A is running and `VITE_BROADCAST_API_ORIGIN` was set in Window B before `pnpm dev`.
- **TAKE says "Control refused (403)":** you opened the operator page from another computer. Writes are limited to the same machine unless `EARTHGLASS_CONTROL_TOKEN` is set on the API.
- **Weather fields other than radar look illustrative:** expected. The GFS model catalog is not mounted by the bare API; those fields are watermarked as illustrative.
- **Port busy:** use the address `pnpm dev` prints instead of 5173 everywhere above, and start the API with `$env:EARTHGLASS_CORS_ORIGINS="http://127.0.0.1:YOURPORT"` set first.
