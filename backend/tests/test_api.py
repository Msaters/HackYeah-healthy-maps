import unittest
from unittest.mock import patch
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

    @patch("backend.app.service.plan_route_slider")
    def test_routes_endpoint_with_smog_lock(self, mock_plan_route_slider):
        mock_plan_route_slider.return_value = {
            "baseline_min": 25.0,
            "default_index": 0,
            "lock_reason": "smog",
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
            "lock_reason": "smog",
        }

        resp = client.post("/api/routes", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Check response structure
        self.assertEqual(data["baseline_min"], 25.0)
        self.assertEqual(data["default_index"], 0)
        self.assertEqual(len(data["positions"]), 3)

        # 1. Anchor / transit fallback is unlocked
        self.assertFalse(data["positions"][0]["locked"])
        self.assertEqual(data["positions"][0]["metrics"]["bike_duration_min"], 0.0)

        # 2. Short bike ride (8 min <= 15 min) remains UNLOCKED under smog
        self.assertFalse(data["positions"][1]["locked"])
        self.assertEqual(data["positions"][1]["metrics"]["bike_duration_min"], 8.0)
        self.assertIsNone(data["positions"][1]["lock_note"])

        # 3. Long bike ride (35 min > 15 min) is LOCKED under smog
        self.assertTrue(data["positions"][2]["locked"])
        self.assertEqual(data["positions"][2]["metrics"]["bike_duration_min"], 35.0)
        self.assertIn("Zablokowano (smog)", data["positions"][2]["lock_note"])

        # 4. Warnings include smog alert
        self.assertTrue(any("alert (smog)" in w for w in data["warnings"]))

        # Check mock args
        args, kwargs = mock_plan_route_slider.call_args
        self.assertEqual(kwargs["weight"], 72.0)
        self.assertEqual(kwargs["height"], 1.78)
        self.assertEqual(kwargs["walk_speed"], 1.35)

    @patch("backend.app.service.plan_route_slider")
    def test_routes_endpoint_otp_error(self, mock_plan_route_slider):
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
