import unittest
from backend.app.service import get_slider, clear_slider_cache, make_fallback_slider

class TestPresetService(unittest.TestCase):
    def setUp(self):
        clear_slider_cache()

    def test_fallback_bike_slider(self):
        slider = make_fallback_slider("bike", n=7)
        self.assertEqual(slider["meta"]["variant"], "bike")
        self.assertEqual(len(slider["ticks"]), 7)
        for i, t in enumerate(slider["ticks"]):
            self.assertIn("s", t)
            self.assertIn("modes", t)
            self.assertIn("preferences", t)

    def test_fallback_walk_slider(self):
        slider = make_fallback_slider("walk", n=7)
        self.assertEqual(slider["meta"]["variant"], "walk")
        self.assertEqual(len(slider["ticks"]), 7)
        for t in slider["ticks"]:
            # walk variant should never contain BICYCLE in modes
            modes_str = str(t.get("modes") or {})
            self.assertNotIn("BICYCLE", modes_str)

    def test_caching(self):
        s1 = get_slider("bike")
        s2 = get_slider("bike")
        self.assertIs(s1, s2)
        s_walk = get_slider("walk")
        self.assertIsNot(s1, s_walk)

if __name__ == "__main__":
    unittest.main()
