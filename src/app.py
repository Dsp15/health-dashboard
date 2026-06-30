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

from flask import Flask, render_template, jsonify, redirect, url_for, request
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
    """Latest snapshot for stat cards — Whoop primary, Garmin secondary."""
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
    # Garmin secondary data for comparison in stat cards
    garmin = query("""
        SELECT gd.resting_hr           AS garmin_resting_hr,
               gd.training_readiness   AS garmin_training_readiness,
               gs.total_sleep_hours    AS garmin_sleep_hours,
               gs.sleep_score          AS garmin_sleep_score,
               gh.last_night_ms        AS garmin_hrv_last_night
        FROM garmin_daily gd
        LEFT JOIN garmin_sleep gs ON gs.date = gd.date
        LEFT JOIN garmin_hrv   gh ON gh.date = gd.date
        WHERE gd.resting_hr IS NOT NULL
        ORDER BY gd.date DESC
        LIMIT 1
    """)
    return jsonify({
        "recovery": recovery[0] if recovery else {},
        "sleep":    sleep[0]    if sleep    else {},
        "garmin":   garmin[0]   if garmin   else {},
    })


@app.route("/api/recovery")
def api_recovery():
    """Recovery scores, HRV, resting HR. Accepts ?days=30|60|90 (default 90)."""
    days = int(request.args.get("days", 90))
    return jsonify(query("""
        SELECT
            created_at::date        AS date,
            recovery_score,
            hrv_rmssd,
            resting_hr,
            spo2_pct
        FROM whoop_recovery
        WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
        ORDER BY created_at ASC
    """ % days))


@app.route("/api/sleep")
def api_sleep():
    """Sleep data — stages, performance, bedtime. Accepts ?days=30|60|90."""
    days = int(request.args.get("days", 90))
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
        WHERE start_time >= CURRENT_DATE - INTERVAL '%s days'
          AND is_nap = false
        ORDER BY start_time ASC
    """ % days))


@app.route("/api/trends")
def api_trends():
    """
    Compare last 7 days vs previous 7 days for trend arrows on stat cards.
    Returns averages for both windows so the frontend can show ↑ or ↓.
    """
    rows = query("""
        SELECT
            ROUND(AVG(CASE WHEN created_at >= CURRENT_DATE - 7
                           THEN recovery_score END)::numeric, 1)  AS recovery_now,
            ROUND(AVG(CASE WHEN created_at < CURRENT_DATE - 7
                           AND created_at >= CURRENT_DATE - 14
                           THEN recovery_score END)::numeric, 1)  AS recovery_prev,
            ROUND(AVG(CASE WHEN created_at >= CURRENT_DATE - 7
                           THEN hrv_rmssd END)::numeric, 1)       AS hrv_now,
            ROUND(AVG(CASE WHEN created_at < CURRENT_DATE - 7
                           AND created_at >= CURRENT_DATE - 14
                           THEN hrv_rmssd END)::numeric, 1)       AS hrv_prev,
            ROUND(AVG(CASE WHEN created_at >= CURRENT_DATE - 7
                           THEN resting_hr END)::numeric, 1)      AS rhr_now,
            ROUND(AVG(CASE WHEN created_at < CURRENT_DATE - 7
                           AND created_at >= CURRENT_DATE - 14
                           THEN resting_hr END)::numeric, 1)      AS rhr_prev
        FROM whoop_recovery
        WHERE created_at >= CURRENT_DATE - 14
    """)
    return jsonify(rows[0] if rows else {})


@app.route("/api/comparison")
def api_comparison():
    """
    Dual-tracker comparison: Garmin vs Whoop side by side.
    Joins garmin_daily, garmin_sleep, garmin_hrv with whoop data on date.

    This is the interesting one — two devices measuring the same things
    with different algorithms. Useful for validating data quality and
    seeing where the trackers agree or diverge.
    """
    days = int(request.args.get("days", 90))
    return jsonify(query("""
        SELECT
            g.date,
            -- Resting HR from both devices
            g.resting_hr                            AS garmin_resting_hr,
            w.resting_hr                            AS whoop_resting_hr,
            -- Readiness: Body Battery (0-100) vs Whoop Recovery (0-100)
            CAST(g.raw->>'bodyBatteryMostRecentValue' AS FLOAT) AS body_battery,
            w.recovery_score                        AS whoop_recovery,
            -- Stress vs Recovery (should be inversely related)
            g.avg_stress                            AS garmin_stress,
            -- HRV from both
            gh.weekly_avg_ms                        AS garmin_hrv_weekly,
            gh.last_night_ms                        AS garmin_hrv_last_night,
            w.hrv_rmssd                             AS whoop_hrv,
            -- Sleep scores from both
            gs.sleep_score                          AS garmin_sleep_score,
            gs.total_sleep_hours                    AS garmin_sleep_hours,
            ws.sleep_performance_pct                AS whoop_sleep_score,
            ws.total_in_bed_hours                   AS whoop_sleep_hours
        FROM garmin_daily g
        LEFT JOIN whoop_recovery w
            ON w.created_at::date = g.date
        LEFT JOIN garmin_hrv gh
            ON gh.date = g.date
        LEFT JOIN garmin_sleep gs
            ON gs.date = g.date
        LEFT JOIN whoop_sleep ws
            ON ws.start_time::date = g.date - 1
           AND ws.is_nap = false
        WHERE g.date >= CURRENT_DATE - INTERVAL '%s days'
        ORDER BY g.date ASC
    """ % days))


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
