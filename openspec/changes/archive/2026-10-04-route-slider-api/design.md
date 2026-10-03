# Design

## Context

The repository already includes a complete routing and optimization library in `optimizer/`, including `plan_route_slider()` in `optimizer/slider_select.py`, which is validated by 260+ unit tests. See `proposal.md` for motivation.

This change introduces a lightweight FastAPI backend in `backend/` that wraps `optimizer.slider_select.plan_route_slider` to expose an HTTP interface for web and mobile frontends, while refining the environmental safety policy to use an outdoor exposure time threshold (15 minutes).

## Goals / Non-Goals

**Goals:**
- Provide a clean, robust FastAPI application serving `POST /api/routes`.
- Delegate OTP querying, deduplication, MET scoring, and monotonic slider construction directly to `optimizer.slider_select.plan_route_slider`.
- Load and cache `slider.json` presets for both `bike` and `walk` variants.
- Implement the 15-minute cycling exposure safety rule during active `lock_reason` (smog, adverse weather).
- Return UI-ready payloads with polyline geometry, mode summaries, and step/calorie metrics.

**Non-Goals:**
- Frontend map rendering (handled in subsequent frontend change).
- Live polling of GIOŚ/Open-Meteo within the request critical path (backend accepts `lock_reason` as input; automated weather fetching will be added in a separate enhancement).
- Re-running the NSGA-II GA training online (uses pre-computed `slider.json`).

## Decisions

### D1: FastAPI as a direct wrapper around `optimizer.slider_select`
**Choice**: Use FastAPI with endpoint `POST /api/routes` calling `plan_route_slider()` in `optimizer.slider_select`.
**Why**: Avoids code duplication and leverages the 260+ existing tests covering deduplication, arrival buffers, MET calculation, and mini-front sorting.
**Alternatives**: Re-implementing GraphQL client and Pareto filters in `backend/` — rejected as it would waste hackathon time and discard verified logic.

### D2: Pre-loading and caching `slider.json`
**Choice**: Load `slider.json` for `bike` and `walk` from disk on app startup (or fallback to built-in default ticks if files are not yet generated) and hold them in memory.
**Why**: File I/O on every HTTP request is unnecessary. Caching parsed dictionaries in memory ensures <1ms preset lookup overhead.
**Alternatives**: Loading from disk on every request — rejected due to redundant file reads.

### D3: Outdoor exposure safety threshold (15 minutes)
**Choice**: During an active `lock_reason`, calculate total cycling duration:
$$\text{bike\_min} = \sum_{\text{leg} \in \text{legs}, \text{mode}=\text{BICYCLE}} \frac{\text{leg.duration}}{60}$$
If $\text{bike\_min} > 15.0$ minutes, set `locked = True` on the position with an explanatory lock note and warning. If $\le 15.0$ minutes, the position remains unlocked (`locked = False`).
**Why**: A rigid coordinate cutoff ($s > 0.5$) erroneously blocks short 7-minute rides or mixed Bike&Ride trips while permitting long walks. A duration-based threshold accurately reflects health risk from pollutant inhalation.
**Alternatives**: Rigid $s > 0.5$ cutoff — rejected based on user feedback; infinite penalty weights in OTP — rejected because we want the option visible but marked locked in the UI.

### D4: Pydantic request and response schemas
**Choice**: Define explicit Pydantic models:
- `RouteRequest`: `from_loc`, `to_loc`, `deadline`, `has_bike`, `user_profile` (weight, height, speeds), `lock_reason`.
- `RouteResponse`: `baseline_min`, `default_index`, `lock_reason`, `positions`, `warnings`, `otp_stats`.
**Why**: Automatic OpenAPI/Swagger documentation at `/docs`, automatic type coercion, and robust request validation.

### D5: Directory layout
**Choice**:
```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI application & endpoints
│   ├── schemas.py       # Pydantic models
│   ├── service.py       # Adapter calling optimizer.slider_select
│   └── config.py        # Settings (OTP_URL, slider paths, exposure threshold)
├── tests/
│   ├── __init__.py
│   └── test_api.py      # FastAPI TestClient endpoint tests
└── requirements.txt     # fastapi, uvicorn, pydantic
```

## Risks / Trade-offs

- **[Risk] OTP unavailable when API is called** → Mitigation: Return HTTP 503 Service Unavailable or graceful response with warnings indicating OTP connectivity failure (`otp_stats` reports errors).
- **[Risk] Missing pre-computed `slider.json` files on fresh clone** → Mitigation: Service provides a safe fallback preset loader or generates default ticks based on standard OTP weights if `optimizer/out/` is missing.
