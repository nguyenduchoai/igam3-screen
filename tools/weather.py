# Weather from Open-Meteo (https://open-meteo.com): free for non-commercial use, no account and no key.
# Weather data by Open-Meteo.com, under CC BY 4.0: the clock screen shows the credit.

import json
import threading
import time
import urllib.parse
import urllib.request

FORECAST = "https://api.open-meteo.com/v1/forecast"
GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
REFRESH_S = 15 * 60
RETRY_S = 60

# WMO weather codes: (icon, Vietnamese, English)
CODES = {
    0: ("clear", "Trời quang", "Clear sky"), 1: ("clear", "Ít mây", "Mainly clear"),
    2: ("partly", "Có mây", "Partly cloudy"), 3: ("cloud", "Nhiều mây", "Overcast"),
    45: ("fog", "Sương mù", "Fog"), 48: ("fog", "Sương mù", "Fog"),
    51: ("drizzle", "Mưa phùn nhẹ", "Light drizzle"), 53: ("drizzle", "Mưa phùn", "Drizzle"),
    55: ("drizzle", "Mưa phùn dày", "Dense drizzle"), 56: ("drizzle", "Mưa phùn lạnh", "Freezing drizzle"),
    57: ("drizzle", "Mưa phùn lạnh", "Freezing drizzle"),
    61: ("rain", "Mưa nhỏ", "Light rain"), 63: ("rain", "Mưa vừa", "Rain"), 65: ("rain", "Mưa to", "Heavy rain"),
    66: ("rain", "Mưa lạnh", "Freezing rain"), 67: ("rain", "Mưa lạnh to", "Heavy freezing rain"),
    71: ("snow", "Tuyết nhẹ", "Light snow"), 73: ("snow", "Tuyết", "Snow"), 75: ("snow", "Tuyết dày", "Heavy snow"),
    77: ("snow", "Mưa tuyết", "Snow grains"),
    80: ("rain", "Mưa rào nhẹ", "Light showers"), 81: ("rain", "Mưa rào", "Showers"),
    82: ("storm", "Mưa rào rất to", "Violent showers"),
    85: ("snow", "Mưa tuyết", "Snow showers"), 86: ("snow", "Mưa tuyết to", "Heavy snow showers"),
    95: ("storm", "Dông", "Thunderstorm"), 96: ("storm", "Dông, mưa đá", "Thunderstorm, hail"),
    99: ("storm", "Dông, mưa đá to", "Thunderstorm, heavy hail"),
}


def describe(code, vi):
    """(icon, text) of a WMO weather code"""
    icon, text_vi, text_en = CODES.get(int(code) if code is not None else -1, ("cloud", "Không rõ", "Unknown"))
    return icon, text_vi if vi else text_en


def _get(url, params):
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "igam3-screen"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read(2 * 1024 * 1024))


def geocode(name, language="vi", count=5):
    """Places matching a name: [{name, region, country, latitude, longitude}]"""
    data = _get(GEOCODING, {"name": name, "count": count, "language": language, "format": "json"})
    return [{"name": r["name"], "region": r.get("admin1", ""), "country": r.get("country", ""),
             "latitude": round(float(r["latitude"]), 4), "longitude": round(float(r["longitude"]), 4)}
            for r in data.get("results") or []]


def forecast(latitude, longitude):
    return _get(FORECAST, {
        "latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 3,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })


class Weather:
    """Forecast of the place in the settings, refreshed in the background; the last one is kept on disk"""

    def __init__(self, cache_path, place):
        self.cache_path = cache_path
        self.place = place  # callable -> {"name", "latitude", "longitude"} or None
        self.data, self.fetched_at, self.key = None, 0.0, None
        try:
            saved = json.loads(cache_path.read_text(encoding="utf8"))
            self.data, self.fetched_at, self.key = saved["data"], saved["fetched_at"], tuple(saved["key"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.wake = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def snapshot(self):
        """(forecast or None, age in seconds) for the current place"""
        place = self.place()
        if not place or self.key != (place["latitude"], place["longitude"]):
            if place:
                self.wake.set()  # the place changed: fetch now
            return None, None
        return self.data, time.time() - self.fetched_at

    def _loop(self):
        while True:
            place = self.place()
            wait = REFRESH_S
            if place:
                key = (place["latitude"], place["longitude"])
                if key != self.key or time.time() - self.fetched_at >= REFRESH_S:
                    try:
                        self.data, self.fetched_at, self.key = forecast(*key), time.time(), key
                        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                        self.cache_path.write_text(json.dumps({"data": self.data, "fetched_at": self.fetched_at,
                                                               "key": list(key)}), encoding="utf8")
                    except (OSError, ValueError, KeyError):
                        wait = RETRY_S  # no network: try again soon, keep showing the last forecast
                else:
                    wait = max(5, REFRESH_S - (time.time() - self.fetched_at))
            self.wake.wait(wait)
            self.wake.clear()
