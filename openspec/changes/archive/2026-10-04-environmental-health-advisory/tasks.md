# Tasks

## 1. Environmental Data Service & Caching

- [x] 1.1 Implement `backend/app/environment.py` with static Kraków GIOŚ stations, Euclidean nearest-station spatial matching, and in-memory TTL caching. Verify nearest station calculation with unit tests in `backend/tests/test_environment.py`.
- [x] 1.2 Implement asynchronous polling for GIOŚ air quality and Open-Meteo weather forecast with graceful fallback on network error. Verify with unit tests in `backend/tests/test_environment.py` using mocked HTTP responses.

## 2. Schemas Update

- [x] 2.1 Update `backend/app/schemas.py` to define `HealthAdvisory` (level, badge, message, factors) and `EnvironmentSummary` (station, PM10, PM2.5, temp, weather), attaching them to `RoutePosition` and `RouteResponse`. Verify schema validation in `backend/tests/test_schemas.py`.

## 3. Advisory Nudge Evaluator & Service Integration

- [x] 3.1 Implement `evaluate_health_advisory()` in `backend/app/service.py` categorizing route options into `SAFE`, `MODERATE`, `WARNING`, and `DANGER` without hard locking (`locked = False`), detailing affected legs and health rationale. Verify with unit tests in `backend/tests/test_advisory.py`.
- [x] 3.2 Update `plan_routes()` in `backend/app/service.py` to automatically retrieve environmental data, attach advisories, and steer `default_index` to the lowest-risk route. Verify with unit tests.

## 4. API Integration & Verification

- [x] 4.1 Update `POST /api/routes` in `backend/app/main.py` to return the top-level `environment` summary and position advisories.
- [x] 4.2 Update and execute `backend/tests/test_api.py` ensuring complete payload validation and confirming all test suites pass.
