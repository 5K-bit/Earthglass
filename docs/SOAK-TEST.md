# Soak test

Purpose: produce real reliability evidence (hours, not minutes) for a station pilot. The monitor samples the API every 15 seconds, optionally restarts it on a schedule, and the report lists outages, stale data, lost state and memory use. It reports facts; it does not grade them.

## Run it (8 hours, with a restart drill every hour)

1. Start the deployment (see "One-command deployment" in [BROADCAST-PROTOTYPE.md](BROADCAST-PROTOTYPE.md)):

   ```bash
   EARTHGLASS_CONTROL_TOKEN=choose-a-long-secret docker compose up -d --build
   ```

2. Put a shot on air, so the drills have something to check. In the operator page at `http://127.0.0.1:8080/broadcast.html` stage and TAKE New York radar. For the full picture also open `http://127.0.0.1:8080/broadcast.html?program=1` in an OBS Browser Source and leave OBS running.

3. Keep the machine awake and plugged in for the whole run (Windows: Settings, System, Power, set Sleep to Never; close the lid only if lid-close does nothing).

4. Start the monitor from the repository root. It needs only Python 3.11+ and, for memory and drills, Docker:

   ```bash
   python tools/soak/soak_monitor.py --base http://127.0.0.1:8080 --hours 8 --out soak-run \
     --container earthglass-api-1 --restart-every-minutes 60
   ```

   Samples are written to `soak-run/samples.jsonl` as they happen, so stopping early (Ctrl+C) or a crash loses nothing.

5. Make the report:

   ```bash
   python tools/soak/soak_report.py soak-run > soak-run/REPORT.md
   ```

## What it can and cannot tell you

- It measures the API from the machine running it: availability, latency, radar and alert freshness flags and ages, the age of the newest GFS cycle, whether the on-air state was ever lost or could not be saved, and API memory.
- Each restart drill restarts the API container and checks it comes back with the same on-air shot.
- It does **not** see what OBS rendered. A frozen or black picture in OBS would not appear in the report. Check the OBS preview at the start, middle and end, or record a few minutes of the OBS output at those points and keep the files with the report.
- It does not judge whether the weather content is correct. That needs a meteorologist.

## Reading the result

Look first at the outage list, any "stale" stretches and whether the revision ever went backwards. A run with no outages besides the planned restarts, no stale stretches beyond real upstream outages, no lost state and flat memory is a good first reliability report. Report anything else as it is.

Soak output directories (`soak-run*/`) are ignored by Git. Keep the report and notes with the validation record.
