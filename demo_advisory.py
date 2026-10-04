"""
Interactive Demonstration of Aktywny Kraków Environmental Health Advisory System.
Demonstrates:
1. Real-time GIOŚ air quality polling & Open-Meteo weather with <1ms caching.
2. Nearest station Euclidean matching across Kraków districts.
3. Transparent Health Advisory Nudge Model (SAFE / MODERATE / WARNING / DANGER).
4. Smart default_index route steering.
5. End-to-end FastAPI endpoint response structure.
"""
import asyncio
import json
import time
from unittest.mock import patch

from backend.app.environment import (
    GIOS_STATIONS,
    find_nearest_station,
    get_environmental_context,
    clear_environment_cache,
)
from backend.app.service import evaluate_health_advisory
from fastapi.testclient import TestClient
from backend.app.main import app

SEPARATOR = "=" * 70
SUBSEP = "-" * 70


def print_header(title: str):
    print("\n" + SEPARATOR)
    print(f"  {title.upper()}")
    print(SEPARATOR)


async def demo_environmental_intelligence():
    print_header("1. Real-time Kraków Environmental Polling (GIOŚ & Open-Meteo)")
    clear_environment_cache()

    locations = [
        ("Rynek Główny (Centrum)", 50.0614, 19.9366),
        ("Kurdwanów (Południe)", 50.0120, 19.9500),
        ("Nowa Huta (Wschód)", 50.0820, 20.1200),
    ]

    arrival_time = "2026-10-04T08:00:00"

    for name, lat, lon in locations:
        st_match = find_nearest_station(lat, lon)
        print(f"\n📍 Lokalizacja: {name} ({lat}, {lon})")
        print(f"   -> Najbliższa stacja GIOŚ: [{st_match['id']}] {st_match['name']} ({st_match['type']})")
        print(f"   -> Obliczony dystans:      {st_match['distance_km']} km")

    # Measure cold fetch vs warm cache
    print("\n" + SUBSEP)
    print("⚡ Badanie czasu odpowiedzi (Cold fetch vs Warm cache):")
    
    t0 = time.perf_counter()
    env_cold = await get_environmental_context(50.0614, 19.9366, arrival_time)
    cold_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    env_warm = await get_environmental_context(50.0614, 19.9366, arrival_time)
    warm_ms = (time.perf_counter() - t1) * 1000.0

    print(f"   • Cold fetch (Live HTTP z GIOŚ + Open-Meteo): {cold_ms:.2f} ms")
    print(f"   • Warm cache (In-memory TTL cache):          {warm_ms:.3f} ms  (zgodnie ze specyfikacją < 1 ms!)")

    aq = env_cold["air_quality"]
    w = env_cold["weather"]
    print("\n🌱 Aktualne dane ze stacji GIOŚ i prognoza Open-Meteo dla centrum Krakowa:")
    print(f"   • Źródło GIOŚ:       {aq['source']} (Kategoria: {aq['index_name']}, PM10: {aq['pm10']} µg/m³, PM2.5: {aq['pm25']} µg/m³)")
    print(f"   • Pogoda Open-Meteo: {w['temperature_c']}°C, {w['condition']}, Deszcz: {w['rain_mm']} mm, Wiatr: {w['wind_kmh']} km/h")


