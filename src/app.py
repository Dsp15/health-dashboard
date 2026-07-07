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

import atexit
import json
import os
import secrets
import sys
import threading
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
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


# ── Auto Sync ─────────────────────────────────────────────────────────────────

def run_background_sync(reason="scheduled"):
    """
    Pull the last 7 days of data from Whoop and Garmin in a background thread.

    This is the same logic as the WebSocket "Sync Now" button, but it runs
    automatically — either on a schedule (6am daily) or when the server
    starts and detects stale data.

    Why a background thread?
      Flask handles one request at a time per thread. If we ran the sync
      inside a request, the browser would hang waiting for it. Running it
      in a separate thread lets Flask keep serving pages while syncing.
    """
    print(f"\n📡 Auto-sync triggered ({reason})...")
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from whoop_client import WhoopClient
        from garmin_client import GarminClient
        from pipeline import run_whoop_sync, run_garmin_sync, run_weather_sync
        from database import Database

        start  = (date.today() - timedelta(days=7)).isoformat()
        db     = Database()
        whoop  = WhoopClient()
        garmin = GarminClient()

        run_whoop_sync(whoop, db, start=start)
        run_garmin_sync(garmin, db, start=start)
        run_weather_sync(db, start=start)
        db.close()

        print("✅ Auto-sync complete")
        # Push a notification to any open browser tabs
        socketio.emit("sync_complete", {
            "success": True,
            "message": f"Auto-sync complete ({reason})"
        })
    except Exception as e:
        print(f"⚠️  Auto-sync failed: {e}")


def hours_since_last_sync():
    """
    Check the database to see how old the most recent Whoop record is.
    Returns hours as a float. Returns 999 if we can't tell (treat as stale).
    """
    try:
        rows = query("SELECT MAX(created_at) AS last FROM whoop_recovery")
        if rows and rows[0].get("last"):
            last = datetime.fromisoformat(str(rows[0]["last"]))
            # Make both timezone-aware or both naive for comparison
            now = datetime.now(last.tzinfo) if last.tzinfo else datetime.now()
            return (now - last).total_seconds() / 3600
    except Exception:
        pass
    return 999


def start_scheduler():
    """
    Set up APScheduler with two jobs:
      1. Daily 6am sync — runs every morning automatically
      2. Startup sync   — fires once immediately if data is > 4 hours old

    We only start the scheduler in the actual Flask process, not in the
    Werkzeug reloader's watcher process (which also imports this file).
    """
    scheduler = BackgroundScheduler(daemon=True)

    # Job 1: every day at 6:00am
    scheduler.add_job(
        func=lambda: run_background_sync("6am daily"),
        trigger=CronTrigger(hour=6, minute=0),
        id="daily_6am_sync",
        replace_existing=True,
    )

    scheduler.start()
    # Shut down cleanly when Flask exits
    atexit.register(scheduler.shutdown)

    # Job 2: startup sync if data is stale
    stale = hours_since_last_sync()
    if stale > 4:
        print(f"⏰ Data is {stale:.0f}h old — running startup sync in background...")
        threading.Thread(target=lambda: run_background_sync("startup"), daemon=True).start()
    else:
        print(f"✅ Data is fresh ({stale:.1f}h old) — skipping startup sync")


# Only start the scheduler in the real server process, not the reloader watcher.
# WERKZEUG_RUN_MAIN is set to 'true' in the child (real) process.
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    start_scheduler()


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


# ── Whoop OAuth ────────────────────────────────────────────────────────────────
# These routes handle Whoop re-authentication when Flask is already running.
# Without this, the Whoop callback would hit Flask on port 8080 and get a 404.

_whoop_oauth_state = None   # One-time random string to prevent CSRF

@app.route("/whoop/reauth")
def whoop_reauth():
    """
    Redirect the browser to Whoop's login page.
    Visit http://localhost:8080/whoop/reauth any time your Whoop token expires.
    """
    global _whoop_oauth_state
    _whoop_oauth_state = secrets.token_urlsafe(16)

    params = {
        "client_id":     os.getenv("WHOOP_CLIENT_ID"),
        "redirect_uri":  os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8080/callback"),
        "response_type": "code",
        "scope":         "read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement offline",
        "state":         _whoop_oauth_state,
    }
    return redirect(f"https://api.prod.whoop.com/oauth/oauth2/auth?{urlencode(params)}")


