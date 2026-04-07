-- Omni-Track Database Schema v1.0

-- Metric type registry (auto-populated by agent)
CREATE TABLE IF NOT EXISTS metric_types (
    id           SERIAL PRIMARY KEY,
    name         TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    unit         TEXT,
    category     TEXT NOT NULL CHECK (category IN ('biometric', 'financial', 'behavioral', 'custom')),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- All metric readings (time-series)
CREATE TABLE IF NOT EXISTS metric_readings (
    id              SERIAL PRIMARY KEY,
    metric_type_id  INT REFERENCES metric_types(id),
    value           NUMERIC NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    ingested_at     TIMESTAMPTZ DEFAULT NOW(),
    source_type     TEXT NOT NULL CHECK (source_type IN ('pdf', 'image', 'voice', 'text')),
    source_ref      TEXT,
    notes           TEXT,
    UNIQUE(metric_type_id, timestamp)
);

-- Weekly AI insight log
CREATE TABLE IF NOT EXISTS insights (
    id           SERIAL PRIMARY KEY,
    week_start   DATE UNIQUE NOT NULL,
    content      TEXT NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Configurable safe/reference ranges per metric
CREATE TABLE IF NOT EXISTS safe_ranges (
    id          SERIAL PRIMARY KEY,
    metric_name TEXT UNIQUE NOT NULL,
    min_value   NUMERIC,
    max_value   NUMERIC,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_readings_metric_type      ON metric_readings(metric_type_id);
CREATE INDEX IF NOT EXISTS idx_readings_timestamp         ON metric_readings(timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_metric_ts_desc    ON metric_readings(metric_type_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_metric_types_category      ON metric_types(category);
