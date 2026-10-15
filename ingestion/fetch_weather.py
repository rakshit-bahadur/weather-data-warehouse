"""Load daily weather data from the Open-Meteo Archive API into DuckDB.

The loader is idempotent: for every city it deletes the requested date range
from raw.weather_daily before inserting, so re-running a load never creates
duplicates. Each run writes one row per city to raw.load_audit.

Examples:
    python -m ingestion.fetch_weather --days 90
    python -m ingestion.fetch_weather --start 2026-01-01 --end 2026-03-31
    python -m ingestion.fetch_weather --sample-dir data/sample
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import requests
import yaml

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARIABLES = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "rain_sum",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
]
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = os.environ.get("WEATHER_DB_PATH", str(PROJECT_ROOT / "warehouse" / "weather.duckdb"))
DEFAULT_CITIES = PROJECT_ROOT / "config" / "cities.yml"

log = logging.getLogger("fetch_weather")


@dataclass(frozen=True)
class City:
    city: str
    state: str
    latitude: float
    longitude: float


def load_cities(path: Path) -> list[City]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [City(**c) for c in data["cities"]]


def fetch_city(city: City, start: date, end: date, retries: int = 3) -> dict:
    params = {
        "latitude": city.latitude,
        "longitude": city.longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": "Asia/Kolkata",
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(ARCHIVE_URL, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            log.warning("%s: attempt %d failed (%s), retrying in %ds", city.city, attempt, exc, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def parse_daily(payload: dict, city: City, run_id: str, loaded_at: datetime) -> list[tuple]:
    """Turn an Open-Meteo daily response into rows for raw.weather_daily."""
    daily = payload.get("daily")
    if not daily or "time" not in daily:
        raise ValueError(f"{city.city}: response has no daily block")
    days = daily["time"]
    for var in DAILY_VARIABLES:
        values = daily.get(var)
        if values is None or len(values) != len(days):
            raise ValueError(f"{city.city}: variable {var} missing or wrong length")
    rows = []
    for i, day in enumerate(days):
        rows.append(
            (
                city.city,
                city.state,
                city.latitude,
                city.longitude,
                date.fromisoformat(day),
                *[daily[var][i] for var in DAILY_VARIABLES],
                run_id,
                loaded_at,
            )
        )
    return rows


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.weather_daily (
            city VARCHAR,
            state VARCHAR,
            latitude DOUBLE,
            longitude DOUBLE,
            weather_date DATE,
            temperature_2m_max DOUBLE,
            temperature_2m_min DOUBLE,
            temperature_2m_mean DOUBLE,
            precipitation_sum DOUBLE,
            rain_sum DOUBLE,
            relative_humidity_2m_mean DOUBLE,
            wind_speed_10m_max DOUBLE,
            run_id VARCHAR,
            loaded_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.load_audit (
            run_id VARCHAR,
            city VARCHAR,
            start_date DATE,
            end_date DATE,
            rows_loaded INTEGER,
            status VARCHAR,
            error_message VARCHAR,
            loaded_at TIMESTAMP
        )
        """
    )


def write_rows(con: duckdb.DuckDBPyConnection, city: City, start: date, end: date, rows: list[tuple]) -> None:
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            "DELETE FROM raw.weather_daily WHERE city = ? AND weather_date BETWEEN ? AND ?",
            [city.city, start, end],
        )
        con.executemany(
            "INSERT INTO raw.weather_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def audit(con, run_id, city, start, end, rows_loaded, status, error, loaded_at) -> None:
    con.execute(
        "INSERT INTO raw.load_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [run_id, city.city, start, end, rows_loaded, status, error, loaded_at],
    )


def run(db_path: str, cities: list[City], start: date, end: date, sample_dir: Path | None = None) -> int:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    failures = 0
    with duckdb.connect(db_path) as con:
        ensure_schema(con)
        for city in cities:
            try:
                if sample_dir is not None:
                    sample_file = sample_dir / f"{city.city.lower()}.json"
                    if not sample_file.exists():
                        continue
                    payload = json.loads(sample_file.read_text(encoding="utf-8"))
                    days = payload["daily"]["time"]
                    city_start, city_end = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
                else:
                    payload = fetch_city(city, start, end)
                    city_start, city_end = start, end
                rows = parse_daily(payload, city, run_id, loaded_at)
                write_rows(con, city, city_start, city_end, rows)
                audit(con, run_id, city, city_start, city_end, len(rows), "SUCCESS", None, loaded_at)
                log.info("%s: loaded %d rows", city.city, len(rows))
            except Exception as exc:
                failures += 1
                audit(con, run_id, city, start, end, 0, "FAILED", str(exc)[:500], loaded_at)
                log.error("%s: load failed: %s", city.city, exc)
    log.info("Run %s finished with %d failure(s)", run_id, failures)
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Open-Meteo daily weather into DuckDB")
    parser.add_argument("--db", default=DEFAULT_DB, help="DuckDB file path")
    parser.add_argument("--cities", default=str(DEFAULT_CITIES), help="Cities YAML file")
    parser.add_argument("--days", type=int, default=90, help="Days of history to load, ending 5 days ago")
    parser.add_argument("--start", type=date.fromisoformat, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="End date (YYYY-MM-DD)")
    parser.add_argument("--sample-dir", type=Path, help="Load bundled sample JSON instead of calling the API")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # The archive API publishes data with a delay of a few days.
    end = args.end or (date.today() - timedelta(days=5))
    start = args.start or (end - timedelta(days=args.days - 1))
    if start > end:
        parser.error("start date must be on or before end date")

    failures = run(args.db, load_cities(Path(args.cities)), start, end, args.sample_dir)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
