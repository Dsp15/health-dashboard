/**
 * daily.js
 *
 * Daily Health page — loads and renders all charts.
 *
 * Features:
 *   - Date range toggle (30 / 60 / 90 days) — all charts update together
 *   - Trend arrows on stat cards (this week vs last week)
 *   - HRV vs Recovery scatter plot (shows the correlation)
 *   - Dual-tracker comparison section (Garmin vs Whoop)
 *
 * Data flow:
 *   Browser → fetch(/api/...) → Flask → PostgreSQL → JSON → Chart.js
 */

// ── Global State ─────────────────────────────────────────────────────────────

let currentDays = 30;   // Default to 30 days for a cleaner initial view
const charts = {};      // Stores Chart.js instances so we can destroy/recreate

// ── Date Range Toggle ────────────────────────────────────────────────────────

function setDays(days) {
    currentDays = days;

    // Update button styles
    const label = days === 9999 ? "All Time" : `${days} Days`;
    document.querySelectorAll(".range-btn").forEach(btn => {
        btn.classList.toggle("active", btn.textContent === label);
    });

    // Reload all charts with new range
    loadCharts();
}

// ── Entry Point ──────────────────────────────────────────────────────────────

async function loadCharts() {
    try {
        // Fetch all data sources in parallel
        const [todayData, recoveryData, sleepData, trendsData, compData] = await Promise.all([
            fetch("/api/today").then(r => r.json()),
            fetch(`/api/recovery?days=${currentDays}`).then(r => r.json()),
            fetch(`/api/sleep?days=${currentDays}`).then(r => r.json()),
            fetch("/api/trends").then(r => r.json()),
            fetch(`/api/comparison?days=${currentDays}`).then(r => r.json()),
        ]);

        // ── Whoop charts ──────────────────────────────────────────
        renderStatCards(todayData, trendsData);
        renderRecoveryChart(recoveryData);
        renderHRVChart(recoveryData);
        renderRestingHRChart(recoveryData);
        renderSleepChart(sleepData);
        renderSleepPerfChart(sleepData);
        renderBedtimeChart(sleepData);
        renderScatterChart(recoveryData);

        // ── Dual tracker comparison ───────────────────────────────
        renderRHRCompareChart(compData);
        renderReadinessChart(compData);
        renderHRVCompareChart(compData);
        renderSleepCompareChart(compData);

    } catch (err) {
        console.error("Failed to load charts:", err);
    }
}

// ── Stat Cards ────────────────────────────────────────────────────────────────

function renderStatCards(data, trends) {
    const rec   = data.recovery || {};
    const sleep = data.sleep    || {};

    // Recovery score
    const score = rec.recovery_score;
    if (score != null) {
        const el = document.getElementById("stat-recovery");
        el.textContent = Math.round(score) + "%";
        el.className   = "stat-value " + recoveryClass(score);
        const bar = document.getElementById("bar-recovery");
        bar.style.width      = score + "%";
        bar.style.background = recoveryColor(score);
    }

    setCard("stat-hrv",        rec.hrv_rmssd,             v => Math.round(v) + " ms");
    setCard("stat-hr",         rec.resting_hr,            v => Math.round(v));
    setCard("stat-sleep",      sleep.total_in_bed_hours,  v => v.toFixed(1) + "h");
    setCard("stat-sleep-perf", sleep.sleep_performance_pct, v => Math.round(v) + "%");

    if (sleep.start_time) {
        const d = new Date(sleep.start_time);
        document.getElementById("stat-bedtime").textContent = fmtTime(d);
    }

    // Today's date label
    const dateEl = document.getElementById("today-date");
    if (dateEl) {
        const today = new Date();
        dateEl.textContent = today.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
    }

    // Garmin secondary lines on stat cards
    const g = data.garmin || {};
    if (g.garmin_resting_hr)
        document.getElementById("stat-hr-garmin").textContent =
            `Garmin ${Math.round(g.garmin_resting_hr)} bpm`;
    if (g.garmin_sleep_hours)
        document.getElementById("stat-sleep-garmin").textContent =
            `Garmin ${g.garmin_sleep_hours.toFixed(1)}h`;
    if (g.garmin_sleep_score)
        document.getElementById("stat-sleep-score-garmin").textContent =
            `Garmin score ${Math.round(g.garmin_sleep_score)}`;
    if (g.garmin_training_readiness != null)
        document.getElementById("stat-training-readiness").textContent =
            `Training Readiness ${Math.round(g.garmin_training_readiness)}`;
    if (g.garmin_hrv_last_night != null)
        document.getElementById("stat-hrv-garmin").textContent =
            `Garmin ${Math.round(g.garmin_hrv_last_night)} ms last night`;

    // Trend arrows — compare last 7 days to previous 7 days
    if (trends) {
        setTrend("trend-recovery", trends.recovery_now, trends.recovery_prev, true);
        setTrend("trend-hrv",      trends.hrv_now,      trends.hrv_prev,      true);
        // For resting HR, lower is better so flip the arrow direction
        setTrend("trend-hr",       trends.rhr_now,      trends.rhr_prev,      false);
    }
}

