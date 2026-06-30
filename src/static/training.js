/**
 * training.js
 *
 * Loads and renders all charts on the Training page.
 *
 * Charts:
 *   - Weekly training load (bar)
 *   - Sport breakdown (donut)
 *   - Training → next-day recovery (scatter/bar)
 *   - Half ironman recovery story (dual-axis line)
 */

const charts = {};

// ── Entry Point ──────────────────────────────────────────────────────────────

async function loadCharts() {
    try {
        const [activities, weeklyLoad, sportBreakdown, raceRecovery] = await Promise.all([
            fetch("/api/activities").then(r => r.json()),
            fetch("/api/weekly_load").then(r => r.json()),
            fetch("/api/sport_breakdown").then(r => r.json()),
            fetch("/api/recovery_timeline").then(r => r.json()),
        ]);

        renderStatCards(activities);
        renderWeeklyLoadChart(weeklyLoad);
        renderSportBreakdownChart(sportBreakdown);
        renderStrainRecoveryChart(activities);
        renderRaceRecoveryChart(raceRecovery);

    } catch (err) {
        console.error("Failed to load training charts:", err);
    }
}

// ── Stat Cards ───────────────────────────────────────────────────────────────

function renderStatCards(activities) {
    // Total sessions
    document.getElementById("stat-sessions").textContent = activities.length;

    // Total hours
    const totalMins = activities.reduce((sum, a) => sum + (a.duration_mins || 0), 0);
    document.getElementById("stat-hours").textContent = (totalMins / 60).toFixed(0) + "h";

    // Avg next-day recovery on training days
    const withRecovery = activities.filter(a => a.next_day_recovery != null);
    if (withRecovery.length > 0) {
        const avg = withRecovery.reduce((s, a) => s + a.next_day_recovery, 0) / withRecovery.length;
        const el  = document.getElementById("stat-avg-recovery");
        el.textContent = Math.round(avg) + "%";
        el.className   = "stat-value " + recoveryClass(avg);
    }
}

// ── Weekly Load Chart ────────────────────────────────────────────────────────

function renderWeeklyLoadChart(data) {
    const labels = data.map(d => fmtDate(d.week));
    const hours  = data.map(d => parseFloat(d.total_hours) || 0);

    // Color bars by volume: high weeks darker purple, low weeks lighter
    const maxHours = Math.max(...hours, 1);
    const bgColors = hours.map(h => {
        const intensity = h / maxHours;
        return `rgba(124, 106, 247, ${0.3 + intensity * 0.7})`;
    });

    renderChart("chartWeeklyLoad", {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Training Hours",
                data: hours,
                backgroundColor: bgColors,
                borderRadius: 4,
                borderSkipped: false,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis() },
                y: {
                    ...yAxis(),
                    ticks: { callback: v => v + "h" }
                }
            },
            plugins: {
                ...basePlugins(),
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const week = data[ctx.dataIndex];
                            return [
                                `Hours: ${ctx.raw}h`,
                                `Sessions: ${week.sessions}`,
                                `Sports: ${week.sports || "n/a"}`,
                            ];
                        }
                    }
                }
            }
        }
    });
}

// ── Sport Breakdown Donut ────────────────────────────────────────────────────

function renderSportBreakdownChart(data) {
    const sportColors = {
        running:             "#3fb950",
        cycling:             "#58a6ff",
        open_water_swimming: "#7c6af7",
        swimming:            "#7c6af7",
        strength_training:   "#d29922",
        multi_sport:         "#f85149",
        road_biking:         "#58a6ff",
        treadmill_running:   "#3fb950",
        trail_running:       "#2ea043",
    };

    const labels = data.map(d => sportLabel(d.sport_type));
    const hours  = data.map(d => parseFloat(d.total_hours) || 0);
    const colors = data.map(d => sportColors[d.sport_type] || "#484f58");

    renderChart("chartSports", {
        type: "doughnut",
        data: {
            labels,
            datasets: [{
                data: hours,
                backgroundColor: colors,
                borderColor: "#161b22",
                borderWidth: 3,
                hoverOffset: 6,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            cutout: "65%",
            plugins: {
                legend: {
                    display: true,
                    position: "bottom",
                    labels: {
                        color: "#8b949e",
                        padding: 12,
                        font: { size: 11 },
                        boxWidth: 12,
                        boxHeight: 12,
                    }
                },
                tooltip: {
                    ...basePlugins().tooltip,
                    callbacks: {
                        label: (ctx) => {
                            const d = data[ctx.dataIndex];
                            return ` ${ctx.label}: ${d.total_hours}h (${d.sessions} sessions)`;
                        }
                    }
                }
            }
        }
    });
}

// ── Training → Recovery Chart ────────────────────────────────────────────────

function renderStrainRecoveryChart(activities) {
    // Show next-day recovery for each activity as a bar, colored by recovery score
    const withRecovery = activities.filter(a => a.next_day_recovery != null);
    const labels = withRecovery.map(a => `${fmtDate(a.date)} ${sportLabel(a.sport_type)}`);
    const values = withRecovery.map(a => a.next_day_recovery);
    const colors = values.map(recoveryColor);

    renderChart("chartStrainRecovery", {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Next-Day Recovery",
                data: values,
                backgroundColor: colors,
                borderRadius: 3,
                borderSkipped: false,
            }]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: {
                    ...xAxis(),
                    ticks: {
                        maxTicksLimit: 15,
                        maxRotation: 35,
                        color: "#8b949e",
                        font: { size: 10 },
                    }
                },
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
                        label: (ctx) => {
                            const a = withRecovery[ctx.dataIndex];
                            return [
                                `Next-day recovery: ${Math.round(ctx.raw)}%`,
                                `Duration: ${a.duration_mins} min`,
                                `Avg HR: ${a.avg_hr ? Math.round(a.avg_hr) + " bpm" : "n/a"}`,
                                a.distance_km ? `Distance: ${a.distance_km} km` : "",
                            ].filter(Boolean);
                        }
                    }
                }
            }
        }
    });
}

