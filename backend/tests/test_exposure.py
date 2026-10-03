import unittest
from backend.app.service import evaluate_outdoor_exposure

class TestOutdoorExposure(unittest.TestCase):
    def test_exposure_under_smog(self):
        positions = [
            {
                "s": 0.0,
                "fallback": True,
                "metrics": {"modes": ["WALK", "TRAM"]},
                "itinerary": {
                    "legs": [
                        {"mode": "WALK", "duration": 300},
                        {"mode": "TRAM", "duration": 900}
                    ]
                }
            },
            {
                "s": 0.3,
                "fallback": False,
                "metrics": {"modes": ["BICYCLE"]},
                "itinerary": {
                    "legs": [
                        {"mode": "BICYCLE", "duration": 480}  # 8 min <= 15 min
                    ]
                }
            },
            {
                "s": 1.0,
                "fallback": False,
                "metrics": {"modes": ["BICYCLE"]},
                "itinerary": {
                    "legs": [
                        {"mode": "BICYCLE", "duration": 1500}  # 25 min > 15 min
                    ]
                }
            }
        ]

        updated, warnings = evaluate_outdoor_exposure(positions, lock_reason="smog", limit_min=15.0)
        
        # 1. Fallback transit route remains unlocked
        self.assertFalse(updated[0]["locked"])
        self.assertEqual(updated[0]["metrics"]["bike_duration_min"], 0.0)

        # 2. Short bike ride (8 min <= 15 min) remains unlocked
        self.assertFalse(updated[1]["locked"])
        self.assertEqual(updated[1]["metrics"]["bike_duration_min"], 8.0)
        self.assertIsNone(updated[1]["lock_note"])

        # 3. Long bike ride (25 min > 15 min) is locked
        self.assertTrue(updated[2]["locked"])
        self.assertEqual(updated[2]["metrics"]["bike_duration_min"], 25.0)
        self.assertIn("Zablokowano (smog)", updated[2]["lock_note"])
        self.assertIn("15 min", updated[2]["lock_note"])

        # 4. Warnings contain smog notice
        self.assertTrue(any("alert (smog)" in w for w in warnings))

    def test_no_lock_reason_keeps_all_unlocked(self):
        positions = [
            {
                "s": 1.0,
                "fallback": False,
                "metrics": {"modes": ["BICYCLE"]},
                "itinerary": {
                    "legs": [
                        {"mode": "BICYCLE", "duration": 3600}  # 60 min
                    ]
                }
            }
        ]
        updated, warnings = evaluate_outdoor_exposure(positions, lock_reason=None, limit_min=15.0)
        self.assertFalse(updated[0]["locked"])
        self.assertEqual(len(warnings), 0)

if __name__ == "__main__":
    unittest.main()
