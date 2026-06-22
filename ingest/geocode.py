"""Geocoding for the pipeline: Census first, city-centroid fallback for missing/
unknown streets. (Google fallback can slot in here when GOOGLE_MAPS_API_KEY is set.)"""
import requests

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

CITY_CENTROIDS = {
    ("manchester", "NH"): (42.9956, -71.4548),
    ("nashua", "NH"): (42.7654, -71.4676),
    ("dover", "NH"): (43.1979, -70.8737),
    ("pittsfield", "NH"): (43.3037, -71.3242),
    ("allenstown", "NH"): (43.1465, -71.4090),
    ("derry", "NH"): (42.8806, -71.3273),
    ("londonderry", "NH"): (42.8651, -71.3743),
    ("salem", "NH"): (42.7884, -71.2009),
    ("rochester", "NH"): (43.3045, -70.9756),
    ("somersworth", "NH"): (43.2615, -70.8650),
    ("hampton", "NH"): (42.9376, -70.8387),
}


def geocode(street, city, state, session=None):
    """Return (lat, lon, method). method in {census, city_centroid_fallback, none}."""
    session = session or requests.Session()
    street_known = street and street.strip().lower() not in ("unknown", "")
    is_tbd = street and ("tbd" in street.lower() or "addr" in street.lower())
    query = f"{street}, {city}, {state}" if (street_known and not is_tbd) else f"{city}, {state}"
    try:
        r = session.get(CENSUS_URL, params={
            "address": query, "benchmark": "Public_AR_Current", "format": "json",
        }, timeout=20)
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches and not is_tbd:
            c = matches[0]["coordinates"]
            return round(c["y"], 6), round(c["x"], 6), "census"
    except Exception:
        pass
    fb = CITY_CENTROIDS.get(((city or "").strip().lower(), (state or "").strip().upper()))
    if fb:
        return fb[0], fb[1], "city_centroid_fallback"
    return None, None, "none"