// ── Race Recovery Chart ──────────────────────────────────────────────────────

function renderRaceRecoveryChart(data) {
    // Dual-axis: recovery score (left) + HRV (right)
    const labels = data.map(d => fmtDate(d.date));
    const scores = data.map(d => d.recovery_score);
    const hrvs   = data.map(d => d.hrv_rmssd);

    // Mark race day (Jun 14)
    const raceIdx = data.findIndex(d => d.date && d.date.startsWith("2026-06-14"));

    renderChart("chartRaceRecovery", {
        type: "line",
        data: {
            labels,
            datasets: [
                {
                    label: "Recovery %",
                    data: scores,
                    borderColor: "#3fb950",
                    backgroundColor: "rgba(63, 185, 80, 0.1)",
                    borderWidth: 2.5,
                    pointRadius: scores.map((_, i) => i === raceIdx ? 8 : 3),
                    pointBackgroundColor: scores.map((_, i) =>
                        i === raceIdx ? "#f85149" : recoveryColor(scores[i])
                    ),
                    fill: true,
                    tension: 0.3,
                    yAxisID: "yRecovery",
                },
                {
                    label: "HRV (ms)",
                    data: hrvs,
                    borderColor: "#7c6af7",
                    borderWidth: 2,
                    borderDash: [5, 3],
                    pointRadius: 0,
                    fill: false,
                    tension: 0.3,
                    yAxisID: "yHRV",
                }
            ]
        },
        options: {
            ...baseOptions(),
            scales: {
                x: { ...xAxis() },
                yRecovery: {
                    ...yAxis(),
                    position: "left",
                    min: 0, max: 100,
                    title: { display: true, text: "Recovery %", color: "#8b949e" },
                    ticks: { callback: v => v + "%" },
                },
                yHRV: {
                    ...yAxis(),
                    position: "right",
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: "HRV (ms)", color: "#8b949e" },
                    ticks: { callback: v => v + " ms" },
                }
            },
            plugins: {
                ...basePlugins(),
                legend: {
                    display: true,
                    position: "top",
                    labels: {
                        color: "#8b949e",
                        font: { size: 12 },
                        boxWidth: 12,
                    }
                },
                tooltip: {
                    ...basePlugins().tooltip,
                    callbacks: {
                        label: ctx => {
                            if (ctx.dataset.label === "Recovery %") {
                                return `Recovery: ${Math.round(ctx.raw)}%`;
                            }
                            return `HRV: ${Math.round(ctx.raw)} ms`;
                        },
                        afterBody: (items) => {
                            const idx = items[0]?.dataIndex;
                            if (idx === raceIdx) return ["🏁 RACE DAY — Half Ironman"];
                            return [];
                        }
                    }
                }
            }
        }
    });
}

// ── Shared Helpers ───────────────────────────────────────────────────────────

function sportLabel(typeKey) {
    const labels = {
        running:             "Run",
        cycling:             "Bike",
        open_water_swimming: "Swim",
        swimming:            "Swim",
        strength_training:   "Strength",
        multi_sport:         "Triathlon",
        road_biking:         "Bike",
        treadmill_running:   "Run",
        trail_running:       "Trail Run",
    };
    return labels[typeKey] || typeKey?.replace(/_/g, " ") || "Unknown";
}

function recoveryClass(score) {
    if (score >= 67) return "green";
    if (score >= 34) return "yellow";
    return "red";
}

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

// ── Boot ─────────────────────────────────────────────────────────────────────
loadCharts();
