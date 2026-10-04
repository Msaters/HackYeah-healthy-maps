# route-slider-api Specification

## Purpose
Provides an HTTP REST API endpoint `POST /api/routes` that returns health-aware, multi-modal Pareto route slider positions between coordinates in Kraków, integrating GA weight presets, transit baselines, user health parameters, and environmental exposure safety.

## Requirements

### Requirement: Route planning request validation
The system SHALL expose `POST /api/routes` accepting origin and destination coordinates, an ISO 8601 arrival deadline, a boolean bike availability flag, an optional user profile, and an optional environmental lock reason.

#### Scenario: Valid request with defaults
- **WHEN** client sends a POST request with valid `from`, `to`, `deadline`, and `has_bike: true` without profile
- **THEN** system responds with HTTP 200 using default physical parameters (70.0 kg, 1.75 m)

#### Scenario: Request with customized profile
- **WHEN** client sends custom `weight_kg: 85.0`, `height_m: 1.82`, and `walk_speed_mps: 1.4`
- **THEN** system computes MET calories and walking duration tailored to those physical metrics

#### Scenario: Invalid coordinates or missing deadline
- **WHEN** client sends out-of-range coordinates or missing arrival deadline
- **THEN** system responds with HTTP 422 Unprocessable Entity describing the validation error

### Requirement: Multi-modal slider calculation via GA presets
The system SHALL evaluate routes by querying the OTP engine using the pre-computed GA slider profile corresponding to `has_bike`, deduplicating identical itineraries and sorting non-dominated routes along a monotonic slider coordinate $s \in [0, 1]$.

#### Scenario: Bike variant query
- **WHEN** client queries with `has_bike: true`
- **THEN** system loads the `bike` slider profile and returns positions spanning from fastest transit to maximum cycling activity

#### Scenario: Walk-only variant query
- **WHEN** client queries with `has_bike: false`
- **THEN** system loads the `walk` slider profile and returns positions excluding personal bicycle legs

### Requirement: Outdoor exposure safety threshold
The system SHALL evaluate outdoor bicycle duration against environmental conditions (real-time GIOŚ air quality and Open-Meteo forecast) and attach an advisory health assessment (`advisory` with levels `SAFE`, `MODERATE`, `WARNING`, `DANGER`), keeping routes selectable while setting `default_index` to the cleanest option.

#### Scenario: Long cycling route locked under smog
- **WHEN** PM10 at nearest station exceeds 50 µg/m³ (or lock_reason is "smog") and an itinerary has >15 minutes of bicycle travel
- **THEN** the position remains selectable (`locked: false`), receives advisory level `WARNING` or `DANGER`, a warning badge, and an explanation citing PM10 levels and exposure duration

#### Scenario: Short cycling route permitted under smog
- **WHEN** smog is elevated but an itinerary has $\le 15$ minutes of bicycle travel
- **THEN** the position has advisory level `SAFE` or `MODERATE` with a badge indicating short, acceptable exposure

#### Scenario: Transit fallback guaranteed
- **WHEN** air quality is poor or heavy rain is forecast
- **THEN** `default_index` automatically selects the lowest-risk public transit or pedestrian fallback route

### Requirement: Route response format with UI geometry
The response SHALL include all fields needed for map rendering and route comparison, including slider index $s$, health and time metrics, baseline transit duration, smart default index, top-level `environment` summary, and leg-by-leg encoded polyline geometry.

#### Scenario: Complete geometry and metrics payload
- **WHEN** a routing request succeeds
- **THEN** response contains `baseline_min`, `default_index`, `environment` (with nearest station name, PM10/PM2.5, temperature, weather summary), and a `positions` array where each element contains `s`, `advisory`, `metrics`, and `itinerary.legs` with `legGeometry.points`

### Requirement: Real-time environmental data caching
The system SHALL poll air quality from GIOŚ monitoring stations in Kraków and weather from Open-Meteo, caching records in memory with a 15–20 minute TTL and matching the nearest monitoring station spatially in under 1 millisecond.

#### Scenario: Cached nearest station lookup
- **WHEN** a route request arrives for coordinates near Al. Krasińskiego
- **THEN** system retrieves air quality from the in-memory cache for station ID 400 without making blocking external HTTP calls during the request

