"""Populate Omni-Track with realistic test data spanning 30 days."""

import sys
import os
import random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import db

db.init_db()

print("Populating test data...")

# ── Safe ranges ──────────────────────────────────────────────────────────────

safe_ranges = [
    ("blood_pressure_systolic", 90, 120),
    ("blood_pressure_diastolic", 60, 80),
    ("heart_rate", 60, 100),
    ("fasting_blood_sugar", 70, 100),
    ("body_weight", 65, 80),
    ("body_temperature", 36.1, 37.2),
    ("spo2", 95, 100),
    ("sleep_hours", 7, 9),
    ("water_intake_liters", 2.0, 3.5),
    ("steps", 8000, 15000),
]

for name, min_v, max_v in safe_ranges:
    db.execute(
        """INSERT INTO safe_ranges (metric_name, min_value, max_value)
           VALUES (?, ?, ?)
           ON CONFLICT (metric_name) DO UPDATE SET min_value=excluded.min_value, max_value=excluded.max_value""",
        (name, min_v, max_v),
    )

print(f"  ✓ {len(safe_ranges)} safe ranges configured")

# ── Metric types ─────────────────────────────────────────────────────────────

metrics = [
    # (name, display_name, unit, category, base_value, variance, safe_min, safe_max)
    ("blood_pressure_systolic", "BP Systolic", "mmHg", "biometric", 118, 10, 90, 135),
    ("blood_pressure_diastolic", "BP Diastolic", "mmHg", "biometric", 76, 6, 60, 90),
    ("heart_rate", "Heart Rate", "bpm", "biometric", 72, 8, 55, 100),
    ("fasting_blood_sugar", "Fasting Blood Sugar", "mg/dL", "biometric", 92, 12, 70, 110),
    ("body_weight", "Body Weight", "kg", "biometric", 74.5, 0.8, None, None),
    ("body_temperature", "Body Temperature", "°C", "biometric", 36.6, 0.3, None, None),
    ("spo2", "SpO2", "%", "biometric", 97.5, 1.5, 95, 100),
    ("sleep_hours", "Sleep Duration", "hours", "behavioral", 7.2, 1.2, None, None),
    ("water_intake_liters", "Water Intake", "L", "behavioral", 2.5, 0.6, None, None),
    ("steps", "Daily Steps", "steps", "behavioral", 9500, 3000, None, None),
    ("pushups", "Push-ups", "reps", "behavioral", 30, 10, None, None),
    ("running_distance", "Running Distance", "km", "behavioral", 4.0, 1.5, None, None),
    ("monthly_savings", "Monthly Savings", "₹", "financial", 25000, 8000, None, None),
    ("daily_spending", "Daily Spending", "₹", "financial", 850, 400, None, None),
    ("caffeine_cups", "Caffeine Intake", "cups", "behavioral", 2.5, 1.0, None, None),
]

now = datetime.utcnow()
readings_count = 0

for name, display, unit, category, base, var, _, _ in metrics:
    # Create metric type
    db.execute_returning(
        "INSERT OR IGNORE INTO metric_types (name, display_name, unit, category) VALUES (?, ?, ?, ?)",
        (name, display, unit, category),
    )

    # Generate 30 days of data (some metrics daily, some less frequent)
    if name in ("monthly_savings",):
        # Monthly metric — just 1 reading
        ts = (now - timedelta(days=5)).strftime("%Y-%m-%dT09:00:00")
        val = round(base + random.uniform(-var, var), 2)
        db.execute(
            """INSERT OR IGNORE INTO metric_readings (metric_type_id, value, timestamp, source_type, source_ref, notes)
               VALUES ((SELECT id FROM metric_types WHERE name = ?), ?, ?, 'text', 'test', 'Test data')""",
            (name, val, ts),
        )
        readings_count += 1
    elif name in ("pushups", "running_distance"):
        # Every 2-3 days
        for day in range(30):
            if random.random() < 0.4:
                ts = (now - timedelta(days=30 - day, hours=random.randint(6, 20))).strftime("%Y-%m-%dT%H:00:00")
                # Slight upward trend for fitness metrics
                trend = day * 0.15
                val = round(max(0, base + trend + random.uniform(-var, var)), 1)
                db.execute(
                    """INSERT OR IGNORE INTO metric_readings (metric_type_id, value, timestamp, source_type, source_ref, notes)
                       VALUES ((SELECT id FROM metric_types WHERE name = ?), ?, ?, 'text', 'test', 'Test data')""",
                    (name, val, ts),
                )
                readings_count += 1
    else:
        # Daily metrics
        for day in range(30):
            ts = (now - timedelta(days=30 - day, hours=random.randint(6, 10))).strftime("%Y-%m-%dT%H:00:00")
            # Add a slight trend for some metrics
            if name == "body_weight":
                trend = -day * 0.02  # Slight weight loss trend
            elif name == "steps":
                trend = day * 50  # Increasing steps
            elif name == "fasting_blood_sugar":
                trend = -day * 0.1  # Improving blood sugar
            else:
                trend = 0
            val = round(base + trend + random.uniform(-var, var), 1)
            if name in ("steps",):
                val = int(val)
            if name == "spo2":
                val = min(100, val)
            db.execute(
                """INSERT OR IGNORE INTO metric_readings (metric_type_id, value, timestamp, source_type, source_ref, notes)
                   VALUES ((SELECT id FROM metric_types WHERE name = ?), ?, ?, 'text', 'test', 'Test data')""",
                (name, val, ts),
            )
            readings_count += 1

print(f"  ✓ {len(metrics)} metric types created")
print(f"  ✓ {readings_count} readings generated (30 days)")

# ── Sample weekly insight ────────────────────────────────────────────────────

week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
insight = """**Week Summary**

Your blood pressure has remained stable this week, averaging 118/76 mmHg — within the healthy range. \
Fasting blood sugar shows a downward trend (from 95 to 88 mg/dL), which is excellent.

**Notable observations:**
- Daily step count has been climbing steadily, now averaging ~11,000 steps/day — great consistency.
- Sleep duration dipped below 7 hours on two nights. Those nights correlate with higher next-day heart rates.
- Water intake has been inconsistent — aim for a minimum of 2.5L daily.

**Recommendation for next week:** Try to maintain your sleep above 7 hours consistently. Consider setting a \
bedtime alarm. The correlation between your sleep and next-day heart rate suggests recovery quality is affected."""

db.execute(
    "INSERT OR REPLACE INTO insights (week_start, content) VALUES (?, ?)",
    (week_start, insight),
)
print(f"  ✓ Weekly insight generated for week of {week_start}")

print("\n✅ Test data population complete!")
print(f"   Database: {db.DB_PATH}")