@app.route("/callback")
def whoop_callback():
    """
    Whoop redirects here after the user logs in.
    We exchange the code for a token and save it — same file whoop_client.py reads.
    """
    global _whoop_oauth_state
    import requests as req

    code  = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return f"<h2>Whoop auth error: {error}</h2>", 400
    if not code:
        return "<h2>No authorization code received from Whoop.</h2>", 400

    # Exchange the code for a token
    try:
        resp = req.post("https://api.prod.whoop.com/oauth/oauth2/token", data={
            "client_id":     os.getenv("WHOOP_CLIENT_ID"),
            "client_secret": os.getenv("WHOOP_CLIENT_SECRET"),
            "code":          code,
            "redirect_uri":  os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8080/callback"),
            "grant_type":    "authorization_code",
        })
        resp.raise_for_status()
        token = resp.json()

        # Save to the same file that whoop_client.py reads
        token_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".whoop_token.json")
        with open(token_path, "w") as f:
            json.dump(token, f, indent=2)

        _whoop_oauth_state = None  # Clear state after successful use
        return """
        <html><body style="font-family:sans-serif;max-width:500px;margin:80px auto;text-align:center">
            <h2>✅ Whoop connected!</h2>
            <p>Token saved. You can close this tab.</p>
            <a href="/daily" style="color:#58a6ff">← Back to dashboard</a>
        </body></html>
        """
    except Exception as e:
        return f"<h2>Token exchange failed: {e}</h2>", 500


# ── API: Daily Health ──────────────────────────────────────────────────────────