function setCard(id, value, fmt) {
    if (value != null) document.getElementById(id).textContent = fmt(value);
}

/**
 * Render a trend arrow on a stat card.
 * @param {string} id      - Element ID
 * @param {number} now     - Current 7-day average
 * @param {number} prev    - Previous 7-day average
 * @param {boolean} upGood - True if higher value = better (recovery, HRV)
 *                           False if lower value = better (resting HR)
 */
function setTrend(id, now, prev, upGood) {
    const el = document.getElementById(id);
    if (!el || now == null || prev == null) return;
    const diff = now - prev;
    const pct  = Math.abs(Math.round((diff / prev) * 100));
    if (Math.abs(diff) < 0.5) {
        el.textContent  = "→ Stable";
        el.className    = "stat-trend flat";
        return;
    }
    const improving = upGood ? diff > 0 : diff < 0;
    el.textContent = improving
        ? `↑ +${pct}% vs last week`
        : `↓ -${pct}% vs last week`;
    el.className = "stat-trend " + (improving ? "up" : "down");
}

// ── Recovery Chart ────────────────────────────────────────────────────────────

function renderRecoveryChart(data) {
    renderChart("chartRecovery", {
        type: "bar",
        data: {
            labels: data.map(d => fmtDate(d.date)),
            datasets: [{
                label: "Recovery %",
                data: data.map(d => d.recovery_score),
                backgroundColor: data.map(d => recoveryColor(d.recovery_score)),
                borderRadius: 3,
                borderSkipped: false,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 12 } },
                y: { ...yAxis(), min: 0, max: 100, ticks: { callback: v => v + "%" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `Recovery: ${Math.round(ctx.raw)}%`
            }}}
        }
    });
}

// ── HRV Chart ─────────────────────────────────────────────────────────────────

function renderHRVChart(data) {
    renderChart("chartHRV", {
        type: "line",
        data: {
            labels: data.map(d => fmtDate(d.date)),
            datasets: [{
                label: "HRV",
                data: data.map(d => d.hrv_rmssd),
                borderColor: "#7c6af7",
                backgroundColor: "rgba(124,106,247,0.1)",
                borderWidth: 2, pointRadius: 0, fill: true, tension: 0.4,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 8 } },
                y: { ...yAxis(), ticks: { callback: v => v + " ms" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `HRV: ${Math.round(ctx.raw)} ms`
            }}}
        }
    });
}

// ── Resting HR Chart ──────────────────────────────────────────────────────────

function renderRestingHRChart(data) {
    renderChart("chartRestingHR", {
        type: "line",
        data: {
            labels: data.map(d => fmtDate(d.date)),
            datasets: [{
                label: "Resting HR",
                data: data.map(d => d.resting_hr),
                borderColor: "#f85149",
                backgroundColor: "rgba(248,81,73,0.08)",
                borderWidth: 2, pointRadius: 0, fill: true, tension: 0.4,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 8 } },
                y: { ...yAxis(), ticks: { callback: v => v + " bpm" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `Resting HR: ${Math.round(ctx.raw)} bpm`
            }}}
        }
    });
}

// ── Sleep Stacked Bar ─────────────────────────────────────────────────────────

function renderSleepChart(data) {
    renderChart("chartSleep", {
        type: "bar",
        data: {
            labels: data.map(d => fmtDate(d.date)),
            datasets: [
                { label: "Deep",  data: data.map(d => d.deep_sleep_hours),  backgroundColor: "#3fb950", stack: "s", borderRadius: 2 },
                { label: "REM",   data: data.map(d => d.rem_sleep_hours),   backgroundColor: "#7c6af7", stack: "s" },
                { label: "Light", data: data.map(d => d.light_sleep_hours), backgroundColor: "#58a6ff", stack: "s" },
                { label: "Awake", data: data.map(d => d.awake_hours),       backgroundColor: "#484f58", stack: "s" },
            ]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), stacked: true, ticks: { maxTicksLimit: 12 } },
                y: { ...yAxis(), stacked: true, ticks: { callback: v => v + "h" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `${ctx.dataset.label}: ${ctx.raw?.toFixed(1)}h`
            }}}
        }
    });
}

// ── Sleep Performance ─────────────────────────────────────────────────────────

