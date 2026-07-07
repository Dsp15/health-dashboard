"""
pipeline.py

ETL (Extract, Transform, Load) pipeline for the health dashboard.

ETL means:
  Extract  — pull data from APIs (Whoop, Garmin)
  Transform — clean and reshape the data into our schema
  Load     — insert it into the PostgreSQL database

How syncing works:
  - First run: pulls ALL historical data (full backfill)
  - Subsequent runs: pulls only the last 7 days (incremental sync)

This pattern is common in data engineering. You don't re-pull
everything every day because it's slow and hits API rate limits.
Instead, you keep track of what you have and only fetch new stuff.

Run it:
    python src/pipeline.py

For a full historical backfill:
    python src/pipeline.py --full
"""

import argparse
from datetime import date, datetime, timedelta

from whoop_client import WhoopClient
from garmin_client import GarminClient
from weather_client import get_weather_range, get_air_quality_range
from database import Database


def run_whoop_sync(whoop: WhoopClient, db: Database, start: str):
    """
    Pull all Whoop data streams from `start` date and write to the database.
    Whoop data comes in as a list of records from the API.
    """
    print(f"\n── Whoop sync (from {start}) ──────────────────────────────")

    print("  Fetching recovery data...")
    recovery = whoop.get_all_recovery(start=f"{start}T00:00:00.000Z")
    db.upsert_whoop_recovery(recovery)

    print("  Fetching sleep data...")
    sleep = whoop.get_all_sleep(start=f"{start}T00:00:00.000Z")
    db.upsert_whoop_sleep(sleep)

    print("  Fetching cycles data...")
    cycles = whoop.get_all_cycles(start=f"{start}T00:00:00.000Z")
    db.upsert_whoop_cycles(cycles)


def run_garmin_sync(garmin: GarminClient, db: Database, start: str):
    """
    Pull all Garmin data streams from `start` to today and write to the database.
    Garmin data is fetched one day at a time or by date range depending on the endpoint.
    """
    print(f"\n── Garmin sync (from {start}) ──────────────────────────────")
    today = date.today().isoformat()

    # Activities — fetched all at once by date range
    print("  Fetching activities...")
    activities = garmin.get_activities_by_date(start, today)
    db.upsert_garmin_activities(activities)

    # Daily stats — must be fetched one day at a time
    print("  Fetching daily stats (one day at a time)...")
    current = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = date.today()
    day_count = 0

    while current <= end_date:
        date_str = current.isoformat()

        try:
            stats = garmin.get_daily_stats(date_str)
            if stats:
                # Fetch training readiness alongside daily stats
                tr_score = None
                try:
                    tr = garmin.get_training_readiness(date_str)
                    if isinstance(tr, list) and tr:
                        tr = tr[0]
                    if isinstance(tr, dict):
                        tr_score = tr.get("score")
                except Exception:
                    pass
                db.upsert_garmin_daily(date_str, stats, training_readiness=tr_score)
            day_count += 1
        except Exception as e:
            print(f"    Warning: daily stats for {date_str} failed: {e}")

        try:
            sleep_data = garmin.get_sleep(date_str)
            if sleep_data:
                db.upsert_garmin_sleep(date_str, sleep_data)
        except Exception:
            pass  # Sleep not available for every day

        try:
            hrv_data = garmin.get_hrv_data(date_str)
            if hrv_data:
                db.upsert_garmin_hrv(date_str, hrv_data)
        except Exception:
            pass  # HRV not available for every day

        current += timedelta(days=1)

    print(f"  Garmin daily: {day_count} days processed")


def run_weather_sync(db: Database, start: str):
    """
    Pull weather and air quality data for a date range and store it.

    Uses Open-Meteo (free, no API key). Automatically handles the split
    between historical archive data and recent forecast data.
    """
    print(f"\n── Weather sync (from {start}) ──────────────────────────────")
    today = date.today().isoformat()

    print("  Fetching weather data...")
    weather = get_weather_range(start, today)
    if weather:
        db.upsert_weather(weather)

    print("  Fetching air quality data...")
    air_quality = get_air_quality_range(start, today)
    if air_quality:
        db.upsert_air_quality(air_quality)


def main():
    # ── Parse command-line arguments ─────────────────────────────────
    parser = argparse.ArgumentParser(description="Health Dashboard ETL Pipeline")
    parser.add_argument("--full",         action="store_true", help="Pull all historical data")
    parser.add_argument("--garmin-only",  action="store_true", help="Only sync Garmin data")
    parser.add_argument("--whoop-only",   action="store_true", help="Only sync Whoop data")
    parser.add_argument("--weather-only", action="store_true", help="Only sync weather data")
    args = parser.parse_args()

    # ── Date range ───────────────────────────────────────────────────
    if args.full:
        whoop_start   = "2025-05-01"   # When Dan got his Whoop
        garmin_start  = "2026-04-01"   # When Dan got his Garmin
        weather_start = "2026-04-01"   # Match Garmin start for correlation
        print("🔄 Running FULL historical backfill...")
    else:
        whoop_start   = (date.today() - timedelta(days=7)).isoformat()
        garmin_start  = (date.today() - timedelta(days=7)).isoformat()
        weather_start = (date.today() - timedelta(days=7)).isoformat()
        print("🔄 Running incremental sync (last 7 days)...")

    # ── Connect ──────────────────────────────────────────────────────
    db = Database()
    db.create_tables()

    # ── Run syncs ────────────────────────────────────────────────────
    if args.weather_only:
        run_weather_sync(db, start=weather_start)
    else:
        if not args.garmin_only:
            whoop  = WhoopClient()
            run_whoop_sync(whoop, db, start=whoop_start)
        if not args.whoop_only:
            garmin = GarminClient()
            run_garmin_sync(garmin, db, start=garmin_start)
        run_weather_sync(db, start=weather_start)

    # ── Done ─────────────────────────────────────────────────────────
    db.close()
    print("\n✅ Pipeline complete!")


if __name__ == "__main__":
    main()
