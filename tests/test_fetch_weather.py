from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest

from ingestion.fetch_weather import City, ensure_schema, load_cities, parse_daily, run, write_rows

ROOT = Path(__file__).resolve().parents[1]
DELHI = City("Delhi", "Delhi", 28.6139, 77.2090)
LOADED_AT = datetime(2026, 1, 1, 0, 0, 0)


def payload(days=("2026-01-01", "2026-01-02"), **overrides):
    n = len(days)
    daily = {
        "time": list(days),
        "temperature_2m_max": [20.0] * n,
        "temperature_2m_min": [10.0] * n,
        "temperature_2m_mean": [15.0] * n,
        "precipitation_sum": [0.0] * n,
        "rain_sum": [0.0] * n,
        "relative_humidity_2m_mean": [60.0] * n,
        "wind_speed_10m_max": [12.0] * n,
    }
    daily.update(overrides)
    return {"daily": daily}


def test_parse_daily_returns_one_row_per_day():
    rows = parse_daily(payload(), DELHI, "run1", LOADED_AT)
    assert len(rows) == 2
    assert rows[0][0] == "Delhi"
    assert rows[0][4] == date(2026, 1, 1)
    assert rows[0][7] == 15.0


def test_parse_daily_rejects_missing_block():
    with pytest.raises(ValueError, match="no daily block"):
        parse_daily({}, DELHI, "run1", LOADED_AT)


def test_parse_daily_rejects_length_mismatch():
    with pytest.raises(ValueError, match="rain_sum"):
        parse_daily(payload(rain_sum=[0.0]), DELHI, "run1", LOADED_AT)


def test_reload_does_not_duplicate_rows():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    rows = parse_daily(payload(), DELHI, "run1", LOADED_AT)
    write_rows(con, DELHI, date(2026, 1, 1), date(2026, 1, 2), rows)
    write_rows(con, DELHI, date(2026, 1, 1), date(2026, 1, 2), rows)
    assert con.execute("select count(*) from raw.weather_daily").fetchone()[0] == 2


def test_cities_config_has_unique_cities():
    cities = load_cities(ROOT / "config" / "cities.yml")
    names = [c.city for c in cities]
    assert len(names) == 20
    assert len(set(names)) == len(names)


def test_sample_run_writes_audit(tmp_path):
    db = tmp_path / "weather.duckdb"
    cities = load_cities(ROOT / "config" / "cities.yml")
    failures = run(str(db), cities, date(2026, 4, 1), date(2026, 7, 29), ROOT / "data" / "sample")
    assert failures == 0
    with duckdb.connect(str(db)) as con:
        loaded = con.execute("select count(distinct city) from raw.weather_daily").fetchone()[0]
        audited = con.execute("select count(*) from raw.load_audit where status = 'SUCCESS'").fetchone()[0]
    assert loaded == 5
    assert audited == 5
