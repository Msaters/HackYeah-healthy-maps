import unittest
from unittest.mock import patch, MagicMock

from backend.app.service import evaluate_health_advisory, plan_routes


class TestHealthAdvisory(unittest.TestCase):
    def test_advisory_under_clean_air(self):
        positions = [
            {
                "s": 0.5,
                "metrics": {"modes": ["BICYCLE"]},
                "itinerary": {"legs": [{"mode": "BICYCLE", "duration": 1200}]},  # 20 min
            }
        ]
        env_context = {
            "station": {"name": "Kraków, Al. Krasińskiego", "id": 400, "distance_km": 1.2},
            "air_quality": {"index_name": "Bardzo dobry", "pm10": 15.0, "pm25": 10.0},
            "weather": {"temperature_c": 18.0, "rain_mm": 0.0, "condition": "Bezchmurnie"},
        }
        updated, summary = evaluate_health_advisory(positions, env_context)
        self.assertEqual(summary["overall_level"], "SAFE")
        self.assertEqual(updated[0]["advisory"]["level"], "SAFE")
        self.assertFalse(updated[0]["locked"])

    def test_advisory_under_moderate_smog(self):
        positions = [
            {
                "s": 0.0,
                "metrics": {"modes": ["WALK", "TRAM"]},
                "itinerary": {"legs": [{"mode": "WALK", "duration": 300}, {"mode": "TRAM", "duration": 900}]},
            },
            {
                "s": 0.3,
                "metrics": {"modes": ["BICYCLE"]},
                "itinerary": {"legs": [{"mode": "BICYCLE", "duration": 600}]},  # 10 min <= 15 min
            },
            {
                "s": 1.0,
                "metrics": {"modes": ["BICYCLE"]},
                "itinerary": {"legs": [{"mode": "BICYCLE", "duration": 1800}]},  # 30 min > 15 min
            },
        ]
        env_context = {
            "station": {"name": "Kraków, Al. Krasińskiego", "id": 400, "distance_km": 0.8},
            "air_quality": {"index_name": "Umiarkowany", "pm10": 62.0, "pm25": 40.0},
            "weather": {"temperature_c": 12.0, "rain_mm": 0.0, "condition": "Pochmurno"},
        }

        updated, summary = evaluate_health_advisory(positions, env_context, limit_min=15.0)
        self.assertEqual(summary["overall_level"], "WARNING")

        # 1. Transit is SAFE
        self.assertEqual(updated[0]["advisory"]["level"], "SAFE")
        self.assertFalse(updated[0]["locked"])

        # 2. Short bike is MODERATE (accessible, badge "Krótka ekspozycja")
        self.assertEqual(updated[1]["advisory"]["level"], "MODERATE")
        self.assertEqual(updated[1]["advisory"]["badge"], "Krótka ekspozycja")
        self.assertFalse(updated[1]["locked"])

        # 3. Long bike is WARNING (accessible, but with health warning factors)
        self.assertEqual(updated[2]["advisory"]["level"], "WARNING")
        self.assertEqual(updated[2]["advisory"]["badge"], "Wysoka ekspozycja")
        self.assertFalse(updated[2]["locked"])  # Retains user choice!
        self.assertTrue(len(updated[2]["advisory"]["factors"]) >= 2)

    def test_advisory_under_severe_smog(self):
        positions = [
            {
                "s": 1.0,
                "metrics": {"modes": ["BICYCLE"]},
                "itinerary": {"legs": [{"mode": "BICYCLE", "duration": 1200}]},
            }
        ]
        env_context = {
            "station": {"name": "Kraków, ul. Dietla", "id": 402, "distance_km": 1.0},
            "air_quality": {"index_name": "Bardzo zły", "pm10": 110.0, "pm25": 80.0},
            "weather": {"temperature_c": 8.0, "rain_mm": 0.0, "condition": "Pochmurno"},
        }
        updated, summary = evaluate_health_advisory(positions, env_context)
        self.assertEqual(summary["overall_level"], "DANGER")
        self.assertEqual(updated[0]["advisory"]["level"], "DANGER")
        self.assertFalse(updated[0]["locked"])


class TestPlanRoutesWithAdvisory(unittest.IsolatedAsyncioTestCase):
    @patch("backend.app.service.get_environmental_context")
    @patch("backend.app.service.plan_route_slider")
    async def test_plan_routes_smart_default(self, mock_plan_route_slider, mock_get_env):
        mock_get_env.return_value = {
            "station": {"name": "Kraków, Al. Krasińskiego", "id": 400, "distance_km": 0.5},
            "air_quality": {"index_name": "Zły", "pm10": 70.0, "pm25": 45.0},
            "weather": {"temperature_c": 10.0, "rain_mm": 0.0, "condition": "Pochmurno"},
        }
        mock_plan_route_slider.return_value = {
            "baseline_min": 25.0,
            "default_index": 2,  # Suppose raw OTP picked the bike route
            "positions": [
                {
                    "s": 0.0,
                    "metrics": {"modes": ["TRAM"]},
                    "itinerary": {"legs": [{"mode": "TRAM", "duration": 1200}]},
                },
                {
                    "s": 1.0,
                    "metrics": {"modes": ["BICYCLE"]},
                    "itinerary": {"legs": [{"mode": "BICYCLE", "duration": 1800}]},
                },
            ],
        }

        rs = await plan_routes(
            origin={"lat": 50.0614, "lon": 19.9383},
            destination={"lat": 50.0678, "lon": 19.9126},
            deadline="2026-10-05T08:30:00+02:00",
        )

        # Smart default should steer to index 0 (the safe transit route)
        self.assertEqual(rs["default_index"], 0)
        self.assertIn("environment", rs)
        self.assertEqual(rs["positions"][0]["advisory"]["level"], "SAFE")
        self.assertEqual(rs["positions"][1]["advisory"]["level"], "WARNING")


if __name__ == "__main__":
    unittest.main()
