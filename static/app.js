// Steps 1-3: load process data, pick goals, show the combined ranking and shortlist.
// Step 4 (assessment.js) uses the globals declared here.

const GOALS = [
    { key: "reduce_total_duration", column: "total_duration", title: "Processing time", name: "processing time", unit: " min" },
    { key: "reduce_total_cost", column: "total_cost", title: "Cost", name: "cost", unit: "" },
    { key: "reduce_rework_duration", column: "rework_duration", title: "Rework time", name: "rework time", unit: " min" },
];
const MAX_GOALS = 2;
const MANUAL_ROWS = 3;
const MAP_FIELDS = ["case_id", "activity", "start_time", "end_time", "duration", "cost", "rate"];

let uploadId = null;
let activities = [];
let metricTotals = {};
let candidates = [];

let source = "eventlog";
let logFile = null;      // event log currently loaded
let logLabel = "";
let tableFile = null;    // activity table currently loaded
let caseCount = null;
let requestSeq = 0;      // guards against out-of-order responses

const $ = (id) => document.getElementById(id);

function show(id) { $(id).classList.remove("hidden"); }
function hide(id) { $(id).classList.add("hidden"); }

// Used by assessment.js as well: plain number with up to two decimals.
function fmt(v) {
    if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(2);
    return v;
}
const num = (v, d = 1) => Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v) => (v * 100).toFixed(1) + "%";

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

let toastTimer = null;
function toast(message) {
    const t = $("toast");
    t.textContent = message;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 3500);
}

function showError(id, message) {
    $(id).textContent = message;
    show(id);
}

function clearData() {
    uploadId = null;
    activities = [];
    hide("results-section");
    hide("assess-section");
}

// ---------- Step 1: data source ----------

function handleSourceChange() {
    source = document.querySelector('input[name="source"]:checked').value;
    ["eventlog", "activities", "manual"].forEach((s) => $("src-" + s).classList.toggle("hidden", s !== source));
    hide("upload-error");
    hide("upload-warnings");
    clearData();
    // Typed-in data only has times, so only the time goal applies.
    setAvailableGoals(source === "manual" ? ["reduce_total_duration"] : GOALS.map((g) => g.key));
    if (source === "eventlog" && logFile) mineLog();
    if (source === "activities" && tableFile) uploadTable();
}

async function postFile(endpoint, file, extra = {}) {
    const form = new FormData();
    form.append("file", file);
    Object.entries(extra).forEach(([k, v]) => form.append(k, v));
    const res = await fetch(endpoint, { method: "POST", body: form });
    return { ok: res.ok, data: await res.json() };
}

async function loadLog(file, label) {
    hide("upload-error");
    hide("upload-warnings");
    const { ok, data } = await postFile("/api/preview", file);
    if (!ok) {
        showError("upload-error", data.error || "Couldn't read that file.");
        return;
    }
    logFile = file;
    logLabel = label;
    MAP_FIELDS.forEach((field) => {
        const select = $("m-" + field);
        const optional = select.hasAttribute("data-optional");
        select.innerHTML = (optional ? '<option value="">(none)</option>' : "") +
            data.columns.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
        select.value = data.mapping[field] || (optional ? "" : data.columns[0]);
    });
    show("mapping");
    $("log-info").textContent = `${data.rows.toLocaleString()} rows loaded from ${label}`;
    await mineLog();
}

async function mineLog() {
    if (!logFile) return;
    hide("upload-error");
    hide("upload-warnings");
    const mapping = Object.fromEntries(MAP_FIELDS.map((f) => [f, $("m-" + f).value]));
    const seq = ++requestSeq;
    const { ok, data } = await postFile("/api/upload", logFile, {
        mapping: JSON.stringify(mapping),
        default_rate: $("default-rate").value,
    });
    if (seq !== requestSeq) return;
    if (!ok) {
        clearData();
        showError("upload-error", data.error || "Couldn't read the event log.");
        return;
    }
    await useActivities(data);
}

