# Proposal

## Why

The backend currently relies on a manually passed `lock_reason` string and applies a rigid hard-lockout (`locked: true`) on bicycle routes exceeding 15 minutes. To maximize user agency and city-level utility, the app should automatically retrieve real-time air quality (GIOŚ Kraków stations) and weather conditions (Open-Meteo), presenting transparent health advisories and contextual risk badges per route rather than forcibly blocking user choices.

## What Changes

- Add an **environmental intelligence service** (`backend/app/environment.py`) that fetches data from GIOŚ (monitoring stations in Kraków) and Open-Meteo (hourly weather forecast for the arrival deadline).
- Implement in-memory TTL caching (15–20 minutes) and ultra-fast spatial matching (<0.01 ms) to look up the nearest GIOŚ monitoring station without blocking the request critical path.
- Replace the rigid hard-lock policy with an **Advisory Health Nudge model**:
  - Routes remain selectable by the user (`locked: false` by default).
  - Each route position receives a `health_advisory` object detailing risk level (`SAFE`, `MODERATE`, `WARNING`, `DANGER`), badge label, affected legs (e.g. cycling in smog/rain), and explanatory rationale.
  - The API response includes an `environment` summary (nearest station, PM10/PM2.5 metrics, air quality index, temperature, precipitation).
- The `default_index` automatically selects the safest/cleanest route as a smart default, while keeping full freedom of choice for the user.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `route-slider-api`: Updates the environmental safety behavior from rigid route blocking to an automated, real-time advisory health nudge using GIOŚ and Open-Meteo data.

## Impact

- **Affected code**: `backend/app/environment.py` (new), `backend/app/schemas.py`, `backend/app/service.py`, `backend/app/main.py`.
- **Dependencies**: Uses `httpx` (already installed) for asynchronous API polling.
- **External APIs**: Public GIOŚ API (`api.gios.gov.pl`) and Open-Meteo API (`api.open-meteo.com`) — both free and requiring no API keys.