function renderSleepPerfChart(data) {
    renderChart("chartSleepPerf", {
        type: "line",
        data: {
            labels: data.map(d => fmtDate(d.date)),
            datasets: [{
                label: "Sleep Performance",
                data: data.map(d => d.sleep_performance_pct),
                borderColor: "#58a6ff",
                backgroundColor: "rgba(88,166,255,0.1)",
                borderWidth: 2, pointRadius: 0, fill: true, tension: 0.4,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 8 } },
                y: { ...yAxis(), min: 0, max: 100, ticks: { callback: v => v + "%" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `Sleep score: ${Math.round(ctx.raw)}%`
            }}}
        }
    });
}

// ── Bedtime Chart ─────────────────────────────────────────────────────────────

function renderBedtimeChart(data) {
    const values = data.map(d => {
        if (!d.start_time) return null;
        const t = new Date(d.start_time);
        let h = t.getHours() + t.getMinutes() / 60;
        if (h < 6) h += 24;
        return Math.round(h * 10) / 10;
    });

    renderChart("chartBedtime", {
        type: "line",
        data: {
            labels: data.map(d => fmtDate(d.date)),
            datasets: [{
                label: "Bedtime",
                data: values,
                borderColor: "#d29922",
                backgroundColor: "rgba(210,153,34,0.08)",
                borderWidth: 2, pointRadius: 0, fill: true, tension: 0.3,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 8 } },
                y: {
                    ...yAxis(), min: 20, max: 28,
                    ticks: { callback: v => {
                        const h = v % 24;
                        return `${h % 12 || 12}${h >= 12 ? "pm" : "am"}`;
                    }}
                }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => {
                    const h = ctx.raw % 24;
                    const m = Math.round((h % 1) * 60).toString().padStart(2, "0");
                    return `Bedtime: ${Math.floor(h) % 12 || 12}:${m}${h >= 12 ? "pm" : "am"}`;
                }
            }}}
        }
    });
}

// ── HRV vs Recovery Scatter ───────────────────────────────────────────────────

function renderScatterChart(data) {
    const points = data
        .filter(d => d.hrv_rmssd != null && d.recovery_score != null)
        .map(d => ({
            x: d.hrv_rmssd,
            y: d.recovery_score,
            date: d.date,
        }));

    renderChart("chartScatter", {
        type: "scatter",
        data: {
            datasets: [{
                label: "HRV vs Recovery",
                data: points,
                backgroundColor: points.map(p => recoveryColor(p.y) + "cc"),
                pointRadius: 5,
                pointHoverRadius: 7,
            }]
        },
        options: {
            ...baseOptions(),
            interaction: { mode: "nearest", intersect: true },
            scales: {
                x: { ...xAxis(), title: { display: true, text: "HRV (rMSSD ms)", color: "#8b949e" } },
                y: {
                    ...yAxis(), min: 0, max: 100,
                    title: { display: true, text: "Recovery %", color: "#8b949e" },
                    ticks: { callback: v => v + "%" }
                }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => [
                    `Date: ${fmtDate(ctx.raw.date)}`,
                    `HRV: ${Math.round(ctx.raw.x)} ms`,
                    `Recovery: ${Math.round(ctx.raw.y)}%`,
                ]
            }}}
        }
    });
}

// ── Dual Tracker: Resting HR ──────────────────────────────────────────────────

function renderRHRCompareChart(data) {
    const withBoth = data.filter(d => d.garmin_resting_hr || d.whoop_resting_hr);

    renderChart("chartRHRCompare", {
        type: "line",
        data: {
            labels: withBoth.map(d => fmtDate(d.date)),
            datasets: [
                {
                    label: "Garmin",
                    data: withBoth.map(d => d.garmin_resting_hr),
                    borderColor: "#58a6ff",
                    backgroundColor: "rgba(88,166,255,0.08)",
                    borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
                },
                {
                    label: "Whoop",
                    data: withBoth.map(d => d.whoop_resting_hr),
                    borderColor: "#3fb950",
                    backgroundColor: "rgba(63,185,80,0.08)",
                    borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
                },
            ]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 10 } },
                y: { ...yAxis(), ticks: { callback: v => v + " bpm" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `${ctx.dataset.label}: ${Math.round(ctx.raw)} bpm`
            }}}
        }
    });
}

// ── Dual Tracker: Body Battery vs Whoop Recovery ──────────────────────────────

function renderReadinessChart(data) {
    const withBoth = data.filter(d => d.body_battery != null || d.whoop_recovery != null);

    renderChart("chartReadiness", {
        type: "line",
        data: {
            labels: withBoth.map(d => fmtDate(d.date)),
            datasets: [
                {
                    label: "Garmin Body Battery",
                    data: withBoth.map(d => d.body_battery),
                    borderColor: "#58a6ff",
                    backgroundColor: "rgba(88,166,255,0.08)",
                    borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
                    yAxisID: "y",
                },
                {
                    label: "Whoop Recovery",
                    data: withBoth.map(d => d.whoop_recovery),
                    borderColor: "#3fb950",
                    backgroundColor: "rgba(63,185,80,0.08)",
                    borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
                    yAxisID: "y",
                },
            ]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 10 } },
                y: { ...yAxis(), min: 0, max: 100, ticks: { callback: v => v + "%" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `${ctx.dataset.label}: ${Math.round(ctx.raw)}`
            }}}
        }
    });
}