async function uploadTable() {
    if (!tableFile) return;
    hide("upload-error");
    hide("upload-warnings");
    const seq = ++requestSeq;
    const { ok, data } = await postFile("/api/upload-activities", tableFile, { duration_unit: $("duration-unit").value });
    if (seq !== requestSeq) return;
    if (!ok) {
        clearData();
        showError("upload-error", data.error || "Couldn't read the activity table.");
        return;
    }
    $("table-info").textContent = `${data.activities.length} activities loaded from ${tableFile.name}`;
    await useActivities(data);
}

function addManualRow(name = "", time = "", executions = "") {
    const tr = document.createElement("tr");
    tr.innerHTML = `
        <td><input type="text" class="manual-name" placeholder="Activity name" aria-label="Activity name"></td>
        <td><input type="number" class="manual-time" min="0" step="any" aria-label="Time in minutes"></td>
        <td><input type="number" class="manual-executions" min="0" step="1" aria-label="Executions"></td>
        <td><button type="button" class="remove-row" title="Remove activity" aria-label="Remove activity">&times;</button></td>
    `;
    tr.querySelector(".manual-name").value = name;
    tr.querySelector(".manual-time").value = time;
    tr.querySelector(".manual-executions").value = executions;
    tr.querySelector(".remove-row").addEventListener("click", () => tr.remove());
    $("manual-table").querySelector("tbody").appendChild(tr);
}

async function handleManual() {
    hide("upload-error");
    hide("upload-warnings");

    const rows = [...$("manual-table").querySelectorAll("tbody tr")]
        .map((tr) => ({
            activity: tr.querySelector(".manual-name").value.trim(),
            time: tr.querySelector(".manual-time").value,
            executions: tr.querySelector(".manual-executions").value,
        }))
        .filter((r) => r.activity || r.time !== "" || r.executions !== "");

    const payload = {
        total_processing_time: parseFloat($("total-time").value),
        activities: rows.map((r) => ({
            activity: r.activity,
            duration: r.time === "" ? null : parseFloat(r.time),
            executions: r.executions === "" ? null : Number(r.executions),
        })),
    };
    if (Number.isNaN(payload.total_processing_time)) payload.total_processing_time = null;

    const seq = ++requestSeq;
    const res = await fetch("/api/manual-activities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (seq !== requestSeq) return;

    if (!res.ok) {
        clearData();
        showError("upload-error", data.error || "Could not use these times.");
        return;
    }
    await useActivities(data);
}

async function useActivities(data) {
    uploadId = data.upload_id;
    activities = data.activities;
    metricTotals = data.metric_totals || {};
    caseCount = data.cases ?? null;

    if (data.warnings && data.warnings.length) {
        $("upload-warnings").innerHTML = "<ul>" + data.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("") + "</ul>";
        show("upload-warnings");
    }
    await runRanking();
}

// ---------- Step 2: goals ----------

const goalInput = (key) => document.querySelector(`input[name=goal][value=${key}]`);
const selectedGoalKeys = () => GOALS.map((g) => g.key).filter((k) => goalInput(k).checked && !goalInput(k).disabled);

function syncTargetFields() {
    GOALS.forEach((g) => $("tw-" + g.key).classList.toggle("hidden", !selectedGoalKeys().includes(g.key)));
}

function setAvailableGoals(keys) {
    GOALS.forEach((g) => {
        const available = keys.includes(g.key);
        goalInput(g.key).disabled = !available;
        document.querySelector(`#goal-pills label[data-goal=${g.key}]`).classList.toggle("hidden", !available);
    });
    if (!selectedGoalKeys().length) goalInput(keys[0]).checked = true;
    syncTargetFields();
}

function handleGoalToggle(event) {
    const checkbox = event.target;
    const selected = selectedGoalKeys();
    if (selected.length > MAX_GOALS) {
        checkbox.checked = false;
        toast("Choose up to two goals at once.");
    } else if (selected.length === 0) {
        checkbox.checked = true;
        toast("Keep at least one goal selected.");
    }
    syncTargetFields();
    runRanking();
}

// ---------- Step 3: ranking ----------

async function runRanking() {
    if (!uploadId) return;
    hide("rank-error");

    const goals = selectedGoalKeys().map((key) => ({ category: key, target_pct: parseFloat($("tgt-" + key).value) }));
    if (goals.some((g) => !(g.target_pct > 0 && g.target_pct <= 100))) {
        hide("results-section");
        hide("assess-section");
        showError("rank-error", "Give every selected goal a target above 0% and at most 100%.");
        return;
    }

    const seq = ++requestSeq;
    const res = await fetch("/api/rank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: uploadId, goals }),
    });
    const data = await res.json();
    if (seq !== requestSeq) return;

    if (!res.ok) {
        hide("results-section");
        showError("rank-error", data.error || "Ranking failed.");
        return;
    }

    renderRanking(data);
    $("export-link").href = `/api/export/${uploadId}`;
    show("results-section");

    // The shortlisted activities go on to the questionnaire. Rebuild it only when the
    // shortlist changes, so answers already typed in are not lost on a target tweak.
    const previous = JSON.stringify(candidates);
    candidates = data.shortlist;
    if (!candidates.length) {
        hide("assess-section");
    } else if (JSON.stringify(candidates) !== previous || $("assess-section").classList.contains("hidden")) {
        hide("assess-results");
        await buildQuestionnaire();
    }
}

