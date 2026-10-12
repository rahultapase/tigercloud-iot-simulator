# tigercloud-iot-simulator

Simulates an IoT sensor dataset in a [Tiger Cloud](https://www.tigerdata.com/cloud) (TimescaleDB)
service and runs the queries from Tiger Data's tutorial
[Simulate an IoT sensor dataset](https://www.tigerdata.com/docs/learn/tutorials/simulate-iot-sensor-data).

Built for the MLH Global Hack Week (Hacktoberfest 2026) Tiger Data challenge.

## What it does

- Creates the tutorial's relational `sensors` table and `sensor_data` hypertable
  ([`sql/schema.sql`](sql/schema.sql)) with the declarative `CREATE TABLE … WITH (tsdb.hypertable)` syntax.
- Backfills **7 days of readings every 5 minutes for 4 sensors: 8,064 rows**, loaded with
  `COPY` into a staging table and one `INSERT … ON CONFLICT DO NOTHING`.
- `--report` prints a read-only summary and the tutorial's three queries ([`sql/queries.sql`](sql/queries.sql)).

## Data model

```
sensors (id, type, location)            4 rows: type a/b × floor/ceiling
sensor_data (time, sensor_id → sensors.id, temperature, cpu)
  hypertable on time, 7-day chunks
  columnstore: segmentby sensor_id, orderby time DESC (policy added automatically)
  unique index (sensor_id, time DESC)
```

Changes from the tutorial's schema, all additive: `NOT NULL` on the key columns,
`UNIQUE (type, location)` on `sensors`, explicit `segmentby`/`orderby`, and a unique
`(sensor_id, time)` index so a reading can't be stored twice. The tutorial's queries run unchanged.

## Simulated values

Instead of the tutorial's uniform `random()`, readings follow a simple model (seeded, so
values are reproducible for a given time window):

| Signal | Model |
|---|---|
| temperature (°C) | floor 21.0 / ceiling 24.0 base, +0.5 for type `b`, ±3 °C daily cycle peaking ~3 PM IST, Gaussian noise σ 0.4 |
| cpu (0–1) | 0.25 baseline + up to 0.35 working-hours load (9 AM–7 PM IST), noise σ 0.05, clamped |

So the queries show something: a daily temperature curve, ceiling sensors about 3 °C warmer
than floor sensors, and CPU rising during the working day.

## Run it

Requires Python 3.12+ and the [Tiger CLI](https://www.tigerdata.com/docs/get-started/quickstart/tiger-cli),
logged in with `tiger auth login`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt

.\.venv\Scripts\python simulate.py            # create schema if missing, load 7 days
.\.venv\Scripts\python simulate.py --report   # read-only summary + tutorial queries
```

Options: `--service` (Tiger Cloud service name or ID, default `db-ghw`), `--days` (default 7),
`--seed` (default 42).

The window is `[now − days, now)` aligned to 5 minutes. Running the loader again later adds
only the 5-minute steps since the previous run; readings that already exist are skipped.

### Connection and secrets

The script asks the Tiger CLI for the connection string at runtime
(`tiger db uri <service> --with-password`; the password comes from the OS keyring). The string
stays in memory: it is never printed, logged or written to disk, and connection errors are
reported without the hostname. Nothing secret lives in this repo.

## Sample output

From the run on Mon 12 Oct 2026 (times in IST):

```text
sensors: 4
generated 8064 readings (7 days x 5 min x 4 sensors)
inserted 8064 rows (0 already present)
sensor_data: 8064 rows, 2 chunks, Mon 05 Oct 2026 14:15 IST -> Mon 12 Oct 2026 14:10 IST
```

`python simulate.py --report` (excerpt):

```text
Floor vs ceiling (all readings)
  location | avg_temp_c | min_temp_c | max_temp_c | avg_cpu
  ---------+------------+------------+------------+--------
  ceiling  | 24.25      | 20.11      | 28.68      | 0.343
  floor    | 21.25      | 16.83      | 25.45      | 0.342

3. Query the metadata: the same windows per sensor location  (674 rows, last 6 shown, times in IST)
  location | period           | avg_temp | last_temp | avg_cpu
  ---------+------------------+----------+-----------+--------
  ceiling  | 2026-10-12 13:00 | 26.908   | 27.190    | 0.593
  floor    | 2026-10-12 13:00 | 24.008   | 24.330    | 0.571
  ceiling  | 2026-10-12 13:30 | 27.198   | 27.350    | 0.571
  floor    | 2026-10-12 13:30 | 24.256   | 23.580    | 0.601
  ceiling  | 2026-10-12 14:00 | 27.313   | 26.330    | 0.609
  floor    | 2026-10-12 14:00 | 24.283   | 24.090    | 0.602
```

Query 1 and 2 return 337 thirty-minute windows; query 3 returns 674 (two locations per window).

## License

[MIT](LICENSE)
