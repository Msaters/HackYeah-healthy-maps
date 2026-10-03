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
When `lock_reason` is specified, the system SHALL calculate the total outdoor bicycle duration for each position. If the cycling duration exceeds 15.0 minutes, the position SHALL be marked as locked with an explanatory note. If the cycling duration is 15.0 minutes or less, the position SHALL remain unlocked.

#### Scenario: Long cycling route locked under smog
- **WHEN** `lock_reason` is "smog" and an itinerary has 25 minutes of bicycle travel
- **THEN** the position has `locked: true` and includes a warning regarding smog exposure limit (15 min)

#### Scenario: Short cycling route permitted under smog
- **WHEN** `lock_reason` is "smog" and an itinerary has 8 minutes of bicycle travel
- **THEN** the position has `locked: false` and is directly selectable by the user

#### Scenario: Transit fallback guaranteed
- **WHEN** `lock_reason` is active and all cycling positions exceed 15 minutes
- **THEN** the default route (`default_index`) points to a non-cycling public transit or pedestrian fallback that is not locked

### Requirement: Route response format with UI geometry
The response SHALL include all fields needed for map rendering and route comparison, including slider index $s$, locked status, health and time metrics, baseline transit duration, default index, warnings, and leg-by-leg encoded polyline geometry.

#### Scenario: Complete geometry and metrics payload
- **WHEN** a routing request succeeds
- **THEN** response contains `baseline_min`, `default_index`, `lock_reason`, and a `positions` array where each element contains `s`, `locked`, `metrics` (with `duration_min`, `active_kcal`, `steps`, `bike_duration_min`), and `itinerary.legs` containing `legGeometry.points`