function renderKpis() {
    const sum = (col) => activities.reduce((total, a) => total + (a[col] || 0), 0);
    const tiles = [[activities.length, "Activities"]];
    if (caseCount !== null) tiles.push([caseCount.toLocaleString(), "Cases"]);
    if ("total_duration" in metricTotals) {
        tiles.push([num(metricTotals.total_duration) + " min", "Total processing time (entered)"]);
        tiles.push([num(sum("total_duration")) + " min", "Sum of activity times"]);
    } else {
        tiles.push([num(sum("total_duration")) + " min", "Total processing time"]);
        tiles.push([num(sum("total_cost"), 0), "Total cost"]);
        tiles.push([num(sum("rework_duration")) + " min", "Total rework time"]);
    }
    $("kpis").innerHTML = tiles.map(([value, label]) => `<div class="kpi"><b>${value}</b><span>${label}</span></div>`).join("");
}

function renderStatus(data, goals) {
    const count = data.shortlist.length;
    $("status").innerHTML = goals.map((g) => {
        const r = data.goals[g.key];
        if (r.total <= 0) {
            return `<p class="status bad">The data contains no ${g.name} to reduce, so this goal can’t be assessed.</p>`;
        }
        const amount = `${num(r.achieved_reduction, g.unit ? 1 : 0)}${g.unit}`;
        if (r.goal_met) {
            return `<p class="status ok">${g.title} target reachable: the ${count} shortlisted activit${count === 1 ? "y gives" : "ies give"} an estimated ${pct(r.achieved_share)} reduction (${amount}), against a target of ${pct(r.target_pct / 100)}.</p>`;
        }
        return `<p class="status bad">${g.title} target not reachable: automating every activity gives an estimated ${pct(r.achieved_share)} reduction (${amount}), below the ${pct(r.target_pct / 100)} target.</p>`;
    }).join("");
}

