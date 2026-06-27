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
                db.upsert_garmin_daily(date_str, stats)
            day_count += 1
        except Exception as e:
            print(f"    Warning: daily stats for {date_str} failed: {e}")
        current += timedelta(days=1)

    print(f"  Garmin daily: {day_count} days processed")


def main():
    # ── Parse command-line arguments ─────────────────────────────────
    # This lets you run: python src/pipeline.py --full
    # for a full historical backfill on the first run.
    parser = argparse.ArgumentParser(description="Health Dashboard ETL Pipeline")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Pull all historical data (use on first run)"
    )
    args = parser.parse_args()

    # ── Date range ───────────────────────────────────────────────────
    if args.full:
        # Pull all data since we started wearing these devices
        whoop_start  = "2025-05-01"   # When Dan got his Whoop
        garmin_start = "2026-04-01"   # When Dan got his Garmin
        print("🔄 Running FULL historical backfill...")
    else:
        # Incremental: last 7 days (catches any late-scoring records too)
        whoop_start  = (date.today() - timedelta(days=7)).isoformat()
        garmin_start = (date.today() - timedelta(days=7)).isoformat()
        print("🔄 Running incremental sync (last 7 days)...")

    # ── Connect ──────────────────────────────────────────────────────
    db     = Database()
    whoop  = WhoopClient()
    garmin = GarminClient()

    # ── Make sure tables exist ───────────────────────────────────────
    db.create_tables()

    # ── Run syncs ────────────────────────────────────────────────────
    run_whoop_sync(whoop, db, start=whoop_start)
    run_garmin_sync(garmin, db, start=garmin_start)

    # ── Done ─────────────────────────────────────────────────────────
    db.close()
    print("\n✅ Pipeline complete!")
    print("\nTo explore your data, open psql and run:")
    print("  psql health_dashboard")
    print("  SELECT date, recovery_score, hrv_rmssd, resting_hr FROM whoop_recovery ORDER BY date DESC LIMIT 10;")


if __name__ == "__main__":
    main()
