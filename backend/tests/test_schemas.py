import unittest
from datetime import datetime, timezone
from pydantic import ValidationError

from backend.app.schemas import RouteRequest, RouteResponse, UserProfile, Coordinates

class TestSchemas(unittest.TestCase):
    def test_valid_request(self):
        req_data = {
            "from": {"lat": 50.0614, "lon": 19.9383},
            "to": {"lat": 50.0678, "lon": 19.9126},
            "deadline": "2026-10-05T08:30:00+02:00",
            "has_bike": True,
            "user_profile": {"weight_kg": 75.0, "height_m": 1.80},
            "lock_reason": "smog"
        }
        req = RouteRequest.model_validate(req_data)
        self.assertEqual(req.from_loc.lat, 50.0614)
        self.assertEqual(req.to_loc.lon, 19.9126)
        self.assertTrue(req.has_bike)
        self.assertIsNotNone(req.user_profile)
        self.assertEqual(req.user_profile.weight_kg, 75.0)
        self.assertEqual(req.lock_reason, "smog")

    def test_invalid_lat_lon(self):
        # lat > 90
        req_data = {
            "from": {"lat": 95.0, "lon": 19.9383},
            "to": {"lat": 50.0678, "lon": 19.9126},
            "deadline": "2026-10-05T08:30:00+02:00",
        }
        with self.assertRaises(ValidationError):
            RouteRequest.model_validate(req_data)

    def test_deadline_without_timezone(self):
        req_data = {
            "from": {"lat": 50.0614, "lon": 19.9383},
            "to": {"lat": 50.0678, "lon": 19.9126},
            "deadline": "2026-10-05T08:30:00",  # missing tz
        }
        with self.assertRaises(ValidationError):
            RouteRequest.model_validate(req_data)

    def test_valid_response(self):
        resp_data = {
            "baseline_min": 25.0,
            "default_index": 0,
            "lock_reason": "smog",
            "positions": [
                {
                    "s": 0.0,
                    "locked": False,
                    "metrics": {
                        "duration_min": 25.0,
                        "active_kcal": 50.0,
                        "steps": 1200,
                        "bike_duration_min": 0.0,
                        "modes": ["WALK", "TRAM"]
                    },
                    "itinerary": {"legs": []}
                }
            ],
            "warnings": ["Warning test"]
        }
        resp = RouteResponse.model_validate(resp_data)
        self.assertEqual(resp.baseline_min, 25.0)
        self.assertEqual(len(resp.positions), 1)
        self.assertFalse(resp.positions[0].locked)

if __name__ == "__main__":
    unittest.main()