function renderRanking(data) {
    const goals = GOALS.filter((g) => g.key in data.goals);
    const two = goals.length > 1;

    renderKpis();
    renderStatus(data, goals);

    let head1 = `<tr><th class="c" rowspan="2">Rank</th><th class="l" rowspan="2">Activity</th><th rowspan="2">Executions</th><th rowspan="2">Total time (min)</th>`;
    let head2 = "<tr>";
    goals.forEach((g) => {
        head1 += `<th class="c grp sep" colspan="2">${g.title} (target ${pct(data.goals[g.key].target_pct / 100)})</th>`;
        head2 += `<th class="sep">Share of total</th><th>Cumulative</th>`;
    });
    head1 += `${two ? '<th class="sep" rowspan="2">Combined score</th>' : ""}<th class="c sep" rowspan="2">Shortlist</th></tr>`;
    head2 += "</tr>";
    $("rank-table").querySelector("thead").innerHTML = head1 + head2;

    const executions = (a) => (a.activity_instances ? Number(a.activity_instances).toLocaleString() : "–");
    const rows = data.ranked.map((a) => {
        let cells = `<td class="c">${a.rank}</td><td class="l">${escapeHtml(a.activity)}</td><td>${executions(a)}</td><td>${num(a.total_duration || 0)}</td>`;
        goals.forEach((g) => {
            const share = a["share_" + g.column];
            cells += `<td class="sep">${pct(share)}<div class="bar"><span style="width:${Math.min(100, share * 100).toFixed(1)}%"></span></div></td><td>${pct(a["cumulative_" + g.column])}</td>`;
        });
        if (two) cells += `<td class="sep"><b>${pct(a.score)}</b></td>`;
        cells += `<td class="c sep">${a.shortlisted ? '<span class="tag">Shortlisted</span>' : ""}</td>`;
        return `<tr class="${a.shortlisted ? "short" : ""}">${cells}</tr>`;
    });
    const span = goals.length * 2 + (two ? 1 : 0) + 1;
    data.unranked.forEach((a) => {
        const label = (a.total_duration || 0) === 0 ? "Already automated" : "No contribution to these goals";
        rows.push(`<tr class="auto"><td class="c">–</td><td class="l">${escapeHtml(a.activity)}</td><td>${executions(a)}</td><td>${num(a.total_duration || 0)}</td><td colspan="${span}" class="l sep"><span class="tag grey">${label}</span></td></tr>`);
    });
    $("rank-table").querySelector("tbody").innerHTML = rows.join("");

    $("combo-note").textContent = two
        ? "With two goals, both count equally. Activities are ranked by a combined score: the average of the activity’s estimated reductions for the two goals. Activities are shortlisted from the top until both targets are reached."
        : "";
    $("total-note").textContent = "total_duration" in metricTotals
        ? "Shares are taken from the total processing time you entered, which can exceed the sum of the activity times because of waiting."
        : "";

    renderMetricsTable();
}

function renderMetricsTable() {
    const labels = {
        activity: "Activity", cases: "Cases", activity_instances: "Executions",
        min_duration: "Min time (min)", median_duration: "Median time (min)", average_duration: "Average time (min)",
        max_duration: "Max time (min)", total_duration: "Total time (min)", total_cost: "Total cost",
        rework_instances: "Rework executions", rework_duration: "Rework time (min)", rework_cost: "Rework cost",
    };
    const columns = Object.keys(labels).filter((c) => activities.some((a) => c in a));
    const table = $("activities-table");
    table.querySelector("thead").innerHTML = "<tr>" + columns.map((c) => `<th>${labels[c]}</th>`).join("") + "</tr>";
    table.querySelector("tbody").innerHTML = activities.map((a) => "<tr>" + columns.map((c) => {
        const v = a[c];
        if (c === "activity") return `<td>${escapeHtml(v)}</td>`;
        return `<td>${typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : num(v, 2)) : (v ?? "")}</td>`;
    }).join("") + "</tr>").join("");
}

// ---------- wiring ----------

document.querySelectorAll('input[name="source"]').forEach((r) => r.addEventListener("change", handleSourceChange));

$("log-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) loadLog(file, file.name);
});
$("sample-btn").addEventListener("click", async () => {
    const res = await fetch("sample_log.csv");
    if (!res.ok) return toast("The sample log couldn’t be loaded.");
    loadLog(new File([await res.blob()], "sample_log.csv", { type: "text/csv" }), "sample log (invented data)");
});
MAP_FIELDS.forEach((f) => $("m-" + f).addEventListener("change", mineLog));
$("default-rate").addEventListener("change", mineLog);

$("table-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) { tableFile = file; uploadTable(); }
});
$("duration-unit").addEventListener("change", uploadTable);

$("manual-btn").addEventListener("click", handleManual);
$("add-row-btn").addEventListener("click", () => addManualRow());
for (let i = 0; i < MANUAL_ROWS; i++) addManualRow();

document.querySelectorAll("input[name=goal]").forEach((cb) => cb.addEventListener("change", handleGoalToggle));
GOALS.forEach((g) => $("tgt-" + g.key).addEventListener("change", runRanking));

$("assess-btn").addEventListener("click", handleAssess);
