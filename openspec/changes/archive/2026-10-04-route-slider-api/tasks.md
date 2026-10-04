# Tasks

## 1. Backend Project Scaffolding

- [x] 1.1 Create `backend/` directory structure (`backend/app/`, `backend/tests/`) and `backend/requirements.txt` with `fastapi`, `uvicorn[standard]`, and `pydantic`. Verify file creation.
- [x] 1.2 Install backend dependencies and verify that FastAPI and Pydantic import without errors.

## 2. Configuration & Preset Loader

- [x] 2.1 Implement `backend/app/config.py` defining settings for OTP URL (`http://localhost:8080/otp/gtfs/v1`), slider preset paths, and outdoor exposure limit (15.0 minutes).
- [x] 2.2 Implement preset loader in `backend/app/service.py` that loads and caches `slider.json` for `bike` and `walk` variants, providing fallback default presets if disk files are missing. Verify with a unit test.

## 3. Schemas & Outdoor Exposure Logic

- [x] 3.1 Implement Pydantic models in `backend/app/schemas.py` for `RouteRequest` and `RouteResponse` with coordinates, ISO deadline, `has_bike`, optional user profile, and `lock_reason`. Verify schema validation with valid and invalid inputs.
- [x] 3.2 Implement outdoor exposure rule in `backend/app/service.py`: when `lock_reason` is set, calculate cycling duration per position and set `locked = True` if bike duration > 15.0 minutes, keeping transit/walk fallback unlocked. Verify with a unit test.

## 4. Endpoint Implementation & Testing

- [x] 4.1 Implement `POST /api/routes` in `backend/app/main.py` calling `plan_route_slider()`, attaching exposure evaluation, and returning formatted slider positions.
- [x] 4.2 Add FastAPI CORS middleware to allow requests from local frontend development servers (`http://localhost:5173`, `http://localhost:3000`).
- [x] 4.3 Implement API tests in `backend/tests/test_api.py` using `TestClient` (with mocked or live OTP) verifying response structure, 15-minute lock behavior, and user profile parameters. Verify all tests pass.
