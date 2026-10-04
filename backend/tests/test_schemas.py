import unittest
from datetime import datetime
from pydantic import ValidationError

from backend.app.schemas import (
    RouteRequest,
    RouteResponse,
    HealthAdvisory,
    EnvironmentSummary,
    AirQualityInfo,
    WeatherInfo,
)


class TestSchemas(unittest.TestCase):
    def test_valid_request(self):
        req_data = {
            "from": {"lat": 50.0614, "lon": 19.9383},
            "to": {"lat": 50.0678, "lon": 19.9126},
            "deadline": "2026-10-05T08:30:00+02:00",
            "has_bike": True,
            "user_profile": {"weight_kg": 75.0, "height_m": 1.80},
            "lock_reason": "auto",
        }
        req = RouteRequest.model_validate(req_data)
        self.assertEqual(req.from_loc.lat, 50.0614)
        self.assertEqual(req.to_loc.lon, 19.9126)
        self.assertTrue(req.has_bike)
        self.assertEqual(req.lock_reason, "auto")

    def test_invalid_lat_lon(self):
        req_data = {
            "from": {"lat": 95.0, "lon": 19.9383},
            "to": {"lat": 50.0678, "lon": 19.9126},
            "deadline": "2026-10-05T08:30:00+02:00",
        }
        with self.assertRaises(ValidationError):
            RouteRequest.model_validate(req_data)

    def test_valid_response_with_advisory_and_environment(self):
        resp_data = {
            "baseline_min": 25.0,
            "default_index": 0,
            "environment": {
                "overall_level": "WARNING",
                "summary": "Podwyższone stężenie pyłu PM10 w centrum Krakowa.",
                "air_quality": {
                    "station_name": "Kraków, Al. Krasińskiego",
                    "station_id": 400,
                    "distance_km": 0.8,
                    "index_name": "Zły",
                    "pm10": 65.0,
                    "pm25": 42.0,
                },
                "weather": {
                    "temperature_c": 11.0,
                    "rain_mm": 0.0,
                    "precipitation_mm": 0.0,
                    "condition": "Bezchmurnie",
                    "wind_kmh": 14.0,
                },
            },
            "positions": [
                {
                    "s": 0.0,
                    "locked": False,
                    "advisory": {
                        "level": "SAFE",
                        "badge": "Czysty przejazd",
                        "message": "Trasa w pojeździe (tramwaj) chroni przed zanieczyszczeniami.",
                        "factors": [],
                        "affected_legs": [],
                    },
                    "metrics": {
                        "duration_min": 25.0,
                        "active_kcal": 45.0,
                        "steps": 1200,
                        "bike_duration_min": 0.0,
                        "modes": ["WALK", "TRAM"],
                    },
                    "itinerary": {"legs": []},
                },
                {
                    "s": 1.0,
                    "locked": False,
                    "advisory": {
                        "level": "WARNING",
                        "badge": "Wysoka ekspozycja na smog",
                        "message": "35 min jazdy na rowerze przy PM10 = 65 µg/m³.",
                        "factors": ["Czas jazdy na rowerze > 15 min", "Stacja Al. Krasińskiego: indeks Zły"],
                        "affected_legs": ["BICYCLE"],
                    },
                    "metrics": {
                        "duration_min": 35.0,
                        "active_kcal": 260.0,
                        "steps": 0,
                        "bike_duration_min": 35.0,
                        "modes": ["BICYCLE"],
                    },
                    "itinerary": {"legs": []},
                },
            ],
            "warnings": [],
        }

        resp = RouteResponse.model_validate(resp_data)
        self.assertEqual(resp.baseline_min, 25.0)
        self.assertIsNotNone(resp.environment)
        self.assertEqual(resp.environment.overall_level, "WARNING")
        self.assertEqual(resp.positions[0].advisory.level, "SAFE")
        self.assertEqual(resp.positions[1].advisory.level, "WARNING")
        self.assertFalse(resp.positions[1].locked)  # Remains selectable!


if __name__ == "__main__":
    unittest.main()
