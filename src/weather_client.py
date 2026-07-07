"""
weather_client.py

Fetches daily weather and air quality data from Open-Meteo.
Open-Meteo is completely free — no API key, no rate limits for personal use.

Two APIs used:
  - Archive API:     Historical weather (temperature, humidity, precipitation, UV, wind)
  - Air Quality API: Historical PM2.5 and PM10 (proxies for allergy/pollution days)

Why Open-Meteo?
  - Free forever for personal use
  - No API key or account needed
  - High quality data from national weather services (NOAA for US)
  - Historical archive back to 1940

Location is read from .env (LOCATION_LAT / LOCATION_LON).
Defaults to Ballston, VA if not set.

Docs: https://open-meteo.com/en/docs
"""

import os
from datetime import date, timedelta
from collections import defaultdict

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Location ───────────────────────────────────────────────────────────────────

LAT  = float(os.getenv("LOCATION_LAT",  "38.8826"))   # Ballston, VA
LON  = float(os.getenv("LOCATION_LON", "-77.1116"))
NAME = os.getenv("LOCATION_NAME", "Ballston, VA")

# ── API endpoints ──────────────────────────────────────────────────────────────

WEATHER_ARCHIVE_URL   = "https://archive-api.open-meteo.com/v1/archive"
AIR_QUALITY_URL       = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_FORECAST_URL  = "https://api.open-meteo.com/v1/forecast"   # recent days only
TOMORROW_API_URL      = "https://api.tomorrow.io/v4/weather/forecast"
TOMORROW_API_KEY      = os.getenv("TOMORROW_API_KEY")


# ── Weather ────────────────────────────────────────────────────────────────────