// ── Dual Tracker: HRV Comparison ──────────────────────────────────────────────

function renderHRVCompareChart(data) {
    const withData = data.filter(d =>
        d.garmin_hrv_weekly || d.garmin_hrv_last_night || d.whoop_hrv
    );
    if (withData.length === 0) {
        // Garmin HRV data not loaded yet — show placeholder message
        const canvas = document.getElementById("chartHRVCompare");
        if (canvas) {
            const ctx2d = canvas.getContext("2d");
            ctx2d.fillStyle = "#8b949e";
            ctx2d.font = "14px sans-serif";
            ctx2d.textAlign = "center";
            ctx2d.fillText(
                "Run pipeline --full to load Garmin HRV data",
                canvas.width / 2, canvas.height / 2
            );
        }
        return;
    }

    renderChart("chartHRVCompare", {
        type: "line",
        data: {
            labels: withData.map(d => fmtDate(d.date)),
            datasets: [
                {
                    label: "Garmin weekly avg",
                    data: withData.map(d => d.garmin_hrv_weekly),
                    borderColor: "#58a6ff",
                    borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
                },
                {
                    label: "Garmin last night",
                    data: withData.map(d => d.garmin_hrv_last_night),
                    borderColor: "#58a6ff",
                    borderWidth: 1.5, borderDash: [4, 3],
                    pointRadius: 0, fill: false, tension: 0.3,
                },
                {
                    label: "Whoop rMSSD",
                    data: withData.map(d => d.whoop_hrv),
                    borderColor: "#7c6af7",
                    borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
                },
            ]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 10 } },
                y: { ...yAxis(), ticks: { callback: v => v + " ms" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `${ctx.dataset.label}: ${Math.round(ctx.raw)} ms`
            }}}
        }
    });
}

// ── Dual Tracker: Sleep Hours ─────────────────────────────────────────────────

function renderSleepCompareChart(data) {
    const withData = data.filter(d => d.garmin_sleep_hours || d.whoop_sleep_hours);
    if (withData.length === 0) return;

    renderChart("chartSleepCompare", {
        type: "line",
        data: {
            labels: withData.map(d => fmtDate(d.date)),
            datasets: [
                {
                    label: "Garmin",
                    data: withData.map(d => d.garmin_sleep_hours),
                    borderColor: "#58a6ff",
                    borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
                },
                {
                    label: "Whoop",
                    data: withData.map(d => d.whoop_sleep_hours),
                    borderColor: "#3fb950",
                    borderWidth: 2, pointRadius: 0, fill: false, tension: 0.3,
                },
            ]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 10 } },
                y: { ...yAxis(), ticks: { callback: v => v + "h" } }
            },
            plugins: { ...basePlugins(), tooltip: { callbacks: {
                label: ctx => `${ctx.dataset.label}: ${ctx.raw?.toFixed(1)}h`
            }}}
        }
    });
}

// ── Shared Utilities ──────────────────────────────────────────────────────────

function renderChart(id, config) {
    if (charts[id]) charts[id].destroy();
    const ctx = document.getElementById(id);
    if (!ctx) return;
    charts[id] = new Chart(ctx, config);
}

function recoveryClass(score) {
    if (score >= 67) return "green";
    if (score >= 34) return "yellow";
    return "red";
}

function fmtTime(date) {
    let h = date.getHours(), m = date.getMinutes();
    return `${h % 12 || 12}:${m.toString().padStart(2,"0")} ${h >= 12 ? "pm" : "am"}`;
}

function baseOptions() {
    return {
        responsive: true,
        maintainAspectRatio: true,
        animation: { duration: 400 },
        interaction: { mode: "index", intersect: false },
    };
}

function basePlugins() {
    return {
        legend: { display: false },
        tooltip: {
            backgroundColor: "#1c2128",
            borderColor: "#30363d",
            borderWidth: 1,
            titleColor: "#c9d1d9",
            bodyColor: "#8b949e",
            padding: 10,
        }
    };
}

function xAxis() {
    return { grid: { color: "#21262d" }, ticks: { color: "#8b949e", maxRotation: 0 }, border: { color: "#30363d" } };
}

function yAxis() {
    return { grid: { color: "#21262d" }, ticks: { color: "#8b949e" }, border: { color: "#30363d" } };
}

// ── Boot ──────────────────────────────────────────────────────────────────────
loadCharts();
