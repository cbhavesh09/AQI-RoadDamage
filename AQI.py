from __future__ import annotations
import os
import sys
import argparse
import requests
import json
from dotenv import load_dotenv

load_dotenv()

DEFAULT_OPENWEATHER_URL = "http://api.openweathermap.org/data/2.5/air_pollution"
OW_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

USER_EMAIL = os.getenv("USER_EMAIL", "aqi-checker@example.com")

OW_AQI_MAP = {
    1: "Good",
    2: "Fair",
    3: "Moderate",
    4: "Poor",
    5: "Very Poor"
}


PM25_BREAKPOINTS = [
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 350.4, 301, 400),
    (350.5, 500.4, 401, 500),
]

def linear_aqi(Cp: float, Clow: float, Chigh: float, Ilow: int, Ihigh: int) -> int:
    return round((Ihigh - Ilow) / (Chigh - Clow) * (Cp - Clow) + Ilow)

def pm25_to_us_aqi(pm25: float | None) -> int | None:
    if pm25 is None:
        return None
    Cp = float(pm25)
    for (Clow, Chigh, Ilow, Ihigh) in PM25_BREAKPOINTS:
        if Clow <= Cp <= Chigh:
            return linear_aqi(Cp, Clow, Chigh, Ilow, Ihigh)
    return None

def reverse_geocode(lat: float, lon: float) -> str | None:
    headers = {"User-Agent": f"AQI-Checker ({USER_EMAIL})"}
    params = {"lat": lat, "lon": lon, "format": "json", "zoom": 10, "addressdetails": 0}
    try:
        resp = requests.get(OW_NOMINATIM_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("display_name")
    except requests.RequestException:
        return None

def get_aqi(lat: float, lon: float, api_key: str | None, base_url: str = DEFAULT_OPENWEATHER_URL) -> dict:
    if not api_key:
        raise ValueError("OpenWeather API key not provided. Set OPENWEATHER_API_KEY in .env or pass --api-key.")
    params = {"lat": lat, "lon": lon, "appid": api_key}
    try:
        resp = requests.get(base_url, params=params, timeout=12)
    except requests.RequestException as e:
        raise RuntimeError(f"Network error while contacting OpenWeather: {e}") from e

    if resp.status_code == 401:
        raise PermissionError("401 Unauthorized — check your OpenWeather API key.")
    if resp.status_code == 429:
        raise RuntimeError("429 Too Many Requests — you may have hit the rate limit.")
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"OpenWeather HTTP error: {e}") from e

    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError("OpenWeather returned non-JSON response.")

    if "list" not in data or not data["list"]:
        raise RuntimeError("OpenWeather returned no 'list' data for the coordinates.")

    entry = data["list"][0]
    main = entry.get("main") or {}
    comps = entry.get("components") or {}

    ow_aqi = main.get("aqi")
    pm25 = comps.get("pm2_5") or comps.get("pm2.5") or None
    us_aqi = pm25_to_us_aqi(pm25)

    return {
        "openweather_aqi": ow_aqi,
        "openweather_category": OW_AQI_MAP.get(ow_aqi, "Unknown"),
        "components": comps,
        "us_aqi_pm25": us_aqi,
        "raw": data
    }

def pretty_print(lat: float, lon: float, info: dict):
    place = reverse_geocode(lat, lon)
    print("\n" + "=" * 48)
    if place:
        print(f"Location: {place}")
    else:
        print("Location: (reverse geocoding unavailable)")
    print(f"Coordinates: {lat}, {lon}")
    print("=" * 48)
    print(f"OpenWeather AQI (1–5): {info.get('openweather_aqi')} ({info.get('openweather_category')})")
    if info.get("us_aqi_pm25") is not None:
        print(f"Estimated US AQI (from PM2.5): {info['us_aqi_pm25']}")
    else:
        print("Estimated US AQI (from PM2.5): N/A")
    print("\nPollutant concentrations (units: μg/m³ unless noted):")
    for k, v in (info.get("components") or {}).items():
        print(f"  {k:>8}: {v}")
    print()

def main(argv: list | None = None):
    parser = argparse.ArgumentParser(prog="aqi_by_latlon.py", description="Fetch AQI (OpenWeather) and place name (Nominatim).")
    parser.add_argument("lat", type=float, help="Latitude (e.g. 28.7041)")
    parser.add_argument("lon", type=float, help="Longitude (e.g. 77.1025)")
    parser.add_argument("--api-key", type=str, default=None, help="OpenWeather API key (overrides .env)")
    parser.add_argument("--json", action="store_true", help="Print raw OpenWeather JSON and exit")
    args = parser.parse_args(argv)

    api_key = args.api_key or os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        print("Error: OPENWEATHER_API_KEY not found. Add it to your .env file or pass --api-key.", file=sys.stderr)
        sys.exit(2)

    try:
        info = get_aqi(args.lat, args.lon, api_key)
        if args.json:
            print(json.dumps(info["raw"], indent=2))
        else:
            pretty_print(args.lat, args.lon, info)
    except PermissionError as e:
        print("Permission error:", e, file=sys.stderr)
        sys.exit(3)
    except RuntimeError as e:
        print("Runtime error:", e, file=sys.stderr)
        sys.exit(4)
    except Exception as e:
        print("Unexpected error:", e, file=sys.stderr)
        sys.exit(5)

if __name__ == "__main__":
    main()
