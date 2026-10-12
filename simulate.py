"""Simulate an IoT sensor dataset in a Tiger Cloud service.

Creates the tutorial's `sensors` table and `sensor_data` hypertable (sql/schema.sql),
then backfills N days of readings every 5 minutes for every sensor.

    python simulate.py            # create schema (if missing) and load readings
    python simulate.py --report   # read-only summary + the tutorial's queries

The connection string comes from the Tiger CLI at runtime
(`tiger db uri <service> --with-password`). It is kept in memory only and is
never printed, logged or written to disk.
"""

from __future__ import annotations

import argparse
import math
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
SCHEMA_SQL = HERE / "sql" / "schema.sql"
QUERIES_SQL = HERE / "sql" / "queries.sql"

STEP = timedelta(minutes=5)
IST_OFFSET_MIN = 330  # UTC+5:30, used for the daily cycle

# Value model (see README): base temperature per location, offset per sensor type.
BASE_TEMP = {"floor": 21.0, "ceiling": 24.0}
TYPE_OFFSET = {"a": 0.0, "b": 0.5}


class SimulatorError(Exception):
    """An error whose message is safe to print (no hostnames or secrets)."""


# --------------------------------------------------------------------------- connection

def get_uri(service: str) -> str:
    """Ask the Tiger CLI for the service's connection string. Never print the result."""
    tiger = shutil.which("tiger")
    if tiger is None:
        raise SimulatorError("Tiger CLI not found on PATH. Install it and run `tiger auth login`.")
    proc = subprocess.run(
        [tiger, "db", "uri", service, "--with-password"],
        capture_output=True,
        text=True,
        check=False,
    )
    uri = proc.stdout.strip()
    if proc.returncode != 0 or not uri.startswith(("postgres://", "postgresql://")):
        raise SimulatorError(
            f"`tiger db uri` failed (exit {proc.returncode}). Run `tiger auth login` and check the service name."
        )
    return uri


def connect(service: str) -> psycopg.Connection:
    uri = get_uri(service)
    try:
        return psycopg.connect(uri, application_name="tigercloud-iot-simulator", connect_timeout=20)
    except psycopg.OperationalError:
        # psycopg's message includes the hostname, so don't echo it.
        raise SimulatorError(f"Could not connect to service '{service}'.") from None
    finally:
        del uri


# --------------------------------------------------------------------------- data model

def ist_hour(t: datetime) -> float:
    """Hour of day (0-24, fractional) in IST for a UTC timestamp."""
    minutes = (t.hour * 60 + t.minute + IST_OFFSET_MIN) % (24 * 60)
    return minutes / 60.0


def temperature(rng: random.Random, sensor_type: str, location: str, h: float) -> float:
    """Daily cycle peaking ~3 PM IST, lowest ~3 AM; ceiling sensors run ~3 C warmer."""
    daily = 3.0 * math.sin(2 * math.pi * (h - 9) / 24)
    value = BASE_TEMP[location] + TYPE_OFFSET[sensor_type] + daily + rng.gauss(0, 0.4)
    return round(value, 2)


def cpu(rng: random.Random, h: float) -> float:
    """Utilisation 0-1: idle baseline plus a working-hours (9 AM-7 PM IST) load hump."""
    workload = math.sin(math.pi * (h - 9) / 10) if 9 <= h < 19 else 0.0
    value = 0.25 + 0.35 * workload + rng.gauss(0, 0.05)
    return round(min(1.0, max(0.0, value)), 3)


def time_range(days: int) -> tuple[datetime, int]:
    """Start timestamp and number of 5-minute steps: [now - days, now), aligned to 5 minutes."""
    now = datetime.now(timezone.utc)
    end = now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0)
    steps = days * 24 * 12
    return end - steps * STEP, steps


def generate_rows(sensors: list[tuple[int, str, str]], days: int, seed: int):
    """Yield (time, sensor_id, temperature, cpu) rows in time order."""
    rng = random.Random(seed)
    start, steps = time_range(days)
    for k in range(steps):
        t = start + k * STEP
        h = ist_hour(t)
        for sensor_id, sensor_type, location in sensors:
            yield t, sensor_id, temperature(rng, sensor_type, location, h), cpu(rng, h)


# --------------------------------------------------------------------------- commands

