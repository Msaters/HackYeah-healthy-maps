import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


class TestRouteApi(unittest.TestCase):
    def test_health_check(self):
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")

    def test_cors_headers(self):
        resp = client.options(
            "/api/routes",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access-control-allow-origin", resp.headers)

    def test_validation_missing_fields(self):
        resp = client.post("/api/routes", json={})
        self.assertEqual(resp.status_code, 422)

    @patch("backend.app.service.get_environmental_context")
    @patch("backend.app.service.plan_route_slider")
    def test_routes_endpoint_with_health_advisory(self, mock_plan_route_slider, mock_get_env):
        # Mock environmental context (smoggy Kraków day near Krasińskiego)
        mock_get_env.return_value = {
            "station": {
                "name": "Kraków, Al. Krasińskiego",
                "id": 400,
                "distance_km": 0.6,
            },
            "air_quality": {
                "index_name": "Zły",
                "pm10": 68.0,
                "pm25": 44.0,
                "source": "GIOS_MOCK",
            },
            "weather": {
                "temperature_c": 11.0,
                "rain_mm": 0.0,
                "precipitation_mm": 0.0,
                "wind_kmh": 14.0,
                "condition": "Pochmurno",
                "weather_code": 3,
                "source": "OPEN_METEO_MOCK",
            },
        }

        mock_plan_route_slider.return_value = {
            "baseline_min": 25.0,
            "default_index": 0,
            "dropped": {"error": 0},
            "n_requests": 9,
            "warnings": [],
            "positions": [
                {
                    "s": 0.0,
                    "fallback": True,
                    "sources": ["anchor"],
                    "metrics": {
                        "duration_min": 25.0,
                        "active_kcal": 40.0,
                        "steps": 1000,
                        "modes": ["WALK", "TRAM"],
                    },
                    "itinerary": {
                        "legs": [
                            {
                                "mode": "WALK",
                                "duration": 300,
                                "distance": 400,
                                "legGeometry": {"points": "points_walk"},
                            },
                            {
                                "mode": "TRAM",
                                "duration": 1200,
                                "distance": 4000,
                                "legGeometry": {"points": "points_tram"},
                            },
                        ]
                    },
                },
                {
                    "s": 0.35,
                    "fallback": False,
                    "sources": ["tick:1"],
                    "metrics": {
                        "duration_min": 10.0,
                        "active_kcal": 55.0,
                        "steps": 0,
                        "modes": ["BICYCLE"],
                    },
                    "itinerary": {
                        "legs": [
                            {
                                "mode": "BICYCLE",
                                "duration": 480,  # 8 min <= 15 min
                                "distance": 2500,
                                "legGeometry": {"points": "points_bike_short"},
                            }
                        ]
                    },
                },
                {
                    "s": 1.0,
                    "fallback": False,
                    "sources": ["tick:6"],
                    "metrics": {
                        "duration_min": 35.0,
                        "active_kcal": 280.0,
                        "steps": 0,
                        "modes": ["BICYCLE"],
                    },
                    "itinerary": {
                        "legs": [
                            {
                                "mode": "BICYCLE",
                                "duration": 2100,  # 35 min > 15 min
                                "distance": 9000,
                                "legGeometry": {"points": "points_bike_long"},
                            }
                        ]
                    },
                },
            ],
        }

        payload = {
            "from": {"lat": 50.0614, "lon": 19.9383},
            "to": {"lat": 50.0678, "lon": 19.9126},
            "deadline": "2026-10-05T08:30:00+02:00",
            "has_bike": True,
            "user_profile": {
                "weight_kg": 72.0,
                "height_m": 1.78,
                "walk_speed_mps": 1.35,
            },
        }

        resp = client.post("/api/routes", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Check environmental summary
        self.assertIn("environment", data)
        env = data["environment"]
        self.assertEqual(env["overall_level"], "WARNING")
        self.assertEqual(env["air_quality"]["station_name"], "Kraków, Al. Krasińskiego")
        self.assertEqual(env["air_quality"]["pm10"], 68.0)
        self.assertEqual(env["weather"]["temperature_c"], 11.0)

        # Check positions & advisories
        self.assertEqual(len(data["positions"]), 3)
        self.assertEqual(data["default_index"], 0)  # Smart default steers to transit

        # 1. Transit route is SAFE and NOT locked
        pos0 = data["positions"][0]
        self.assertFalse(pos0["locked"])
        self.assertEqual(pos0["advisory"]["level"], "SAFE")
        self.assertEqual(pos0["advisory"]["badge"], "Czysty przejazd")

        # 2. Short bike ride (8 min <= 15 min) is MODERATE and selectable
        pos1 = data["positions"][1]
        self.assertFalse(pos1["locked"])
        self.assertEqual(pos1["advisory"]["level"], "MODERATE")
        self.assertEqual(pos1["advisory"]["badge"], "Krótka ekspozycja")

        # 3. Long bike ride (35 min > 15 min) is WARNING, selectable (locked: false), with detailed factors
        pos2 = data["positions"][2]
        self.assertFalse(pos2["locked"])  # Kept selectable in the advisory nudge model!
        self.assertEqual(pos2["advisory"]["level"], "WARNING")
        self.assertEqual(pos2["advisory"]["badge"], "Wysoka ekspozycja")
        self.assertTrue(len(pos2["advisory"]["factors"]) >= 2)

        # Check that user profile parameters were forwarded
        args, kwargs = mock_plan_route_slider.call_args
        self.assertEqual(kwargs["weight"], 72.0)
        self.assertEqual(kwargs["height"], 1.78)
        self.assertEqual(kwargs["walk_speed"], 1.35)

    @patch("backend.app.service.get_environmental_context")
    @patch("backend.app.service.plan_route_slider")
    def test_routes_endpoint_otp_error(self, mock_plan_route_slider, mock_get_env):
        mock_get_env.return_value = {}
        mock_plan_route_slider.return_value = {
            "n_requests": 9,
            "dropped": {"error": 9},
            "positions": [],
            "warnings": ["OTP down"],
        }
        payload = {
            "from": {"lat": 50.0614, "lon": 19.9383},
            "to": {"lat": 50.0678, "lon": 19.9126},
            "deadline": "2026-10-05T08:30:00+02:00",
        }
        resp = client.post("/api/routes", json=payload)
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
