# Proposal

## Why

The core routing engine and weight optimizer (`optimizer/slider_select.py`) are fully implemented and verified with 260+ unit tests, but currently only exist as a local Python CLI. The web and mobile frontends need an HTTP REST API to query multi-modal routes for Kraków, receive time vs. activity slider positions with geometry, apply environmental safety rules (smog and weather), and allow privacy-friendly user physical profile overrides.

## What Changes

- Create a **FastAPI backend** (`backend/`) exposing `POST /api/routes`.
- Serve route choices using the existing `optimizer.slider_select.plan_route_slider` engine, querying OTP 2.10 with the 7 GA-optimized slider ticks + transit anchor + walking baseline.
- Support the `has_bike` flag by selecting the corresponding pre-calculated `slider.json` (`bike` vs. `walk` variant).
- Support optional user profile overrides (`weight_kg`, `height_m`, `walk_speed_mps`, `bike_speed_mps`) with standard defaults (`70.0 kg`, `1.75 m`), ensuring physical health data remains strictly on the client device.
- Add an **outdoor exposure safety rule (15-minute threshold)**: when `lock_reason` (smog, adverse weather) is provided, routes with bicycle outdoor exposure exceeding 15 minutes are marked `locked: true` with a clear explanation, while short trips ($\le 15$ min) and clean public transit (`anchor`) remain open.
- Provide encoded leg geometries (`legGeometry { points }`), line labels, scheduled times, and health metrics (`duration_min`, `active_kcal`, `steps`, `bike_duration_min`) in the JSON response for MapLibre GL rendering.

## Capabilities

### New Capabilities

- `route-slider-api`: REST API serving health-aware, multi-modal Pareto route slider positions with geometry, user profile adaptation, and outdoor weather/smog exposure safety.

### Modified Capabilities

_None — no existing specs._

## Impact

- **New code**: `backend/` directory with FastAPI application (`main.py`), Pydantic models (`schemas.py`), route handlers, and unit/API tests.
- **Dependencies**: Python 3.12, `fastapi`, `uvicorn[standard]`, `pydantic`, `httpx` (or standard `urllib` wrapped by `optimizer.evaluate`).
- **Integration**: Imports directly from `optimizer.slider_select` and reads `slider.json` profiles; connects to OpenTripPlanner at `http://localhost:8080/otp/gtfs/v1`.
