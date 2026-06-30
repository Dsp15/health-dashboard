"""
app.py

Flask web server for the Health Dashboard.

Architecture:
  - Flask serves two HTML pages: /daily and /training
  - API endpoints query PostgreSQL and return JSON for the charts
  - Flask-SocketIO handles WebSocket connections for live sync

Why Flask?
  - Same Python you already know — no new language to learn
  - Lightweight and fast to get running
  - Industry standard for Python web APIs

Why WebSockets?
  - Normal HTTP: browser asks → server answers → connection closes
  - WebSocket: connection stays open, server can PUSH data to browser
  - When you click "Sync Now", the server fetches new data and pushes
    a notification back to the browser to refresh the charts — no page reload

Run it:
    cd health-dashboard
    python src/app.py

Then open: http://localhost:5000
"""

import os
import sys
from datetime import date, timedelta

from flask import Flask, render_template, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ── App Setup ──────────────────────────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-health-dashboard")

# async_mode='threading' works without installing extra async libraries
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")


# ── Database Helper ────────────────────────────────────────────────────────────

def query(sql, params=None):
    """
    Run a SQL query and return results as a list of plain dicts.

    We open and close a connection per request. For a personal dashboard
    with one user this is perfectly fine. A production app would use
    a connection pool (e.g. psycopg2.pool or SQLAlchemy).
    """
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "health_dashboard"),
        user=os.getenv("DB_USER", "danmac"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or [])
            rows = cur.fetchall()
            # Convert to plain dicts so we can serialize dates to strings
            result = []
            for row in rows:
                d = dict(row)
                for k, v in d.items():
                    if hasattr(v, "isoformat"):
                        d[k] = v.isoformat()
                result.append(d)
            return result
    finally:
        conn.close()


# ── Page Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("daily"))


@app.route("/daily")
def daily():
    return render_template("daily.html")


@app.route("/training")
def training():
    return render_template("training.html")


# ── API: Daily Health ──────────────────────────────────────────────────────────

@app.route("/api/today")
def api_today():
    """Latest recovery and sleep snapshot for the stat cards at the top."""
    recovery = query("""
        SELECT recovery_score, hrv_rmssd, resting_hr, spo2_pct,
               created_at::date AS date
        FROM whoop_recovery
        ORDER BY created_at DESC
        LIMIT 1
    """)
    sleep = query("""
        SELECT total_in_bed_hours, deep_sleep_hours, rem_sleep_hours,
               light_sleep_hours, sleep_performance_pct, start_time
        FROM whoop_sleep
        WHERE is_nap = false
        ORDER BY start_time DESC
        LIMIT 1
    """)
    return jsonify({
        "recovery": recovery[0] if recovery else {},
        "sleep":    sleep[0]    if sleep    else {},
    })


@app.route("/api/recovery")
def api_recovery():
    """Last 90 days of recovery scores, HRV, and resting HR."""
    return jsonify(query("""
        SELECT
            created_at::date        AS date,
            recovery_score,
            hrv_rmssd,
            resting_hr,
            spo2_pct
        FROM whoop_recovery
        WHERE created_at >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY created_at ASC
    """))


@app.route("/api/sleep")
def api_sleep():
    """Last 90 days of sleep data — stages, performance, bedtime."""
    return jsonify(query("""
        SELECT
            start_time::date        AS date,
            start_time,
            end_time,
            total_in_bed_hours,
            light_sleep_hours,
            rem_sleep_hours,
            deep_sleep_hours,
            awake_hours,
            sleep_performance_pct,
            sleep_efficiency_pct
        FROM whoop_sleep
        WHERE start_time >= CURRENT_DATE - INTERVAL '90 days'
          AND is_nap = false
        ORDER BY start_time ASC
    """))


# ── API: Training ──────────────────────────────────────────────────────────────

@app.route("/api/activities")
def api_activities():
    """All Garmin activities joined with next-day Whoop recovery."""
    return jsonify(query("""
        SELECT
            a.start_time::date          AS date,
            a.sport_type,
            a.name,
            ROUND(a.duration_secs / 60) AS duration_mins,
            a.avg_hr,
            ROUND(a.distance_m / 1000.0, 1) AS distance_km,
            a.calories,
            r.recovery_score            AS next_day_recovery,
            r.hrv_rmssd                 AS next_day_hrv
        FROM garmin_activities a
        LEFT JOIN whoop_recovery r
            ON r.created_at::date = a.start_time::date + 1
        ORDER BY a.start_time ASC
    """))


@app.route("/api/weekly_load")
def api_weekly_load():
    """Weekly training volume — sessions, hours, average next-day recovery."""
    return jsonify(query("""
        SELECT
            DATE_TRUNC('week', start_time)::date    AS week,
            COUNT(*)                                AS sessions,
            ROUND(SUM(duration_secs) / 3600.0, 1)  AS total_hours,
            STRING_AGG(DISTINCT sport_type, ', ')   AS sports
        FROM garmin_activities
        GROUP BY DATE_TRUNC('week', start_time)
        ORDER BY week ASC
    """))


@app.route("/api/sport_breakdown")
def api_sport_breakdown():
    """Hours and sessions per sport type for the donut chart."""
    return jsonify(query("""
        SELECT
            sport_type,
            COUNT(*)                                AS sessions,
            ROUND(SUM(duration_secs) / 3600.0, 1)  AS total_hours
        FROM garmin_activities
        GROUP BY sport_type
        ORDER BY total_hours DESC
    """))


@app.route("/api/recovery_timeline")
def api_recovery_timeline():
    """
    Recovery scores around the half ironman (Jun 14) —
    shows how long it took to bounce back.
    """
    return jsonify(query("""
        SELECT
            created_at::date    AS date,
            recovery_score,
            hrv_rmssd
        FROM whoop_recovery
        WHERE created_at::date BETWEEN '2026-06-10' AND '2026-06-29'
        ORDER BY created_at ASC
    """))


# ── WebSocket Events ───────────────────────────────────────────────────────────

@socketio.on("connect")
def handle_connect():
    """Called when a browser opens the dashboard."""
    print("Browser connected via WebSocket")
    emit("status", {"message": "Connected"})


@socketio.on("request_sync")
def handle_sync():
    """
    Browser clicks "Sync Now" → this runs → pushes result back to browser.

    This is the WebSocket magic: we can notify the browser when the sync
    is done WITHOUT the browser polling or refreshing. The server pushes.
    """
    emit("sync_started", {"message": "Syncing latest data..."})
    try:
        # Import here to avoid circular imports
        sys.path.insert(0, os.path.dirname(__file__))
        from whoop_client import WhoopClient
        from garmin_client import GarminClient
        from pipeline import run_whoop_sync, run_garmin_sync
        from database import Database

        start  = (date.today() - timedelta(days=7)).isoformat()
        db     = Database()
        whoop  = WhoopClient()
        garmin = GarminClient()

        run_whoop_sync(whoop, db, start=start)
        run_garmin_sync(garmin, db, start=start)
        db.close()

        emit("sync_complete", {"success": True,  "message": "Data updated!"})
    except Exception as e:
        emit("sync_complete", {"success": False, "message": str(e)})


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🏃 Health Dashboard starting...")
    print("📊 Open http://localhost:5000 in your browser\n")
    socketio.run(app, debug=True, port=8080, allow_unsafe_werkzeug=True)
