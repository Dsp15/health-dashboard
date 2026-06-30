/**
 * daily.js
 *
 * Loads and renders all charts on the Daily Health page.
 *
 * Flow:
 *   1. Page loads → loadCharts() fetches data from Flask API endpoints
 *   2. Each fetch returns JSON from PostgreSQL
 *   3. We transform the data and pass it to Chart.js
 *   4. When WebSocket fires "sync_complete", loadCharts() runs again
 *      and updates all charts without a page refresh
 */

// Store chart instances so we can destroy/recreate on refresh
const charts = {};

// ── Entry Point ─────────────────────────────────────────────────────────────

async function loadCharts() {
    try {
        // Fetch all data in parallel — much faster than one at a time
        const [todayData, recoveryData, sleepData] = await Promise.all([
            fetch("/api/today").then(r => r.json()),
            fetch("/api/recovery").then(r => r.json()),
            fetch("/api/sleep").then(r => r.json()),
        ]);

        renderStatCards(todayData);
        renderRecoveryChart(recoveryData);
        renderHRVChart(recoveryData);
        renderRestingHRChart(recoveryData);
        renderSleepChart(sleepData);
        renderSleepPerfChart(sleepData);
        renderBedtimeChart(sleepData);

    } catch (err) {
        console.error("Failed to load charts:", err);
    }
}

// ── Stat Cards ───────────────────────────────────────────────────────────────

function renderStatCards(data) {
    const rec   = data.recovery || {};
    const sleep = data.sleep    || {};

    // Recovery score
    const score = rec.recovery_score;
    if (score != null) {
        const el  = document.getElementById("stat-recovery");
        el.textContent = Math.round(score) + "%";
        el.className   = "stat-value " + recoveryClass(score);

        const bar = document.getElementById("bar-recovery");
        bar.style.width      = score + "%";
        bar.style.background = recoveryColor(score);
    }

    // HRV
    setCard("stat-hrv", rec.hrv_rmssd, v => Math.round(v) + " ms");

    // Resting HR
    setCard("stat-hr", rec.resting_hr, v => Math.round(v));

    // Sleep hours
    setCard("stat-sleep", sleep.total_in_bed_hours, v => v.toFixed(1) + "h");

    // Sleep performance
    setCard("stat-sleep-perf", sleep.sleep_performance_pct, v => Math.round(v) + "%");

    // Bedtime
    if (sleep.start_time) {
        const d = new Date(sleep.start_time);
        const h = d.getHours();
        const m = d.getMinutes().toString().padStart(2, "0");
        const ampm = h >= 12 ? "pm" : "am";
        const h12  = h % 12 || 12;
        document.getElementById("stat-bedtime").textContent = `${h12}:${m} ${ampm}`;
    }
}

function setCard(id, value, fmt) {
    if (value != null) {
        document.getElementById(id).textContent = fmt(value);
    }
}

function recoveryClass(score) {
    if (score >= 67) return "green";
    if (score >= 34) return "yellow";
    return "red";
}

// ── Recovery Chart ───────────────────────────────────────────────────────────

function renderRecoveryChart(data) {
    const labels = data.map(d => fmtDate(d.date));
    const values = data.map(d => d.recovery_score);
    const colors = values.map(recoveryColor);

    renderChart("chartRecovery", {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Recovery %",
                data: values,
                backgroundColor: colors,
                borderRadius: 3,
                borderSkipped: false,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 12 } },
                y: {
                    ...yAxis(),
                    min: 0, max: 100,
                    ticks: { callback: v => v + "%" }
                }
            },
            plugins: {
                ...basePlugins(),
                tooltip: {
                    callbacks: {
                        label: ctx => `Recovery: ${Math.round(ctx.raw)}%`
                    }
                }
            }
        }
    });
}

// ── HRV Chart ────────────────────────────────────────────────────────────────

function renderHRVChart(data) {
    const labels = data.map(d => fmtDate(d.date));
    const values = data.map(d => d.hrv_rmssd);

    renderChart("chartHRV", {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "HRV (rMSSD)",
                data: values,
                borderColor: "#7c6af7",
                backgroundColor: "rgba(124, 106, 247, 0.1)",
                borderWidth: 2,
                pointRadius: 0,
                fill: true,
                tension: 0.4,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 8 } },
                y: {
                    ...yAxis(),
                    ticks: { callback: v => v + " ms" }
                }
            },
            plugins: {
                ...basePlugins(),
                tooltip: { callbacks: { label: ctx => `HRV: ${Math.round(ctx.raw)} ms` } }
            }
        }
    });
}

// ── Resting HR Chart ─────────────────────────────────────────────────────────

function renderRestingHRChart(data) {
    const labels = data.map(d => fmtDate(d.date));
    const values = data.map(d => d.resting_hr);

    renderChart("chartRestingHR", {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Resting HR",
                data: values,
                borderColor: "#f85149",
                backgroundColor: "rgba(248, 81, 73, 0.08)",
                borderWidth: 2,
                pointRadius: 0,
                fill: true,
                tension: 0.4,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 8 } },
                y: {
                    ...yAxis(),
                    ticks: { callback: v => v + " bpm" }
                }
            },
            plugins: {
                ...basePlugins(),
                tooltip: { callbacks: { label: ctx => `Resting HR: ${Math.round(ctx.raw)} bpm` } }
            }
        }
    });
}