def demo_advisory_scenarios():
    print_header("2. Transparent Health Advisory Nudge Model & Smart Steering")

    sample_positions = [
        {
            "s": 0.0,
            "fallback": True,
            "metrics": {"duration_s": 1200, "modes": ["WALK", "TRAM"]},
            "itinerary": {
                "duration": 1200,
                "legs": [
                    {"mode": "WALK", "duration": 240},
                    {"mode": "TRAM", "duration": 960},
                ],
            },
        },
        {
            "s": 0.5,
            "fallback": False,
            "metrics": {"duration_s": 900, "modes": ["BICYCLE", "TRAM"]},
            "itinerary": {
                "duration": 900,
                "legs": [
                    {"mode": "BICYCLE", "duration": 480},  # 8 min bike
                    {"mode": "TRAM", "duration": 420},
                ],
            },
        },
        {
            "s": 1.0,
            "fallback": False,
            "metrics": {"duration_s": 1500, "modes": ["BICYCLE"]},
            "itinerary": {
                "duration": 1500,
                "legs": [
                    {"mode": "BICYCLE", "duration": 1500},  # 25 min bike
                ],
            },
        },
    ]

    scenarios = [
        (
            "SCENARIUSZ A: Czyste powietrze (Typowy dobry dzień)",
            {
                "station": {"name": "Kraków, Al. Krasińskiego", "id": 400, "distance_km": 0.8},
                "air_quality": {"index_name": "Bardzo dobry", "pm10": 15.0, "pm25": 10.0},
                "weather": {"temperature_c": 18.0, "rain_mm": 0.0, "precipitation_mm": 0.0, "condition": "Bezchmurnie", "wind_kmh": 8.0, "weather_code": 0},
            },
        ),
        (
            "SCENARIUSZ B: Smog / Zła jakość powietrza (PM10 = 95 µg/m³)",
            {
                "station": {"name": "Kraków, ul. Dietla", "id": 402, "distance_km": 1.1},
                "air_quality": {"index_name": "Dostateczny", "pm10": 95.0, "pm25": 62.0},
                "weather": {"temperature_c": 6.0, "rain_mm": 0.0, "precipitation_mm": 0.0, "condition": "Mgła", "wind_kmh": 3.0, "weather_code": 45},
            },
        ),
        (
            "SCENARIUSZ C: Trudne warunki pogodowe (Ulewa i burza)",
            {
                "station": {"name": "Kraków, Al. Krasińskiego", "id": 400, "distance_km": 0.8},
                "air_quality": {"index_name": "Dobry", "pm10": 20.0, "pm25": 13.0},
                "weather": {"temperature_c": 12.0, "rain_mm": 4.5, "precipitation_mm": 4.5, "condition": "Ulewny deszcz", "wind_kmh": 32.0, "weather_code": 65},
            },
        ),
    ]

    for title, env in scenarios:
        import copy
        pos_copy = copy.deepcopy(sample_positions)
        eval_pos, env_sum = evaluate_health_advisory(pos_copy, env_context=env, limit_min=15.0)

        # Smart default selection
        safe_indices = [i for i, p in enumerate(eval_pos) if p["advisory"]["level"] in ("SAFE", "MODERATE")]
        default_idx = safe_indices[0] if safe_indices else 0

        print(f"\n{title}")
        print(f"   Status ogólny: [{env_sum['overall_level']}] - {env_sum['summary']}")
        print(f"   Sugerowany domyślny wybór suwaka (default_index): {default_idx} (pozycja: s={eval_pos[default_idx]['s']})")
        print("   Opcje suwaka:")

        for i, p in enumerate(eval_pos):
            adv = p["advisory"]
            bike_m = p["metrics"]["bike_duration_min"]
            is_def = "👉 [DOMYŚLNA]" if i == default_idx else "  "
            print(f"     {is_def} Pozycja #{i} (s={p['s']}, Rower: {bike_m:.0f} min, locked={p['locked']}):")
            print(f"        Poziom: [{adv['level']}] | Odznaka: '{adv['badge']}'")
            print(f"        Komunikat: {adv['message']}")
            if adv['factors']:
                print(f"        Czynniki: {', '.join(adv['factors'])}")


def demo_fastapi_request():
    print_header("3. End-to-End FastAPI /api/routes Endpoint")

    client = TestClient(app)

    # Health check
    resp_health = client.get("/api/health")
    print("GET /api/health ->", resp_health.json())

    # Mock OTP return so endpoint can be tested without a local Java OTP service running
    mock_otp_slider_result = {
        "variant": "bike",
        "baseline_min": 20.0,
        "default_index": 0,
        "dropped": {"error": 0},
        "n_requests": 2,
        "warnings": [],
        "positions": [
            {
                "s": 0.0,
                "fallback": True,
                "sources": ["anchor"],
                "metrics": {
                    "duration_min": 20.0,
                    "active_kcal": 35.0,
                    "steps": 800,
                    "modes": ["WALK", "TRAM"],
                },
                "itinerary": {
                    "duration": 1200,
                    "legs": [
                        {"mode": "WALK", "duration": 240, "distance": 300, "legGeometry": {"points": "mock_poly_walk"}},
                        {"mode": "TRAM", "duration": 960, "distance": 3500, "legGeometry": {"points": "mock_poly_tram"}},
                    ],
                },
            },
            {
                "s": 1.0,
                "fallback": False,
                "sources": ["tick:1"],
                "metrics": {
                    "duration_min": 22.0,
                    "active_kcal": 180.0,
                    "steps": 0,
                    "modes": ["BICYCLE"],
                },
                "itinerary": {
                    "duration": 1320,
                    "legs": [
                        {"mode": "BICYCLE", "duration": 1320, "distance": 6200, "legGeometry": {"points": "mock_poly_bike"}},
                    ],
                },
            },
        ],
    }

    req_payload = {
        "from": {"lat": 50.0614, "lon": 19.9366},
        "to": {"lat": 50.0820, "lon": 20.1200},
        "deadline": "2026-10-04T09:00:00+02:00",
        "has_bike": True,
        "user_profile": {"weight_kg": 75.0, "height_m": 1.80},
    }

    with patch("backend.app.service.plan_route_slider", return_value=mock_otp_slider_result):
        resp = client.post("/api/routes", json=req_payload)
        print(f"\nPOST /api/routes -> Status {resp.status_code}")
        data = resp.json()
        
        print("\nJSON Response Keys:", list(data.keys()))
        print(f"default_index: {data.get('default_index')}")
        print("Environment Summary:")
        print(json.dumps(data.get("environment"), indent=2, ensure_ascii=False))
        print(f"\nPositions count: {len(data.get('positions', []))}")
        for i, p in enumerate(data.get("positions", [])):
            print(f"  Position {i} (s={p['s']}): advisory badge='{p['advisory']['badge']}', level='{p['advisory']['level']}', locked={p['locked']}")


async def main():
    await demo_environmental_intelligence()
    demo_advisory_scenarios()
    demo_fastapi_request()
    print("\n" + SEPARATOR)
    print("  DEMO COMPLETED SUCCESSFULLY! ")
    print(SEPARATOR + "\n")


if __name__ == "__main__":
    asyncio.run(main())
