# Design

## Context

The backend currently provides `POST /api/routes` with a hard-lockout mechanism (`locked: true`) driven by an optional input parameter. See `proposal.md` for motivation.

This design introduces automated environmental polling from GIOŚ and Open-Meteo, cached in memory, and replaces hard blocking with an advisory health risk nudge model.

## Goals / Non-Goals

**Goals:**
- Provide zero-latency environmental lookup during routing requests (<1 ms) using in-memory caching and constant-time spatial nearest-station matching.
- Connect to public, open APIs: GIOŚ (Kraków monitoring stations) and Open-Meteo (precipitation and temperature forecast).
- Compute structured health advisories (`SAFE`, `MODERATE`, `WARNING`, `DANGER`) with contextual badges and reasons.
- Keep all routes selectable (`locked: false`), maintaining user autonomy while using `default_index` as a smart, health-first recommendation.

**Non-Goals:**
- Training new GA genomes (handled offline).
- Installing physical sensors or managing private IoT networks.

## Decisions

### D1: Static Kraków monitoring stations and microsecond spatial matching
**Choice**: Embed the 6 official Kraków GIOŚ monitoring stations (Krasińskiego, Dietla, Kurdwanów, Piastów, Bronowice, Wadów) as a constant in `backend/app/environment.py`. Find the nearest station using Euclidean squared distance:
$$\Delta d^2 = (\text{lat} - \text{lat}_i)^2 + (\text{lon} - \text{lon}_i)^2$$
**Why**: With only 6 stations, finding the minimum takes $\approx 5$ microseconds ($0.005$ ms) in pure Python. It requires zero database indexing, zero GIS libraries, and zero network calls.
**Alternatives**: GeoPandas/PostGIS spatial queries — rejected as massive overkill for 6 static points.

### D2: Async background/lazy caching with 15-minute TTL
**Choice**: Store environmental data in an in-memory cache dict with a timestamp. When expired (or at startup), fetch fresh station indexes from GIOŚ and hourly forecast from Open-Meteo asynchronously using `httpx`.
**Why**: GIOŚ and Open-Meteo update data at most once an hour. A 15-minute TTL ensures fresh data while guaranteeing that user route requests never wait on external network calls.
**Alternatives**: Synchronous fetching on each request — rejected because GIOŚ API latency (400–1200 ms) would make route planning feel sluggish.

### D3: Health advisory classification (Nudge vs. Hard Lock)
**Choice**: Replace `locked: true` with a multi-level advisory:
- `SAFE` (green): Clean transit, short walks, or cycling in good air / dry weather.
- `MODERATE` (yellow): Short cycling ($\le 15$ min) under elevated smog ($50 < \text{PM10} \le 80$) or light rain ($0.1 < \text{rain} \le 0.5$ mm/h).
- `WARNING` (orange): Extended cycling ($> 15$ min) under elevated smog or rain, detailing why the route carries elevated exposure.
- `DANGER` (red): Cycling during severe smog alerts ($\text{PM10} > 80$) or extreme weather (storms, freezing rain).
`default_index` automatically targets the lowest-risk route (`SAFE`). All routes remain unlocked so users make informed decisions.
**Why**: Nudge theory and usability principles empower users while transparently communicating health risks.

### D4: Schema extensions
**Choice**:
- Extend `RouteResponse` with an optional `environment: EnvironmentSummary` containing the nearest station name, PM10, PM2.5, AQI level, temperature, and weather condition.
- Add `advisory: HealthAdvisory` to `RoutePosition` with `level`, `badge`, `message`, and `factors`.
- Retain backwards compatibility for frontend consumers.

## Risks / Trade-offs

- **[Risk] GIOŚ API downtime or temporary network failure** → Mitigation: Service gracefully falls back to previous cached data or Kraków city-wide historical averages (PM10 = 25 µg/m³), logging a warning without breaking route planning.
- **[Risk] Open-Meteo downtime** → Mitigation: If unavailable, weather condition defaults to neutral ("clear") and routing continues uninterrupted.
