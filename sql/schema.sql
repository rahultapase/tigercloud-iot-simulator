-- Schema for the simulated IoT dataset.
-- Based on Tiger Data's "Simulate an IoT sensor dataset" tutorial:
-- https://www.tigerdata.com/docs/learn/tutorials/simulate-iot-sensor-data
-- Idempotent: safe to run more than once. Creates objects only; never drops or alters.

-- Relational metadata: one row per physical sensor.
CREATE TABLE IF NOT EXISTS sensors (
  id       SERIAL PRIMARY KEY,
  type     VARCHAR(50) NOT NULL,
  location VARCHAR(50) NOT NULL,
  UNIQUE (type, location)                 -- re-running the seed can't duplicate sensors
);

-- Time-series readings. WITH (tsdb.hypertable) partitions on the first TIMESTAMPTZ
-- column (time) and adds a columnstore policy automatically.
CREATE TABLE IF NOT EXISTS sensor_data (
  time        TIMESTAMPTZ NOT NULL,
  sensor_id   INTEGER NOT NULL REFERENCES sensors (id),
  temperature DOUBLE PRECISION,
  cpu         DOUBLE PRECISION
) WITH (
  tsdb.hypertable,
  tsdb.segmentby = 'sensor_id',           -- group compressed rows per sensor
  tsdb.orderby   = 'time DESC'
);

-- One reading per sensor per timestamp; also serves "latest readings for sensor X".
CREATE UNIQUE INDEX IF NOT EXISTS sensor_data_sensor_id_time_idx
  ON sensor_data (sensor_id, time DESC);

-- The tutorial's four sensors.
INSERT INTO sensors (type, location)
VALUES ('a', 'floor'), ('a', 'ceiling'), ('b', 'floor'), ('b', 'ceiling')
ON CONFLICT (type, location) DO NOTHING;