def get_weather_range(start: str, end: str) -> list[dict]:
    """
    Fetch daily weather for a date range.

    Uses the archive API for historical data.
    For dates within the last 5 days (not yet in archive), falls back to
    the forecast API's past_days parameter.

    Args:
        start: "YYYY-MM-DD"
        end:   "YYYY-MM-DD"

    Returns:
        List of dicts with keys: date, temp_max, temp_min, temp_mean,
        humidity, precipitation, wind_speed, uv_index, weather_code
    """
    # The archive API lags ~2 days — use forecast API for recent data
    archive_cutoff = (date.today() - timedelta(days=3)).isoformat()

    records = {}

    # ── Historical (archive) ──────────────────────────────────────────────────
    if start <= archive_cutoff:
        hist_end = min(end, archive_cutoff)
        params = {
            "latitude":   LAT,
            "longitude":  LON,
            "start_date": start,
            "end_date":   hist_end,
            "daily":      "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                          "precipitation_sum,windspeed_10m_max,uv_index_max,weathercode",
            "hourly":     "relative_humidity_2m",
            "timezone":   "America/New_York",
        }
        try:
            resp = requests.get(WEATHER_ARCHIVE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            records.update(_parse_weather_response(data))
        except Exception as e:
            print(f"  Weather archive fetch failed: {e}")

    # ── Recent (forecast API with past_days) ──────────────────────────────────
    if end > archive_cutoff:
        past_days = (date.today() - date.fromisoformat(max(start, archive_cutoff))).days + 1
        params = {
            "latitude":   LAT,
            "longitude":  LON,
            "past_days":  min(past_days, 7),
            "daily":      "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                          "precipitation_sum,windspeed_10m_max,uv_index_max,weathercode",
            "hourly":     "relative_humidity_2m",
            "timezone":   "America/New_York",
        }
        try:
            resp = requests.get(WEATHER_FORECAST_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            records.update(_parse_weather_response(data))
        except Exception as e:
            print(f"  Weather forecast fetch failed: {e}")

    # Return only dates in the requested range, sorted
    return [v for k, v in sorted(records.items()) if start <= k <= end]


def _parse_weather_response(data: dict) -> dict:
    """Parse Open-Meteo response into {date: record} dict."""
    daily  = data.get("daily", {})
    hourly = data.get("hourly", {})

    dates          = daily.get("time", [])
    humidity_raw   = hourly.get("relative_humidity_2m", [])

    # Average hourly humidity into daily means (24 readings per day)
    daily_humidity = []
    for i in range(len(dates)):
        chunk = humidity_raw[i * 24: (i + 1) * 24]
        valid = [h for h in chunk if h is not None]
        daily_humidity.append(round(sum(valid) / len(valid), 1) if valid else None)

    result = {}
    for i, d in enumerate(dates):
        result[d] = {
            "date":         d,
            "temp_max":     _safe(daily.get("temperature_2m_max", []), i),
            "temp_min":     _safe(daily.get("temperature_2m_min", []), i),
            "temp_mean":    _safe(daily.get("temperature_2m_mean", []), i),
            "precipitation": _safe(daily.get("precipitation_sum", []), i),
            "wind_speed":   _safe(daily.get("windspeed_10m_max", []), i),
            "uv_index":     _safe(daily.get("uv_index_max", []), i),
            "weather_code": _safe(daily.get("weathercode", []), i),
            "humidity":     daily_humidity[i] if i < len(daily_humidity) else None,
        }
    return result


# ── Air Quality ────────────────────────────────────────────────────────────────

def get_air_quality_range(start: str, end: str) -> list[dict]:
    """
    Fetch daily average PM2.5 and PM10 for a date range.

    PM2.5 and PM10 are airborne particle measures used as proxies for
    air quality and allergy conditions. High PM2.5 days often coincide
    with high pollen, smoke, or pollution events.

    Args:
        start: "YYYY-MM-DD"
        end:   "YYYY-MM-DD"

    Returns:
        List of dicts with keys: date, pm25, pm10, aqi_category
    """
    # Air quality archive also lags — request a few extra days and filter
    params = {
        "latitude":   LAT,
        "longitude":  LON,
        "start_date": start,
        "end_date":   end,
        "hourly":     "pm2_5,pm10",
        "timezone":   "America/New_York",
    }
    try:
        resp = requests.get(AIR_QUALITY_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Air quality fetch failed: {e}")
        return []

    hourly = data.get("hourly", {})
    times      = hourly.get("time", [])
    pm25_hours = hourly.get("pm2_5", [])
    pm10_hours = hourly.get("pm10", [])

    # Aggregate hourly → daily means
    daily_pm25 = defaultdict(list)
    daily_pm10 = defaultdict(list)

    for i, t in enumerate(times):
        d = t[:10]  # "2026-06-15T14:00" → "2026-06-15"
        if i < len(pm25_hours) and pm25_hours[i] is not None:
            daily_pm25[d].append(pm25_hours[i])
        if i < len(pm10_hours) and pm10_hours[i] is not None:
            daily_pm10[d].append(pm10_hours[i])

    records = []
    for d in sorted(daily_pm25.keys()):
        if not (start <= d <= end):
            continue
        pm25 = round(sum(daily_pm25[d]) / len(daily_pm25[d]), 1) if daily_pm25[d] else None
        pm10 = round(sum(daily_pm10[d]) / len(daily_pm10[d]), 1) if daily_pm10[d] else None
        records.append({
            "date":         d,
            "pm25":         pm25,
            "pm10":         pm10,
            "aqi_category": _pm25_category(pm25),
        })
    return records


def _pm25_category(pm25: float | None) -> str | None:
    """
    Convert PM2.5 µg/m³ to EPA AQI category label.
    These thresholds match the US EPA Air Quality Index standard.
    """
    if pm25 is None:
        return None
    if pm25 <= 12.0:
        return "Good"
    if pm25 <= 35.4:
        return "Moderate"
    if pm25 <= 55.4:
        return "Unhealthy for Sensitive Groups"
    if pm25 <= 150.4:
        return "Unhealthy"
    return "Very Unhealthy"


# ── Pollen (Tomorrow.io) ───────────────────────────────────────────────────────

def get_pollen_range(start: str, end: str) -> list[dict]:
    """
    Fetch daily pollen indices from Tomorrow.io for a date range.

    Tomorrow.io provides US pollen data (unlike Open-Meteo, which is Europe-only).
    The free tier allows 500 calls/day, no credit card required.

    Fields returned:
      grassIndex     — overall grass pollen (0–5 scale)
      treeIndex      — overall tree pollen (0–5 scale)
      weedIndex      — overall weed pollen (0–5 scale)
      weedRagweedIndex — ragweed specifically (0–5 scale, US only)

    Index scale: 0=None, 1=Very Low, 2=Low, 3=Medium, 4=High, 5=Very High

    Limitation: Tomorrow.io free tier only returns ~7 days of historical data.
    Run the pipeline daily to accumulate a growing correlation dataset.

    Args:
        start: "YYYY-MM-DD"
        end:   "YYYY-MM-DD"

    Returns:
        List of dicts with keys: date, grass_pollen, tree_pollen,
        weed_pollen, ragweed_pollen
    """
    if not TOMORROW_API_KEY:
        print("  Skipping pollen: TOMORROW_API_KEY not set in .env")
        return []

    params = {
        "location":  f"{LAT},{LON}",
        "fields":    "grassIndex,treeIndex,weedIndex,weedRagweedIndex",
        "timesteps": "1d",
        "timezone":  "America/New_York",
        "apikey":    TOMORROW_API_KEY,
    }
    try:
        resp = requests.get(TOMORROW_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Pollen fetch failed: {e}")
        return []

    records = []
    for day in data.get("timelines", {}).get("daily", []):
        d = day.get("time", "")[:10]  # "2026-07-05T06:00:00Z" → "2026-07-05"
        if not (start <= d <= end):
            continue
        v = day.get("values", {})
        records.append({
            "date":           d,
            "grass_pollen":   v.get("grassIndex"),
            "tree_pollen":    v.get("treeIndex"),
            "weed_pollen":    v.get("weedIndex"),
            "ragweed_pollen": v.get("weedRagweedIndex"),
        })

    return sorted(records, key=lambda r: r["date"])


def pollen_label(index: int | None) -> str:
    """Convert Tomorrow.io pollen index (0–5) to text label."""
    if index is None:
        return "No data"
    return {0: "None", 1: "Very Low", 2: "Low", 3: "Medium", 4: "High", 5: "Very High"}.get(index, "Unknown")


# ── Utilities ──────────────────────────────────────────────────────────────────

def _safe(lst: list, i: int):
    """Safely get index i from a list, return None if out of range."""
    try:
        return lst[i]
    except IndexError:
        return None


def weather_code_label(code: int | None) -> str:
    """
    Convert WMO weather code to human-readable label.
    Used for the weather condition description in the UI.
    https://open-meteo.com/en/docs#weathervariables
    """
    if code is None:
        return "Unknown"
    codes = {
        0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Icy fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow",
        77: "Snow grains",
        80: "Light showers", 81: "Showers", 82: "Heavy showers",
        85: "Snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
    }
    return codes.get(code, f"Code {code}")
