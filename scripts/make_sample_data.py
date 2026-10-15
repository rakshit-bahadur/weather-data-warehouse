"""Generate synthetic sample files in the Open-Meteo response format.

The sample lets the full pipeline (load, dbt build, tests) run offline.
Values are synthetic and only shaped like real data. They are not real
observations. Use the real loader for actual weather data.
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
START = date(2026, 4, 1)
DAYS = 120

CITIES = {
    "Delhi": dict(base=33.0, swing=5.0, rain=0.35, humidity=48),
    "Mumbai": dict(base=29.5, swing=2.0, rain=0.60, humidity=78),
    "Bengaluru": dict(base=25.0, swing=2.0, rain=0.45, humidity=68),
    "Patna": dict(base=31.5, swing=4.0, rain=0.40, humidity=62),
    "Shimla": dict(base=18.0, swing=4.0, rain=0.50, humidity=70),
}


def build(city: str, cfg: dict, rng: random.Random) -> dict:
    times, tmax, tmin, tmean, precip, rain, hum, wind = [], [], [], [], [], [], [], []
    for i in range(DAYS):
        day = START + timedelta(days=i)
        season = cfg["swing"] * math.sin(math.pi * i / DAYS)
        mean = cfg["base"] + season + rng.gauss(0, 1.0)
        # Two injected heat spikes so the anomaly model has something to find.
        if i in (40, 41) and city in ("Delhi", "Patna"):
            mean += 7.5
        spread = rng.uniform(6, 10)
        wet = rng.random() < cfg["rain"] * (0.4 + i / DAYS)
        r = round(rng.expovariate(1 / 12), 1) if wet else 0.0
        times.append(day.isoformat())
        tmean.append(round(mean, 1))
        tmax.append(round(mean + spread / 2, 1))
        tmin.append(round(mean - spread / 2, 1))
        rain.append(r)
        precip.append(r)
        hum.append(round(min(98, cfg["humidity"] + (15 if wet else 0) + rng.gauss(0, 4)), 0))
        wind.append(round(abs(rng.gauss(14, 5)), 1))
    return {
        "timezone": "Asia/Kolkata",
        "daily_units": {"temperature_2m_max": "°C", "precipitation_sum": "mm", "wind_speed_10m_max": "km/h"},
        "daily": {
            "time": times,
            "temperature_2m_max": tmax,
            "temperature_2m_min": tmin,
            "temperature_2m_mean": tmean,
            "precipitation_sum": precip,
            "rain_sum": rain,
            "relative_humidity_2m_mean": hum,
            "wind_speed_10m_max": wind,
        },
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    for city, cfg in CITIES.items():
        path = OUT_DIR / f"{city.lower()}.json"
        path.write_text(json.dumps(build(city, cfg, rng)), encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