@app.route("/api/sync_status")
def api_sync_status():
    """Returns how long ago the last sync was — shown in the navbar."""
    hours = hours_since_last_sync()
    if hours < 1:
        label = f"{int(hours * 60)}m ago"
    elif hours < 24:
        label = f"{hours:.0f}h ago"
    else:
        label = f"{hours / 24:.0f}d ago"
    return jsonify({"hours": round(hours, 1), "label": label})


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
    # Garmin secondary data — each metric uses its own latest value independently.
    # This avoids date-alignment gaps where garmin_daily, garmin_sleep, and garmin_hrv
    # don't all have entries for the same exact date (e.g. sleep is often one day off).
    garmin = query("""
        SELECT
            (SELECT resting_hr        FROM garmin_daily WHERE resting_hr        IS NOT NULL ORDER BY date DESC LIMIT 1) AS garmin_resting_hr,
            (SELECT training_readiness FROM garmin_daily WHERE training_readiness IS NOT NULL ORDER BY date DESC LIMIT 1) AS garmin_training_readiness,
            (SELECT total_sleep_hours  FROM garmin_sleep  WHERE total_sleep_hours  IS NOT NULL ORDER BY date DESC LIMIT 1) AS garmin_sleep_hours,
            (SELECT sleep_score        FROM garmin_sleep  WHERE sleep_score        IS NOT NULL ORDER BY date DESC LIMIT 1) AS garmin_sleep_score,
            (SELECT weekly_avg_ms      FROM garmin_hrv    WHERE weekly_avg_ms      IS NOT NULL ORDER BY date DESC LIMIT 1) AS garmin_hrv_last_night
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


@app.route("/api/day")
def api_day():
    """
    Stats for a specific date — used when user clicks a chart point.
    Defaults to today if no date provided.
    """
    day = request.args.get("date", date.today().isoformat())

    recovery = query("""
        SELECT recovery_score, hrv_rmssd, resting_hr, spo2_pct,
               created_at::date AS date
        FROM whoop_recovery
        WHERE created_at::date = %s
        LIMIT 1
    """, [day])

    sleep = query("""
        SELECT total_in_bed_hours, deep_sleep_hours, rem_sleep_hours,
               light_sleep_hours, sleep_performance_pct, start_time
        FROM whoop_sleep
        WHERE start_time::date = %s AND is_nap = false
        LIMIT 1
    """, [day])

    # For a specific day, get each Garmin metric independently within ±1 day
    # to handle date-offset differences between garmin_daily, garmin_sleep, and garmin_hrv.
    garmin = query("""
        SELECT
            (SELECT resting_hr         FROM garmin_daily WHERE date = %s AND resting_hr         IS NOT NULL LIMIT 1) AS garmin_resting_hr,
            (SELECT training_readiness  FROM garmin_daily WHERE date = %s AND training_readiness  IS NOT NULL LIMIT 1) AS garmin_training_readiness,
            (SELECT total_sleep_hours   FROM garmin_sleep  WHERE date IN (%s::date, %s::date - 1) AND total_sleep_hours IS NOT NULL ORDER BY date DESC LIMIT 1) AS garmin_sleep_hours,
            (SELECT sleep_score         FROM garmin_sleep  WHERE date IN (%s::date, %s::date - 1) AND sleep_score        IS NOT NULL ORDER BY date DESC LIMIT 1) AS garmin_sleep_score,
            (SELECT weekly_avg_ms       FROM garmin_hrv    WHERE date IN (%s::date, %s::date - 1) AND weekly_avg_ms      IS NOT NULL ORDER BY date DESC LIMIT 1) AS garmin_hrv_last_night
    """, [day, day, day, day, day, day, day, day])

    return jsonify({
        "date":     day,
        "recovery": recovery[0] if recovery else {},
        "sleep":    sleep[0]    if sleep    else {},
        "garmin":   garmin[0]   if garmin   else {},
    })


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


# ── API: Weather & Environment ────────────────────────────────────────────────

@app.route("/api/weather")
def api_weather():
    """
    Environmental data joined with health metrics for correlation analysis.

    Returns daily weather (temp, humidity, UV, precipitation) and air quality
    (PM2.5) alongside Whoop recovery score, HRV, and sleep — so the frontend
    can chart how environmental conditions relate to how Dan feels.

    This tests the hypothesis: do high-allergy / high-pollution days
    predict lower recovery scores?
    """
    days = int(request.args.get("days", 90))
    return jsonify(query("""
        SELECT
            w.date,
            -- Weather
            ROUND(w.temp_max::numeric, 1)     AS temp_max,
            ROUND(w.temp_min::numeric, 1)     AS temp_min,
            ROUND(w.temp_mean::numeric, 1)    AS temp_mean,
            ROUND(w.humidity::numeric, 1)     AS humidity,
            ROUND(w.precipitation::numeric, 2) AS precipitation,
            ROUND(w.uv_index::numeric, 1)     AS uv_index,
            w.weather_code,
            -- Air quality
            ROUND(w.pm25::numeric, 1)         AS pm25,
            ROUND(w.pm10::numeric, 1)         AS pm10,
            w.aqi_category,
            -- Pollen (Tomorrow.io)
            w.grass_pollen,
            w.tree_pollen,
            w.weed_pollen,
            w.ragweed_pollen,
            -- Health (Whoop)
            r.recovery_score,
            r.hrv_rmssd,
            r.resting_hr,
            s.sleep_performance_pct,
            s.total_in_bed_hours
        FROM weather_daily w
        LEFT JOIN whoop_recovery r
            ON r.created_at::date = w.date
        LEFT JOIN whoop_sleep s
            ON s.start_time::date = w.date
            AND s.is_nap = false
        WHERE w.date >= CURRENT_DATE - INTERVAL '%s days'
          AND w.temp_mean IS NOT NULL
        ORDER BY w.date ASC
    """ % days))


@app.route("/api/weather/today")
def api_weather_today():
    """Today's weather conditions for the stat cards."""
    rows = query("""
        SELECT temp_max, temp_min, temp_mean, humidity,
               precipitation, uv_index, weather_code, pm25, aqi_category,
               grass_pollen, tree_pollen, weed_pollen, ragweed_pollen
        FROM weather_daily
        WHERE date = (
            SELECT date FROM weather_daily
            WHERE temp_mean IS NOT NULL
            ORDER BY date DESC LIMIT 1
        )
    """)
    return jsonify(rows[0] if rows else {})


# ── API: Training ──────────────────────────────────────────────────────────────

@app.route("/api/activities")
def api_activities():
    """All Garmin activities joined with next-day Whoop recovery."""
    return jsonify(query("""
        SELECT
            a.start_time::date                          AS date,
            a.sport_type,
            a.name,
            ROUND(a.duration_secs / 60)                 AS duration_mins,
            a.avg_hr,
            ROUND((a.distance_m / 1000.0)::numeric, 1)  AS distance_km,
            a.calories,
            r.recovery_score                            AS next_day_recovery,
            r.hrv_rmssd                                 AS next_day_hrv
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
            COUNT(*)                                            AS sessions,
            ROUND((SUM(duration_secs) / 3600.0)::numeric, 1)   AS total_hours,
            STRING_AGG(DISTINCT sport_type, ', ')               AS sports
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
            COUNT(*)                                            AS sessions,
            ROUND((SUM(duration_secs) / 3600.0)::numeric, 1)   AS total_hours
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


# ── API: AI Summary ───────────────────────────────────────────────────────────

@app.route("/api/ai_summary")
def api_ai_summary():
    """
    Weekly health summary — two modes:

    MODE 1 (default): Rule-based engine
      Reads your actual numbers and generates specific sentences based on
      what the data means. No API key, no cost, works immediately.

    MODE 2 (optional): Claude API
      If ANTHROPIC_API_KEY is set in .env, uses the Claude Haiku model for
      a richer natural-language summary. Upgrade path for later.

    The rule-based engine is genuinely useful — it checks specific thresholds
    and generates different text depending on your exact data, so it reads
    like real coaching feedback, not a template.
    """

    # ── Pull last 7 days of data ────────────────────────────────
    recovery_rows = query("""
        SELECT created_at::date AS date, recovery_score, hrv_rmssd, resting_hr
        FROM whoop_recovery
        WHERE created_at >= CURRENT_DATE - 7
        ORDER BY created_at DESC
    """)

    sleep_rows = query("""
        SELECT start_time::date AS date,
               ROUND(total_in_bed_hours::numeric, 1) AS hours_in_bed,
               sleep_performance_pct AS sleep_score
        FROM whoop_sleep
        WHERE start_time >= CURRENT_DATE - 7
          AND is_nap = false
        ORDER BY start_time DESC
    """)

    activity_rows = query("""
        SELECT start_time::date AS date, sport_type,
               ROUND(duration_secs / 60)                    AS duration_mins,
               ROUND((distance_m / 1000.0)::numeric, 1)     AS distance_km,
               avg_hr
        FROM garmin_activities
        WHERE start_time >= CURRENT_DATE - 7
        ORDER BY start_time DESC
    """)

    trend_rows = query("""
        SELECT
            ROUND(AVG(CASE WHEN created_at >= CURRENT_DATE - 7
                           THEN recovery_score END)::numeric, 1)  AS recovery_this_week,
            ROUND(AVG(CASE WHEN created_at <  CURRENT_DATE - 7
                           AND  created_at >= CURRENT_DATE - 14
                           THEN recovery_score END)::numeric, 1)  AS recovery_last_week,
            ROUND(AVG(CASE WHEN created_at >= CURRENT_DATE - 7
                           THEN hrv_rmssd END)::numeric, 1)       AS hrv_this_week,
            ROUND(AVG(CASE WHEN created_at <  CURRENT_DATE - 7
                           AND  created_at >= CURRENT_DATE - 14
                           THEN hrv_rmssd END)::numeric, 1)       AS hrv_last_week
        FROM whoop_recovery
        WHERE created_at >= CURRENT_DATE - 14
    """)
    trends = trend_rows[0] if trend_rows else {}

    # ── MODE 2: Claude API (if key is configured) ───────────────
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic
            data_block = (
                f"Recovery rows: {json.dumps(recovery_rows, default=str)}\n"
                f"Sleep rows: {json.dumps(sleep_rows, default=str)}\n"
                f"Activities: {json.dumps(activity_rows, default=str)}\n"
                f"Trends: recovery {trends.get('recovery_this_week')} vs "
                f"{trends.get('recovery_last_week')} last week, "
                f"HRV {trends.get('hrv_this_week')} ms vs "
                f"{trends.get('hrv_last_week')} ms last week"
            )
            prompt = (
                "You are a sports performance coach reviewing a triathlete's weekly health data.\n"
                "Write exactly 3 short sentences (plain text, no bullet points, no markdown):\n"
                "1. Recovery and HRV trend this week vs last week\n"
                "2. How training load looks relative to body readiness\n"
                "3. One specific, actionable recommendation\n"
                "Reference the actual numbers. No filler like 'Great job!' or 'It looks like...'\n\n"
                f"Data:\n{data_block}"
            )
            client  = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            return jsonify({"summary": message.content[0].text.strip()})
        except Exception as e:
            pass  # Fall through to rule-based on any error

    # ── MODE 1: Rule-based summary (default) ────────────────────
    summary = _rule_based_summary(recovery_rows, sleep_rows, activity_rows, trends)
    return jsonify({"summary": summary})


def _rule_based_summary(recovery_rows, sleep_rows, activity_rows, trends):
    """
    Generate a plain-English weekly summary from the data.

    This is real business logic — not a static template. The output changes
    based on your actual numbers, trends, and training load.
    """
    sentences = []

    rec_now  = float(trends["recovery_this_week"])  if trends.get("recovery_this_week")  else None
    rec_prev = float(trends["recovery_last_week"])  if trends.get("recovery_last_week")  else None
    hrv_now  = float(trends["hrv_this_week"])       if trends.get("hrv_this_week")       else None
    hrv_prev = float(trends["hrv_last_week"])       if trends.get("hrv_last_week")       else None

    # ── Sentence 1: Recovery + HRV trend ─────────────────────
    if rec_now is not None:
        zone = "green zone" if rec_now >= 67 else ("yellow zone" if rec_now >= 34 else "red zone")
        if rec_prev is not None:
            diff = rec_now - rec_prev
            direction = f"up {abs(diff):.0f} points from last week" if diff > 2 \
                   else f"down {abs(diff):.0f} points from last week" if diff < -2 \
                   else "consistent with last week"
        else:
            direction = "this week"

        hrv_note = ""
        if hrv_now is not None and hrv_prev is not None:
            hdiff = hrv_now - hrv_prev
            if hdiff > 2:
                hrv_note = f"; HRV is tracking {abs(hdiff):.0f} ms higher"
            elif hdiff < -2:
                hrv_note = f"; HRV is down {abs(hdiff):.0f} ms — worth watching"

        sentences.append(
            f"Recovery is averaging {rec_now:.0f}% ({zone}), {direction}{hrv_note}."
        )
    else:
        sentences.append("Not enough recovery data yet this week.")

    # ── Sentence 2: Training load ─────────────────────────────
    n_sessions  = len(activity_rows)
    total_hours = sum((a.get("duration_mins") or 0) for a in activity_rows) / 60

    sport_names = [a.get("sport_type", "") for a in activity_rows]
    sports_done = {
        "run":    any("run" in s for s in sport_names),
        "bike":   any(x in s for s in sport_names for x in ("bik", "cycl", "road")),
        "swim":   any("swim" in s for s in sport_names),
        "multi":  any("multi" in s for s in sport_names),
        "weight": any("strength" in s or "weight" in s for s in sport_names),
    }
    sport_list = [k for k, v in sports_done.items() if v]
    sport_str  = " + ".join(sport_list) if sport_list else "mixed"

    if n_sessions == 0:
        sentences.append("No training sessions recorded this week — full rest.")
    elif total_hours >= 10:
        sentences.append(
            f"Heavy week: {n_sessions} sessions and {total_hours:.1f} hours ({sport_str}) — "
            f"{'body is handling it well' if rec_now and rec_now >= 60 else 'recovery is feeling the load'}."
        )
    elif total_hours >= 5:
        sentences.append(
            f"Solid training week: {n_sessions} sessions, {total_hours:.1f} hours of {sport_str}."
        )
    else:
        sessions_word = "session" if n_sessions == 1 else "sessions"
        sentences.append(
            f"Light week with {n_sessions} {sessions_word} and {total_hours:.1f} hours — "
            f"{'intentional recovery block' if rec_now and rec_now < 60 else 'room to add volume if feeling good'}."
        )

    # ── Sentence 3: Actionable recommendation ─────────────────
    if rec_now is None:
        sentences.append("Sync data and check back for a recommendation.")
    elif rec_now >= 67 and total_hours < 6:
        sentences.append(
            "Body signals are strong and training load is low — good week to push a quality session or extend a long run."
        )
    elif rec_now >= 67 and total_hours >= 6:
        sentences.append(
            "Recovery is holding up well despite solid training load — keep the pattern and listen for any early fatigue signs."
        )
    elif rec_now >= 50 and total_hours >= 8:
        sentences.append(
            f"Recovery is in the yellow under a {total_hours:.0f}-hour week — cut intensity before volume this week."
        )
    elif rec_now < 50 and n_sessions >= 3:
        sentences.append(
            "Recovery is lagging behind training load — prioritize sleep, take an easy day before the next hard effort."
        )
    else:
        sentences.append(
            "Focus on consistent sleep timing this week; bedtime consistency is often the fastest way to lift HRV."
        )

    return " ".join(sentences)


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
        from pipeline import run_whoop_sync, run_garmin_sync, run_weather_sync
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