// ── Sleep Stacked Bar Chart ───────────────────────────────────────────────────

function renderSleepChart(data) {
    const labels = data.map(d => fmtDate(d.date));

    renderChart("chartSleep", {
        type: "bar",
        data: {
            labels,
            datasets: [
                {
                    label: "Deep",
                    data: data.map(d => d.deep_sleep_hours),
                    backgroundColor: "#3fb950",
                    borderRadius: 2,
                    stack: "sleep",
                },
                {
                    label: "REM",
                    data: data.map(d => d.rem_sleep_hours),
                    backgroundColor: "#7c6af7",
                    stack: "sleep",
                },
                {
                    label: "Light",
                    data: data.map(d => d.light_sleep_hours),
                    backgroundColor: "#58a6ff",
                    stack: "sleep",
                },
                {
                    label: "Awake",
                    data: data.map(d => d.awake_hours),
                    backgroundColor: "#484f58",
                    stack: "sleep",
                },
            ]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), stacked: true, ticks: { maxTicksLimit: 12 } },
                y: {
                    ...yAxis(),
                    stacked: true,
                    ticks: { callback: v => v + "h" }
                }
            },
            plugins: {
                ...basePlugins(),
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${ctx.raw?.toFixed(1)}h`
                    }
                }
            }
        }
    });
}

// ── Sleep Performance Chart ───────────────────────────────────────────────────

function renderSleepPerfChart(data) {
    const labels = data.map(d => fmtDate(d.date));
    const values = data.map(d => d.sleep_performance_pct);

    renderChart("chartSleepPerf", {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Sleep Performance",
                data: values,
                borderColor: "#58a6ff",
                backgroundColor: "rgba(88, 166, 255, 0.1)",
                borderWidth: 2,
                pointRadius: 0,
                fill: true,
                tension: 0.4,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 8 } },
                y: {
                    ...yAxis(),
                    min: 0, max: 100,
                    ticks: { callback: v => v + "%" }
                }
            },
            plugins: {
                ...basePlugins(),
                tooltip: { callbacks: { label: ctx => `Sleep score: ${Math.round(ctx.raw)}%` } }
            }
        }
    });
}

// ── Bedtime Chart ─────────────────────────────────────────────────────────────

function renderBedtimeChart(data) {
    // Convert bedtime to decimal hours past midnight for plotting
    // e.g. 11pm = 23.0, 1am = 25.0 (so chart reads left-to-right as "later")
    const labels = data.map(d => fmtDate(d.date));
    const values = data.map(d => {
        if (!d.start_time) return null;
        const t = new Date(d.start_time);
        let h = t.getHours() + t.getMinutes() / 60;
        // If before 6am, add 24 so "1am" plots as 25, not 1
        if (h < 6) h += 24;
        return Math.round(h * 10) / 10;
    });

    renderChart("chartBedtime", {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Bedtime",
                data: values,
                borderColor: "#d29922",
                backgroundColor: "rgba(210, 153, 34, 0.08)",
                borderWidth: 2,
                pointRadius: 0,
                fill: true,
                tension: 0.3,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis(), ticks: { maxTicksLimit: 8 } },
                y: {
                    ...yAxis(),
                    min: 20, max: 28,
                    ticks: {
                        callback: v => {
                            const h = v % 24;
                            const ampm = h >= 12 ? "pm" : "am";
                            const h12  = h % 12 || 12;
                            return `${h12}${ampm}`;
                        }
                    }
                }
            },
            plugins: {
                ...basePlugins(),
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const raw = ctx.raw;
                            const h   = raw % 24;
                            const m   = Math.round((h % 1) * 60).toString().padStart(2, "0");
                            const h12 = Math.floor(h) % 12 || 12;
                            const ap  = h >= 12 ? "pm" : "am";
                            return `Bedtime: ${h12}:${m} ${ap}`;
                        }
                    }
                }
            }
        }
    });
}

// ── Chart Helpers ─────────────────────────────────────────────────────────────

/**
 * Create or update a Chart.js chart.
 * Destroying the old instance before creating a new one prevents
 * Chart.js from showing ghost tooltips from the previous render.
 */
function renderChart(id, config) {
    if (charts[id]) charts[id].destroy();
    const ctx = document.getElementById(id);
    if (!ctx) return;
    charts[id] = new Chart(ctx, config);
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
    return {
        grid:   { color: "#21262d" },
        ticks:  { color: "#8b949e", maxRotation: 0 },
        border: { color: "#30363d" },
    };
}

function yAxis() {
    return {
        grid:   { color: "#21262d" },
        ticks:  { color: "#8b949e" },
        border: { color: "#30363d" },
    };
}

// ── Boot ──────────────────────────────────────────────────────────────────────
loadCharts();
