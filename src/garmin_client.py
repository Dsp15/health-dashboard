"""
garmin_client.py

Handles all communication with Garmin Connect via the python-garminconnect library.

Unlike Whoop (which uses OAuth), Garmin uses email/password authentication.
The library handles token caching automatically — tokens are saved to
~/.garminconnect/ so you only log in once.

Key data we can pull:
  - Daily stats (steps, calories, stress, body battery)
  - Sleep data (stages, HRV, SpO2, respiration)
  - Heart rate (resting HR, HRV status)
  - Activities/workouts (type, duration, distance, HR zones)
  - Body composition (weight, body fat)
  - Training readiness and training load

Note: Dan does not wear the device during work hours, so daytime metrics
(steps, active calories, stress) will show gaps and should not be compared
to population averages.

Docs: https://github.com/cyberjunky/python-garminconnect
"""

import os
from datetime import date, timedelta
from garminconnect import Garmin
from dotenv import load_dotenv

load_dotenv()

# Where the library saves auth tokens automatically
GARMIN_TOKEN_PATH = "~/.garminconnect"


class GarminClient:
    """
    A simple wrapper around the python-garminconnect library.

    Usage:
        client = GarminClient()
        sleep = client.get_sleep("2026-06-20")
        stats = client.get_daily_stats("2026-06-20")
    """

    def __init__(self):
        email    = os.getenv("GARMIN_EMAIL")
        password = os.getenv("GARMIN_PASSWORD")

        if not email or not password:
            raise ValueError(
                "Missing GARMIN_EMAIL or GARMIN_PASSWORD in your .env file."
            )

        self.client = Garmin(
            email=email,
            password=password,
            prompt_mfa=lambda: input("Garmin MFA code: "),
        )

        self._authenticate()

    def _authenticate(self):
        """
        Try loading saved tokens first. If that fails, do a full login.
        Garmin tokens last a long time so you rarely need to re-enter credentials.
        """
        try:
            print("Loading saved Garmin tokens...")
            self.client.login(GARMIN_TOKEN_PATH)
            print("Garmin authenticated via saved tokens.\n")
        except Exception:
            print("No saved tokens — logging in with credentials...")
            self.client.login()
            self.client.garth.dump(GARMIN_TOKEN_PATH)
            print("Garmin authenticated and tokens saved.\n")

    # ── Daily Stats ────────────────────────────────────────────────────────────

    def get_daily_stats(self, date_str: str) -> dict:
        """
        Get overall daily stats for a given date.

        Includes: total steps, active calories, resting calories, stress score,
        body battery (Garmin's energy/readiness metric), floors climbed.

        Note: Steps and active calories will be lower than average due to
        not wearing the device during work hours.

        Args:
            date_str: Date in "YYYY-MM-DD" format, e.g. "2026-06-20"
        """
        return self.client.get_stats(date_str)

    def get_daily_stats_range(self, start: str, end: str) -> list:
        """
        Get daily stats for a range of dates.

        Args:
            start: Start date "YYYY-MM-DD"
            end:   End date "YYYY-MM-DD"
        """
        return self.client.get_stats_and_body(start, end)

    # ── Sleep ──────────────────────────────────────────────────────────────────

    def get_sleep(self, date_str: str) -> dict:
        """
        Get sleep data for a given date.

        Includes: sleep stages (light, deep, REM, awake), sleep score,
        respiration rate, SpO2, and HRV during sleep.

        Garmin's sleep scoring is independent of Whoop's — comparing the two
        is one of the interesting analysis opportunities in this project.
        """
        return self.client.get_sleep_data(date_str)

    # ── Heart Rate ─────────────────────────────────────────────────────────────

    def get_heart_rates(self, date_str: str) -> dict:
        """
        Get heart rate data for a given date.

        Includes: resting heart rate, HR readings throughout the day.
        Note: there will be gaps during work hours when device isn't worn.
        """
        return self.client.get_heart_rates(date_str)

    def get_hrv_data(self, date_str: str) -> dict:
        """
        Get HRV (Heart Rate Variability) status for a given date.

        Garmin measures HRV during sleep (similar to Whoop).
        Comparing Garmin HRV vs Whoop HRV for the same night is a
        key analysis opportunity — they use different measurement methods.
        """
        return self.client.get_hrv_data(date_str)

    # ── Activities ─────────────────────────────────────────────────────────────

    def get_activities(self, start: int = 0, limit: int = 20) -> list:
        """
        Get a list of activities (workouts).

        Includes: activity type, start time, duration, distance, average HR,
        max HR, calories, and training effect.

        Args:
            start: Offset for pagination (0 = most recent)
            limit: Number of activities to return
        """
        return self.client.get_activities(start, limit)

    def get_activities_by_date(self, start: str, end: str) -> list:
        """
        Get all activities between two dates.

        Args:
            start: Start date "YYYY-MM-DD"
            end:   End date "YYYY-MM-DD"
        """
        return self.client.get_activities_by_date(start, end)

    # ── Body Battery ───────────────────────────────────────────────────────────

    def get_body_battery(self, start: str, end: str) -> list:
        """
        Get Garmin's Body Battery readings for a date range.

        Body Battery is Garmin's energy reserve metric (0-100).
        Similar concept to Whoop's recovery score but calculated differently.
        Comparing Body Battery vs Whoop Recovery is an interesting analysis.

        Args:
            start: Start date "YYYY-MM-DD"
            end:   End date "YYYY-MM-DD"
        """
        return self.client.get_body_battery(start, end)

    # ── Training ───────────────────────────────────────────────────────────────

    def get_training_readiness(self, date_str: str) -> dict:
        """
        Get Garmin's Training Readiness score for a given date.

        Training Readiness combines sleep, HRV, recovery time, and acute load
        into a single score. Similar concept to Whoop's recovery but with
        more emphasis on training history.
        """
        return self.client.get_training_readiness(date_str)

    def get_training_status(self, date_str: str) -> dict:
        """
        Get Garmin's Training Status (detraining, maintaining, improving, etc.)
        and current training load.
        """
        return self.client.get_training_status(date_str)
