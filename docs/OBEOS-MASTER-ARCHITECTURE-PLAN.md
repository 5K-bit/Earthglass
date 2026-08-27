# OBEOS Master Architecture Plan

## Purpose

EarthGlass is the geospatial information engine within the OBEOS ecosystem. It is not a separate product from OBEOS and it does not own the planetary renderer.

OBEOS is the complete operating environment. DAISE is the shared system brain. Individual repositories and named projects are specialized subsystems that provide distinct capabilities under that brain.

## System architecture

```
                         OBEOS
                           |
                        DAISE
                    system brain
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
     PERCEPTION          WORLD             ACTION
    Project 3000      OBEOS Earth          Tools
          |                |                |
          +----------------+----------------+
                           |
                    EVENT_BACKBONE
                           |
          +----------------+----------------+
          |                                 |
       Memory                            HUD/UI
```

OpenLive is the human interaction/sensory interface around DAISE.

## Subsystem responsibilities

### DAISE — brain and orchestrator
- reasoning and decision-making
- identity and conversation
- tool selection and execution orchestration
- correlation across perception, world state, events, and memory
- model/runtime abstraction

DAISE should consume normalized capabilities and events rather than becoming tightly coupled to Cesium, a specific voice stack, or individual sensor providers.

### Project 3000 — perception
Owns interpretation of local or attached sensor inputs:
- cameras
- computer vision
- object detection
- OCR/screen perception
- local sensors
- image/video analysis

3000 emits normalized perception events. It does not own the global 3D Earth.

### OBEOS Earth — planetary/world interface
Owns the planetary runtime and spatial presentation:
- Cesium/3D Earth
- terrain, atmosphere, time
- world-state visualization
- spatial navigation
- entity tracking
- spatial queries and filters

OBEOS Earth renders information supplied by EarthGlass and other OBEOS services.

### EarthGlass — geospatial information engine
Owns renderer-agnostic geospatial information:
- layer definitions
- layer registry
- provider contracts
- normalized geospatial feature payloads
- source metadata
- provider refresh/caching behavior
- geospatial APIs and CLI

EarthGlass must remain usable without Cesium or React.

Current repository architecture already establishes this boundary: provider adapters feed a LayerRegistry and can serve FastAPI, CLI, Leaflet, or OBEOS Earth/Cesium clients.

### OpenLive — human interaction interface
Use OpenLive as an implementation/reference for:
- local VAD/STT/turn detection/TTS
- voice interaction
- barge-in/cancellation
- camera and screen input
- live WebSocket interaction protocol
- agent permissions and session controls

OpenLive is not DAISE. OBEOS should integrate its useful interfaces behind an OBEOS assistant gateway rather than make the core brain depend on OpenLive internals.

### EVENT_BACKBONE — system nervous system
All major subsystems publish and consume normalized events.

Initial event families:
- `user.spoken`
- `camera.observation`
- `screen.changed`
- `object.detected`
- `aircraft.position`
- `vessel.position`
- `satellite.position`
- `weather.observation`
- `earthquake.detected`
- `fire.detected`
- `system.alert`
- `tool.requested`
- `tool.completed`
- `memory.created`

### Memory
Maintain distinct concepts:
- **World State:** what is happening now
- **Event History:** what happened
- **Long-Term Memory:** what OBEOS has learned or should remember

## World model

The target information flow is:

```
External feeds / local sensors
          |
          v
     Normalization
          |
          v
   EVENT_BACKBONE
          |
          v
      WORLD STATE
          |
          +------> OBEOS Earth
          |
          +------> DAISE
```

Project 3000 and EarthGlass can therefore contribute observations to the same world model.

Example:

```
Project 3000: visual aircraft observation
          +
EarthGlass: geospatial/aircraft data
          |
          v
      WORLD STATE
          |
          v
         DAISE
          |
          v
correlation / reasoning / action
```

## Implementation roadmap

### Phase 1 — EarthGlass foundation
Current milestone:
- renderer-independent LayerDefinition
- central LayerRegistry
- provider protocol
- FastAPI adapter
- CLI adapter
- tests enforcing renderer independence

