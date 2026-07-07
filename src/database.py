"""
database.py

Manages the PostgreSQL database connection and schema for the health dashboard.

The schema stores data from both Whoop and Garmin in separate tables,
joined by date when needed for analysis.

Why PostgreSQL over SQLite?
  - Same database Dan's company uses in production
  - Better performance at scale
  - Richer data types (e.g. JSONB for flexible storage)
  - Industry-standard — directly transferable skill

Tables:
  whoop_recovery    — daily recovery score, HRV, resting HR
  whoop_sleep       — nightly sleep stages and performance
  whoop_cycles      — daily strain cycles
  whoop_workouts    — Whoop workout records
  garmin_activities — Garmin workout records
  garmin_daily      — daily stats (steps, body battery, stress)
  garmin_sleep      — Garmin sleep scores
  garmin_hrv        — Garmin HRV readings

Usage:
    from database import Database
    db = Database()
    db.create_tables()
"""

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


class Database:
    """
    Handles all database operations.

    psycopg2 is the standard Python library for connecting to PostgreSQL.
    It translates Python dicts and lists into SQL queries.
    """

    def __init__(self):
        self.conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "health_dashboard"),
            user=os.getenv("DB_USER", "danmac"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        self.conn.autocommit = True
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        print("Connected to PostgreSQL health_dashboard database.")

    def create_tables(self):
        """
        Create all tables if they don't already exist.
        'IF NOT EXISTS' means this is safe to run multiple times —
        it won't wipe your data if tables are already there.
        """
        print("Creating tables...")

        # ── Whoop Tables ───────────────────────────────────────────
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS whoop_recovery (
                id              SERIAL PRIMARY KEY,
                cycle_id        BIGINT UNIQUE,
                date            DATE,
                created_at      TIMESTAMPTZ,
                recovery_score  FLOAT,
                hrv_rmssd       FLOAT,
                resting_hr      FLOAT,
                spo2_pct        FLOAT,
                skin_temp_c     FLOAT,
                score_state     TEXT,
                raw             JSONB
            );
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS whoop_sleep (
                id                          SERIAL PRIMARY KEY,
                sleep_id                    TEXT UNIQUE,
                cycle_id                    BIGINT,
                date                        DATE,
                start_time                  TIMESTAMPTZ,
                end_time                    TIMESTAMPTZ,
                is_nap                      BOOLEAN,
                score_state                 TEXT,
                total_in_bed_hours          FLOAT,
                light_sleep_hours           FLOAT,
                rem_sleep_hours             FLOAT,
                deep_sleep_hours            FLOAT,
                awake_hours                 FLOAT,
                sleep_performance_pct       FLOAT,
                sleep_consistency_pct       FLOAT,
                sleep_efficiency_pct        FLOAT,
                respiratory_rate            FLOAT,
                raw                         JSONB
            );
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS whoop_cycles (
                id              SERIAL PRIMARY KEY,
                cycle_id        BIGINT UNIQUE,
                date            DATE,
                start_time      TIMESTAMPTZ,
                end_time        TIMESTAMPTZ,
                strain          FLOAT,
                avg_hr          INTEGER,
                max_hr          INTEGER,
                kilojoules      FLOAT,
                score_state     TEXT,
                raw             JSONB
            );
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS whoop_workouts (
                id              SERIAL PRIMARY KEY,
                workout_id      TEXT UNIQUE,
                cycle_id        BIGINT,
                date            DATE,
                start_time      TIMESTAMPTZ,
                end_time        TIMESTAMPTZ,
                sport_name      TEXT,
                strain          FLOAT,
                avg_hr          INTEGER,
                max_hr          INTEGER,
                kilojoules      FLOAT,
                score_state     TEXT,
                raw             JSONB
            );
        """)

        # ── Garmin Tables ──────────────────────────────────────────
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS garmin_activities (
                id              SERIAL PRIMARY KEY,
                activity_id     BIGINT UNIQUE,
                date            DATE,
                start_time      TIMESTAMPTZ,
                sport_type      TEXT,
                name            TEXT,
                duration_secs   FLOAT,
                distance_m      FLOAT,
                avg_hr          FLOAT,
                max_hr          FLOAT,
                calories        FLOAT,
                raw             JSONB
            );
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS garmin_daily (
                id                  SERIAL PRIMARY KEY,
                date                DATE UNIQUE,
                total_steps         INTEGER,
                active_calories     FLOAT,
                resting_calories    FLOAT,
                resting_hr          INTEGER,
                avg_stress          INTEGER,
                body_battery_max    INTEGER,
                body_battery_min    INTEGER,
                floors_ascended     FLOAT,
                training_readiness  INTEGER,
                raw                 JSONB
            );
        """)
        # Add training_readiness column to existing tables that predate this field
        self.cursor.execute("""
            ALTER TABLE garmin_daily
            ADD COLUMN IF NOT EXISTS training_readiness INTEGER;
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS garmin_sleep (
                id                      SERIAL PRIMARY KEY,
                date                    DATE UNIQUE,
                sleep_score             INTEGER,
                total_sleep_hours       FLOAT,
                deep_sleep_hours        FLOAT,
                rem_sleep_hours         FLOAT,
                light_sleep_hours       FLOAT,
                awake_hours             FLOAT,
                avg_respiration         FLOAT,
                avg_spo2                FLOAT,
                raw                     JSONB
            );
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS garmin_hrv (
                id              SERIAL PRIMARY KEY,
                date            DATE UNIQUE,
                weekly_avg_ms   FLOAT,
                last_night_ms   FLOAT,
                status          TEXT,
                raw             JSONB
            );
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS weather_daily (
                id              SERIAL PRIMARY KEY,
                date            DATE UNIQUE,
                temp_max        FLOAT,
                temp_min        FLOAT,
                temp_mean       FLOAT,
                humidity        FLOAT,
                precipitation   FLOAT,
                wind_speed      FLOAT,
                uv_index        FLOAT,
                weather_code    INTEGER,
                pm25            FLOAT,
                pm10            FLOAT,
                aqi_category    TEXT
            );
        """)

        print("All tables created successfully.\n")

    # ── Upsert Methods ─────────────────────────────────────────────────────────
    # "Upsert" = INSERT if new, UPDATE if already exists.
    # This means we can safely run the pipeline multiple times without
    # creating duplicate rows. The ON CONFLICT clause handles this.

    def upsert_whoop_recovery(self, records: list):
        """Save Whoop recovery records to the database."""
        count = 0
        for r in records:
            if r.get("score_state") != "SCORED":
                continue
            score = r.get("score", {})
            try:
                self.cursor.execute("""
                    INSERT INTO whoop_recovery
                        (cycle_id, created_at, recovery_score, hrv_rmssd,
                         resting_hr, spo2_pct, skin_temp_c, score_state, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (cycle_id) DO UPDATE SET
                        recovery_score = EXCLUDED.recovery_score,
                        hrv_rmssd      = EXCLUDED.hrv_rmssd,
                        resting_hr     = EXCLUDED.resting_hr,
                        raw            = EXCLUDED.raw
                """, (
                    r.get("cycle_id"),
                    r.get("created_at"),
                    score.get("recovery_score"),
                    score.get("hrv_rmssd_milli"),
                    score.get("resting_heart_rate"),
                    score.get("spo2_percentage"),
                    score.get("skin_temp_celsius"),
                    r.get("score_state"),
                    psycopg2.extras.Json(r),
                ))
                count += 1
            except Exception as e:
                print(f"  Error inserting recovery {r.get('cycle_id')}: {e}")
        print(f"  Whoop recovery: {count} records upserted")

    def upsert_whoop_sleep(self, records: list):
        """Save Whoop sleep records to the database."""
        count = 0
        for r in records:
            if r.get("score_state") != "SCORED":
                continue
            score  = r.get("score", {})
            stages = score.get("stage_summary", {})
            try:
                self.cursor.execute("""
                    INSERT INTO whoop_sleep
                        (sleep_id, cycle_id, start_time, end_time, is_nap,
                         score_state, total_in_bed_hours, light_sleep_hours,
                         rem_sleep_hours, deep_sleep_hours, awake_hours,
                         sleep_performance_pct, sleep_consistency_pct,
                         sleep_efficiency_pct, respiratory_rate, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (sleep_id) DO UPDATE SET
                        sleep_performance_pct = EXCLUDED.sleep_performance_pct,
                        raw                   = EXCLUDED.raw
                """, (
                    r.get("id"),
                    r.get("cycle_id"),
                    r.get("start"),
                    r.get("end"),
                    r.get("nap", False),
                    r.get("score_state"),
                    round(stages.get("total_in_bed_time_milli", 0) / 3_600_000, 2),
                    round(stages.get("total_light_sleep_time_milli", 0) / 3_600_000, 2),
                    round(stages.get("total_rem_sleep_time_milli", 0) / 3_600_000, 2),
                    round(stages.get("total_slow_wave_sleep_time_milli", 0) / 3_600_000, 2),
                    round(stages.get("total_awake_time_milli", 0) / 3_600_000, 2),
                    score.get("sleep_performance_percentage"),
                    score.get("sleep_consistency_percentage"),
                    score.get("sleep_efficiency_percentage"),
                    score.get("respiratory_rate"),
                    psycopg2.extras.Json(r),
                ))
                count += 1
            except Exception as e:
                print(f"  Error inserting sleep {r.get('id')}: {e}")
        print(f"  Whoop sleep: {count} records upserted")

    def upsert_whoop_cycles(self, records: list):
        """Save Whoop cycle records to the database."""
        count = 0
        for r in records:
            if r.get("score_state") != "SCORED":
                continue
            score = r.get("score", {})
            try:
                self.cursor.execute("""
                    INSERT INTO whoop_cycles
                        (cycle_id, start_time, end_time, strain, avg_hr,
                         max_hr, kilojoules, score_state, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (cycle_id) DO UPDATE SET
                        strain = EXCLUDED.strain,
                        raw    = EXCLUDED.raw
                """, (
                    r.get("id"),
                    r.get("start"),
                    r.get("end"),
                    score.get("strain"),
                    score.get("average_heart_rate"),
                    score.get("max_heart_rate"),
                    score.get("kilojoule"),
                    r.get("score_state"),
                    psycopg2.extras.Json(r),
                ))
                count += 1
            except Exception as e:
                print(f"  Error inserting cycle {r.get('id')}: {e}")
        print(f"  Whoop cycles: {count} records upserted")

    def upsert_garmin_activities(self, activities: list):
        """Save Garmin activity records to the database."""
        count = 0
        for a in activities:
            try:
                self.cursor.execute("""
                    INSERT INTO garmin_activities
                        (activity_id, start_time, sport_type, name,
                         duration_secs, distance_m, avg_hr, max_hr, calories, raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (activity_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        raw  = EXCLUDED.raw
                """, (
                    a.get("activityId"),
                    a.get("startTimeLocal"),
                    a.get("activityType", {}).get("typeKey"),
                    a.get("activityName"),
                    a.get("duration"),
                    a.get("distance"),
                    a.get("averageHR"),
                    a.get("maxHR"),
                    a.get("calories"),
                    psycopg2.extras.Json(a),
                ))
                count += 1
            except Exception as e:
                print(f"  Error inserting activity {a.get('activityId')}: {e}")
        print(f"  Garmin activities: {count} records upserted")

    def upsert_garmin_daily(self, date_str: str, stats: dict, training_readiness: int = None):
        """Save Garmin daily stats for one date."""
        try:
            self.cursor.execute("""
                INSERT INTO garmin_daily
                    (date, total_steps, active_calories, resting_calories,
                     resting_hr, avg_stress, floors_ascended, training_readiness, raw)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (date) DO UPDATE SET
                    total_steps         = EXCLUDED.total_steps,
                    active_calories     = EXCLUDED.active_calories,
                    resting_hr          = EXCLUDED.resting_hr,
                    training_readiness  = EXCLUDED.training_readiness,
                    raw                 = EXCLUDED.raw
            """, (
                date_str,
                stats.get("totalSteps"),
                stats.get("activeKilocalories"),
                stats.get("bmrKilocalories"),
                stats.get("restingHeartRate"),
                stats.get("averageStressLevel"),
                stats.get("floorsAscended"),
                training_readiness,
                psycopg2.extras.Json(stats),
            ))
        except Exception as e:
            print(f"  Error inserting daily stats {date_str}: {e}")

    def upsert_garmin_sleep(self, date_str: str, sleep_data: dict):
        """Save Garmin sleep data for one night."""
        try:
            daily = sleep_data.get("dailySleepDTO", {})
            if not daily:
                return
            scores = daily.get("sleepScores", {})
            overall = scores.get("overall", {}) if isinstance(scores, dict) else {}
            sleep_score = overall.get("value") if isinstance(overall, dict) else None

            self.cursor.execute("""
                INSERT INTO garmin_sleep
                    (date, sleep_score, total_sleep_hours, deep_sleep_hours,
                     rem_sleep_hours, light_sleep_hours, awake_hours,
                     avg_respiration, avg_spo2, raw)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (date) DO UPDATE SET
                    sleep_score       = EXCLUDED.sleep_score,
                    total_sleep_hours = EXCLUDED.total_sleep_hours,
                    deep_sleep_hours  = EXCLUDED.deep_sleep_hours,
                    rem_sleep_hours   = EXCLUDED.rem_sleep_hours,
                    raw               = EXCLUDED.raw
            """, (
                date_str,
                sleep_score,
                # Total sleep: use Garmin's reported total, or sum stages as fallback.
                # Use (x or 0) not get(key, 0) — Garmin sometimes returns null explicitly.
                round(((daily.get("sleepTimeSeconds") or 0) or
                       ((daily.get("deepSleepSeconds")  or 0) +
                        (daily.get("lightSleepSeconds") or 0) +
                        (daily.get("remSleepSeconds")   or 0))) / 3600, 2),
                round((daily.get("deepSleepSeconds")  or 0) / 3600, 2),
                round((daily.get("remSleepSeconds")   or 0) / 3600, 2),
                round((daily.get("lightSleepSeconds") or 0) / 3600, 2),
                round((daily.get("awakeSleepSeconds") or 0) / 3600, 2),
                daily.get("averageRespirationValue"),
                daily.get("averageSpO2Value"),
                psycopg2.extras.Json(sleep_data),
            ))
        except Exception as e:
            print(f"  Error inserting Garmin sleep {date_str}: {e}")

    def upsert_garmin_hrv(self, date_str: str, hrv_data: dict):
        """Save Garmin HRV summary for one day."""
        try:
            summary = hrv_data.get("hrvSummary", {})
            if not summary:
                return
            weekly = summary.get("weeklyAvg")
            last   = summary.get("lastNight")
            self.cursor.execute("""
                INSERT INTO garmin_hrv
                    (date, weekly_avg_ms, last_night_ms, status, raw)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (date) DO UPDATE SET
                    weekly_avg_ms = EXCLUDED.weekly_avg_ms,
                    last_night_ms = EXCLUDED.last_night_ms,
                    status        = EXCLUDED.status,
                    raw           = EXCLUDED.raw
            """, (
                date_str,
                weekly,
                last,
                summary.get("status"),
                psycopg2.extras.Json(hrv_data),
            ))
        except Exception as e:
            print(f"  Error inserting Garmin HRV {date_str}: {e}")

    def upsert_weather(self, records: list):
        """Save weather records (temperature, humidity, UV, precipitation) for a date range."""
        count = 0
        for r in records:
            try:
                self.cursor.execute("""
                    INSERT INTO weather_daily
                        (date, temp_max, temp_min, temp_mean, humidity,
                         precipitation, wind_speed, uv_index, weather_code)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
                        temp_max      = EXCLUDED.temp_max,
                        temp_min      = EXCLUDED.temp_min,
                        temp_mean     = EXCLUDED.temp_mean,
                        humidity      = EXCLUDED.humidity,
                        precipitation = EXCLUDED.precipitation,
                        wind_speed    = EXCLUDED.wind_speed,
                        uv_index      = EXCLUDED.uv_index,
                        weather_code  = EXCLUDED.weather_code
                """, (
                    r["date"],
                    r.get("temp_max"),
                    r.get("temp_min"),
                    r.get("temp_mean"),
                    r.get("humidity"),
                    r.get("precipitation"),
                    r.get("wind_speed"),
                    r.get("uv_index"),
                    r.get("weather_code"),
                ))
                count += 1
            except Exception as e:
                print(f"  Error inserting weather {r.get('date')}: {e}")
        print(f"  Weather: {count} days upserted")

    def upsert_air_quality(self, records: list):
        """Save air quality records (PM2.5, PM10) for a date range."""
        count = 0
        for r in records:
            try:
                self.cursor.execute("""
                    INSERT INTO weather_daily (date, pm25, pm10, aqi_category)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
                        pm25         = EXCLUDED.pm25,
                        pm10         = EXCLUDED.pm10,
                        aqi_category = EXCLUDED.aqi_category
                """, (
                    r["date"],
                    r.get("pm25"),
                    r.get("pm10"),
                    r.get("aqi_category"),
                ))
                count += 1
            except Exception as e:
                print(f"  Error inserting air quality {r.get('date')}: {e}")
        print(f"  Air quality: {count} days upserted")

    def close(self):
        """Close the database connection."""
        self.cursor.close()
        self.conn.close()
