"""End-to-end test of the quick GA pipeline against a live OTP instance.

Skipped (not errored) when OTP does not answer. The OTP endpoint can be overridden
with the OTP_URL environment variable (e.g. OTP_URL=http://localhost:1/x to force
a skip). All outputs and the OTP cache go to a temporary directory, so
optimizer/cache and optimizer/out stay untouched.

Run:
    python3 -m unittest optimizer.tests.test_integration_otp -v
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.request

from optimizer import run_ga
from optimizer.evaluate import DEFAULT_URL, build_payload, load_od_pairs
from optimizer.slider import sorted_front

OTP_URL = os.environ.get("OTP_URL", DEFAULT_URL)
PING_TIMEOUT = 3  # seconds
TIME_LIMIT = 180  # seconds for the whole quick pipeline


def _post(url, payload, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def otp_available(url=OTP_URL):
    """True if OTP answers a trivial GraphQL query within PING_TIMEOUT."""
    try:
        data = _post(url, {"query": "{ serviceTimeRange { start } }"}, PING_TIMEOUT)
        return bool((data.get("data") or {}).get("serviceTimeRange"))
    except Exception:  # connection refused, timeout, bad JSON, HTTP error ...
        return False


def _dominates(a, b):
    ta, ka = a["f_time_ratio"], a["active_kcal"]
    tb, kb = b["f_time_ratio"], b["active_kcal"]
    return ta <= tb and ka >= kb and (ta < tb or ka > kb)


class QuickPipelineTest(unittest.TestCase):
    """Runs `run_ga --mode quick --seed 1` once and checks every output."""

    @classmethod
    def setUpClass(cls):
        if not otp_available():
            raise unittest.SkipTest(f"OTP not reachable at {OTP_URL}")
        cls.tmp = tempfile.mkdtemp(prefix="ga_quick_")
        cls.out = os.path.join(cls.tmp, "out")
        argv = ["--mode", "quick", "--seed", "1", "--out", cls.out,
                "--cache", os.path.join(cls.tmp, "c.jsonl"), "--url", OTP_URL]
        log = io.StringIO()
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            cls.rc = run_ga.main(argv)
        cls.elapsed = time.perf_counter() - t0
        cls.log = log.getvalue()
        print(f"\n[integration] quick pipeline: rc={cls.rc}, {cls.elapsed:.1f} s", flush=True)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "tmp", None):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def _load(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            return json.load(f)

    def test_exit_code_and_time(self):
        self.assertEqual(self.rc, 0, self.log[-2000:])
        self.assertLess(self.elapsed, TIME_LIMIT)

    def test_front(self):
        front = self._load("front.json")["front"]
        self.assertGreater(len(front), 0)
        for p in front:
            self.assertEqual(p["cv"], 0, p)
            for k in ("query", "f_time_ratio", "active_kcal", "steps", "duration_min"):
                self.assertIn(k, p)
        for p in front:
            for q in front:
                if q is not p:
                    self.assertFalse(_dominates(q, p), (q["f_time_ratio"], q["active_kcal"],
                                                        p["f_time_ratio"], p["active_kcal"]))

    def test_profiles(self):
        prof = self._load("profiles.json")
        self.assertEqual(set(prof), {"fast", "balanced", "active"})
        for key, p in prof.items():
            for field in ("modes", "preferences", "metrics"):
                self.assertIsNotNone(p.get(field), f"{key}.{field}")
        m = [prof[k]["metrics"] for k in ("fast", "balanced", "active")]
        self.assertLessEqual(m[0]["f_time_ratio"], m[1]["f_time_ratio"])
        self.assertLessEqual(m[1]["f_time_ratio"], m[2]["f_time_ratio"])
        self.assertLessEqual(m[0]["active_kcal"], m[1]["active_kcal"])
        self.assertLessEqual(m[1]["active_kcal"], m[2]["active_kcal"])

    def test_report_files(self):
        for name in ("front.svg", "front.md", "checkpoint.json", "slider.json"):
            path = os.path.join(self.out, name)
            self.assertTrue(os.path.isfile(path), name)
            self.assertGreater(os.path.getsize(path), 0, name)

    def test_slider(self):
        doc = self._load("slider.json")
        self.assertEqual(set(doc), {"meta", "ticks"})
        m = doc["meta"]
        for k in ("variant", "n", "f1", "f2", "distinct", "source", "generated", "feasible_front"):
            self.assertIn(k, m)
        self.assertEqual(m["variant"], "bike")
        self.assertEqual((m["f1"], m["f2"]), ("f_time_ratio", "active_kcal"))
        self.assertTrue(m["feasible_front"])
        self.assertEqual(m["n"], 7)
        self.assertEqual(len(doc["ticks"]), 7)
        ordered = sorted_front(self._load("front.json")["front"])
        prev = None
        for i, t in enumerate(doc["ticks"]):
            for k in ("s", "u", "index", "modes", "preferences", "metrics"):
                self.assertIn(k, t)
            self.assertAlmostEqual(t["s"], i / 6)
            p = ordered[t["index"]]
            self.assertEqual(t["modes"], p["query"]["modes"])
            self.assertEqual(t["preferences"], p["query"]["preferences"])
            if prev is not None:
                self.assertGreaterEqual(t["metrics"]["f_time_ratio"], prev["f_time_ratio"])
                self.assertGreaterEqual(t["metrics"]["active_kcal"], prev["active_kcal"])
            prev = t["metrics"]
        self.assertEqual(m["distinct"], len({t["index"] for t in doc["ticks"]}))
        prof = self._load("profiles.json")
        self.assertEqual(prof["fast"]["preferences"], doc["ticks"][0]["preferences"])
        self.assertEqual(prof["active"]["preferences"], doc["ticks"][-1]["preferences"])
        with open(os.path.join(self.out, "front.svg"), encoding="utf-8") as f:
            self.assertEqual(f.read().count('class="tick"'), 7)

    def test_meta_anchor(self):
        meta = self._load("front.json")["meta"]
        self.assertEqual(meta["variant"], "bike")
        self.assertEqual(meta["dedupe_decimals"], 6)
        anchor = meta["anchor"]
        self.assertIsNotNone(anchor)
        self.assertIsInstance(anchor["in_front"], bool)
        # the short pair (rynek_agh) loses to walking: the anchor must use the fallback, not cv=60
        for pp in anchor["per_pair"]:
            self.assertTrue(pp["found"], pp)
        self.assertLess(anchor["cv"], 1.0)

    def test_active_profile_in_live_query(self):
        prof = self._load("profiles.json")["active"]
        pair = next(p for p in load_od_pairs(run_ga.DEFAULT_OD_PAIRS) if p["id"] == "nowa_huta_agh")
        payload = build_payload(pair["from"], pair["to"], prof["modes"], prof["preferences"])
        data = _post(OTP_URL, payload, 60)
        self.assertNotIn("errors", data, data.get("errors"))
        plan = data["data"]["planConnection"]
        self.assertEqual(plan["routingErrors"], [])
        self.assertGreaterEqual(len(plan["edges"]), 1)


if __name__ == "__main__":
    unittest.main()