Next:
1. implement provider adapter interface fully
2. add live USGS earthquake retrieval
3. add normalized feature validation
4. add source metadata/provenance
5. add persistent caching
6. add refresh lifecycle/state
7. expose stable geospatial API

### Phase 2 — OBEOS Earth V1
- connect EarthGlass to the planetary client
- Cesium globe
- NOAA GFS weather ingestion
- temperature visualization
- basic time/state handling
- graceful unavailable/degraded states

### Phase 3 — World layers
Add and normalize:
- aircraft
- earthquakes
- satellites
- vessels
- fires/environmental events
- additional geospatial infrastructure as justified

Each source must have:
- provider adapter
- normalized schema
- lifecycle state
- timestamp/source metadata
- failure behavior
- cache/degraded behavior

### Phase 4 — Spatial intelligence
Implement a stable OBEOS spatial API:
- `world.search`
- `world.nearby`
- `world.entity`
- `world.events`
- `world.weather`
- `map.fly_to`
- `map.track`
- `map.layer`
- `map.filter`
- `map.select`

DAISE invokes these capabilities; it does not manipulate Cesium internals directly.

### Phase 5 — God's Eye View capability study
God's Eye View is a reference implementation for proven spatial interaction patterns.

Study/adapt selectively:
- layer management
- camera/navigation actions
- entity tracking
- spatial command vocabulary
- context modes
- source/lifecycle handling
- spatial UI patterns

Do not make OBEOS depend on its application architecture. Perform license and data-provenance review before reusing code, assets, or datasets.

### Phase 6 — OpenLive integration
Integrate the useful OpenLive interaction stack:
- voice input
- VAD/STT/turn detection
- TTS
- barge-in
- camera/screen frames
- live session transport
- permission/elicitation handling

Target:

```
OpenLive
   |
OBEOS Assistant Gateway
   |
DAISE
```

The interaction protocol should remain replaceable.

### Phase 7 — Project 3000 bridge
- emit normalized perception events
- connect camera/screen observations to EVENT_BACKBONE
- support local inference
- correlate visual observations with World State
- keep 3000 independent from the planetary renderer

### Phase 8 — Unified world intelligence
DAISE should be able to reason across:
- external geospatial observations
- local visual observations
- system state
- event history
- memory

Core query concepts:
- where?
- when?
- what?
- how many?
- what changed?
- what is nearby?
- what is moving?
- what is unusual?

### Phase 9 — OBEOS HUD
Unify:
- DAISE conversation
- 3D Earth
- world-state panels
- perception results
- system status
- voice/touch/keyboard controls

All input methods should resolve to the same DAISE/tool interfaces.

### Phase 10 — Offline-first operation
When disconnected:
- local DAISE remains available
- local STT/TTS remains available
- local memory remains available
- local perception remains available
- cached world data remains available
- external live feeds become explicitly unavailable/stale

Never represent stale external data as live.

## Engineering rules

1. **OBEOS is the product/system.** Repositories are subsystem boundaries.
2. **DAISE is the brain.** Do not duplicate orchestration in individual subsystems.
3. **EVENT_BACKBONE is the integration spine.** Prefer events/contracts over point-to-point coupling.
4. **EarthGlass owns geospatial information; OBEOS Earth owns the planet renderer.**
5. **Project 3000 owns perception, not global world visualization.**
6. **OpenLive owns interaction concerns, not DAISE reasoning.**
7. **External repositories are evaluated by capability:** adopt, adapt, isolate, or replace.
8. Every subsystem needs a defined purpose, interface, failure behavior, recovery path, and scalability path.
9. Source attribution, licensing, and data provenance must be tracked for every external feed or reused component.
10. Build the smallest vertical slice that proves the architecture before expanding the number of feeds.

## Immediate execution target

Do not attempt the entire architecture at once.

The next vertical slice is:

```
USGS/NOAA
   |
EarthGlass
   |
EVENT_BACKBONE
   |
WORLD STATE
   |
OBEOS Earth
   |
DAISE spatial query
```

Then add OpenLive and Project 3000 through the same contracts.

The objective is not to build several disconnected applications. The objective is to progressively assemble one OBEOS system whose specialized components share the same brain, event backbone, world state, and tool contracts.
