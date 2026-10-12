-- The tutorial's three queries, with ORDER BY added so output reads in time order.
-- https://www.tigerdata.com/docs/learn/tutorials/simulate-iot-sensor-data

-- 1. Average temperature and CPU by 30-minute windows
SELECT time_bucket('30 minutes', time) AS period,
       AVG(temperature) AS avg_temp,
       AVG(cpu) AS avg_cpu
FROM sensor_data
GROUP BY period
ORDER BY period;

-- 2. Average and last temperature, average CPU by 30-minute windows
SELECT time_bucket('30 minutes', time) AS period,
       AVG(temperature) AS avg_temp,
       last(temperature, time) AS last_temp,
       AVG(cpu) AS avg_cpu
FROM sensor_data
GROUP BY period
ORDER BY period;

-- 3. Query the metadata: the same windows per sensor location
SELECT sensors.location,
       time_bucket('30 minutes', time) AS period,
       AVG(temperature) AS avg_temp,
       last(temperature, time) AS last_temp,
       AVG(cpu) AS avg_cpu
FROM sensor_data
JOIN sensors ON sensor_data.sensor_id = sensors.id
GROUP BY period, sensors.location
ORDER BY period, sensors.location;