def load(conn: psycopg.Connection, days: int, seed: int) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        cur.execute("SELECT id, type, location FROM sensors ORDER BY id")
        sensors = cur.fetchall()

        cur.execute("CREATE TEMP TABLE sensor_data_stage (LIKE sensor_data) ON COMMIT DROP")
        generated = 0
        with cur.copy("COPY sensor_data_stage (time, sensor_id, temperature, cpu) FROM STDIN") as copy:
            for row in generate_rows(sensors, days, seed):
                copy.write_row(row)
                generated += 1

        cur.execute(
            """
            INSERT INTO sensor_data (time, sensor_id, temperature, cpu)
            SELECT time, sensor_id, temperature, cpu FROM sensor_data_stage
            ON CONFLICT (sensor_id, time) DO NOTHING
            """
        )
        inserted = cur.rowcount

    print(f"sensors: {len(sensors)}")
    print(f"generated {generated} readings ({days} days x 5 min x {len(sensors)} sensors)")
    print(f"inserted {inserted} rows ({generated - inserted} already present)")
    summary(conn)


def summary(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'Asia/Kolkata'")
        cur.execute("SELECT count(*), min(time), max(time) FROM sensor_data")
        total, first, last = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = 'sensor_data'"
        )
        (chunks,) = cur.fetchone()
    fmt = "%a %d %b %Y %H:%M IST"
    span = f"{first:{fmt}} -> {last:{fmt}}" if total else "empty"
    print(f"sensor_data: {total} rows, {chunks} chunks, {span}")


def read_queries() -> list[str]:
    """Split sql/queries.sql into statements, keeping each one's leading comment as a title."""
    statements = []
    for block in QUERIES_SQL.read_text(encoding="utf-8").split(";"):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        titles = [ln[2:].strip() for ln in lines if ln.startswith("--")]
        sql = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        if sql:
            statements.append((titles[-1] if titles else "query", sql))
    return statements


def fmt_cell(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def print_table(columns: list[str], rows: list[tuple]) -> None:
    cells = [[fmt_cell(v) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) if cells else len(c) for i, c in enumerate(columns)]
    print("  " + " | ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  " + "-+-".join("-" * w for w in widths))
    for r in cells:
        print("  " + " | ".join(v.ljust(w) for v, w in zip(r, widths)))


def report(conn: psycopg.Connection, tail: int = 6) -> None:
    """Read-only: per-sensor counts, floor vs ceiling, and the tutorial's queries."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        summary(conn)

        print("\nReadings per sensor")
        cur.execute(
            """
            SELECT s.id, s.type, s.location, count(d.*) AS readings
            FROM sensors s LEFT JOIN sensor_data d ON d.sensor_id = s.id
            GROUP BY s.id, s.type, s.location ORDER BY s.id
            """
        )
        print_table([c.name for c in cur.description], cur.fetchall())

        print("\nFloor vs ceiling (all readings)")
        cur.execute(
            """
            SELECT s.location, round(avg(d.temperature)::numeric, 2) AS avg_temp_c,
                   round(min(d.temperature)::numeric, 2) AS min_temp_c,
                   round(max(d.temperature)::numeric, 2) AS max_temp_c,
                   round(avg(d.cpu)::numeric, 3) AS avg_cpu
            FROM sensor_data d JOIN sensors s ON s.id = d.sensor_id
            GROUP BY s.location ORDER BY s.location
            """
        )
        print_table([c.name for c in cur.description], cur.fetchall())

        for title, sql in read_queries():
            cur.execute(sql)
            rows = cur.fetchall()
            print(f"\n{title}  ({len(rows)} rows, last {min(tail, len(rows))} shown, times in IST)")
            print_table([c.name for c in cur.description], rows[-tail:])


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate an IoT sensor dataset in Tiger Cloud.")
    parser.add_argument("--service", default="db-ghw", help="Tiger Cloud service name or ID (default: db-ghw)")
    parser.add_argument("--days", type=int, default=7, help="days of history to backfill (default: 7)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    parser.add_argument("--report", action="store_true", help="print a read-only report instead of loading")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")

    try:
        with connect(args.service) as conn:
            if args.report:
                report(conn)
            else:
                load(conn, args.days, args.seed)
    except SimulatorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except psycopg.Error as exc:
        message = exc.diag.message_primary if exc.diag and exc.diag.message_primary else type(exc).__name__
        print(f"database error: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
