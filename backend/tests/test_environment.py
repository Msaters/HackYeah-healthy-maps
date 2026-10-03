import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from backend.app.environment import (
    find_nearest_station,
    clear_environment_cache,
    fetch_gios_air_quality,
    fetch_open_meteo_weather,
    get_environmental_context,
)


class TestEnvironmentService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_environment_cache()

    def test_nearest_station_krasinskiego(self):
        station = find_nearest_station(50.064, 19.924)
        self.assertEqual(station["id"], 400)
        self.assertIn("Krasińskiego", station["name"])
        self.assertLess(station["distance_km"], 2.0)

    def test_nearest_station_kurdwanow(self):
        station = find_nearest_station(50.015, 19.952)
        self.assertEqual(station["id"], 401)
        self.assertIn("Bujaka", station["name"])
        self.assertLess(station["distance_km"], 1.5)

    def test_nearest_station_bronowice(self):
        station = find_nearest_station(50.083, 19.892)
        self.assertEqual(station["id"], 10139)
        self.assertIn("Złoty Róg", station["name"])
        self.assertLess(station["distance_km"], 1.0)

    async def test_fetch_gios_air_quality_mocked(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 400,
            "stIndexLevel": {"id": 4, "indexLevelName": "Zły"},
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_resp

        data = await fetch_gios_air_quality(400, client=mock_client)
        self.assertEqual(data["index_name"], "Zły")
        self.assertEqual(data["pm10"], 125.0)
        self.assertEqual(data["source"], "GIOS_LIVE")

    async def test_fetch_gios_fallback_on_network_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        data = await fetch_gios_air_quality(400, client=mock_client)
        self.assertEqual(data["index_name"], "Dobry")
        self.assertEqual(data["source"], "FALLBACK_DEFAULT")

    async def test_fetch_open_meteo_weather_mocked(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hourly": {
                "time": ["2026-10-05T08:00"],
                "temperature_2m": [12.4],
                "rain": [1.5],
                "precipitation": [1.5],
                "weathercode": [61],
                "windspeed_10m": [18.2],
            }
        }
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_resp

        weather = await fetch_open_meteo_weather(50.06, 19.94, "2026-10-05T08:30:00+02:00", client=mock_client)
        self.assertEqual(weather["temperature_c"], 12.4)
        self.assertEqual(weather["rain_mm"], 1.5)
        self.assertEqual(weather["condition"], "Lekki deszcz")
        self.assertEqual(weather["source"], "OPEN_METEO_LIVE")

    async def test_fetch_open_meteo_fallback_on_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.TimeoutException("Timeout")

        weather = await fetch_open_meteo_weather(50.06, 19.94, "2026-10-05T08:30:00+02:00", client=mock_client)
        self.assertEqual(weather["source"], "FALLBACK_DEFAULT")

    async def test_get_environmental_context_caching(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        
        # 1st call
        mock_resp_gios = MagicMock(status_code=200)
        mock_resp_gios.json.return_value = {"stIndexLevel": {"indexLevelName": "Umiarkowany"}}
        mock_resp_weather = MagicMock(status_code=200)
        mock_resp_weather.json.return_value = {
            "hourly": {"time": ["2026-10-05T08:00"], "temperature_2m": [14.0], "rain": [0.0]}
        }
        mock_client.get.side_effect = [mock_resp_gios, mock_resp_weather]

        ctx1 = await get_environmental_context(50.064, 19.924, "2026-10-05T08:30:00+02:00", client=mock_client)
        self.assertEqual(ctx1["air_quality"]["index_name"], "Umiarkowany")
        self.assertEqual(mock_client.get.call_count, 2)

        # 2nd call: should hit cache and NOT make any HTTP calls
        ctx2 = await get_environmental_context(50.064, 19.924, "2026-10-05T08:30:00+02:00", client=mock_client)
        self.assertEqual(ctx2["air_quality"]["index_name"], "Umiarkowany")
        self.assertEqual(mock_client.get.call_count, 2)  # still 2!


if __name__ == "__main__":
    unittest.main()
