// Step 5: task-level questionnaire with three-point estimates.
// Uses globals from app.js ($, show, hide, fmt, escapeHtml, uploadId, activities, candidates);
// only called after app.js has loaded.

let questionnaire = null; // { questions, default_params } from /api/questions

const ESTIMATES = [
    { key: "low", label: "optimistic" },
    { key: "likely", label: "likely" },
    { key: "high", label: "pessimistic" },
];
// The outputs calculated from the six criteria, each with its own weight column.
const OUTPUTS = [
    { key: "feasibility", label: "Feasibility" },
    { key: "failure", label: "Failure rate" },
    { key: "bot_time", label: "Bot time" },
];
const SCENARIO_ORDER = [
    { key: "optimistic", label: "Optimistic" },
    { key: "likely", label: "Likely" },
    { key: "pessimistic", label: "Pessimistic" },
];

// Bot assumptions, grouped by the output they feed. `scale` converts the value shown
// (e.g. 20 %) to the value the API expects (0.2).
const PARAM_GROUPS = [
    {
        title: "Which tasks are automated",
        formula: "automated if likely feasibility ≥ threshold",
        params: [
            { key: "automation_threshold_pct", label: "Feasibility threshold", unit: "%",
              help: "Tasks below it stay with a person." },
        ],
    },
    {
        title: "Number of bots",
        formula: "bots = executions × bot time ÷ time one bot works",
        params: [
            { key: "period_days", label: "Days the executions cover", unit: "days",
              help: "The period over which the executions were counted." },
            { key: "bot_hours_per_day", label: "Bot working hours per day", unit: "h",
              help: "24 for unattended bots, e.g. 8 for bots that run with a person." },
            { key: "utilization", label: "Bot utilization", unit: "%", scale: 100,
              help: "Share of working time a bot is busy; the rest is buffer for peaks and restarts." },
        ],
    },
    {
        title: "Bot failure rate",
        formula: "failure = lowest + (highest − lowest) × weighted barrier ÷ 100",
        source: "Range from Průcha (2023), arXiv:2305.00205: failure rates of 12 production bots, "
            + "upper quartile 3%, lower quartile 34%.",
        params: [
            { key: "failure_min_pct", label: "Lowest (no barrier)", unit: "%" },
            { key: "failure_max_pct", label: "Highest (full barrier)", unit: "%" },
        ],
    },
    {
        title: "Bot execution time",
        formula: "bot time = task time × (lowest + (highest − lowest) × weighted barrier ÷ 100)",
        source: "Range from Aydıner, Ortaköy & Özsürünç (2023), IJISPM 11(1), Table 2: robot time in 54 RPA "
            + "processes was 14% (fastest unit) to 39% (slowest unit) of the human time.",
        params: [
            { key: "bot_time_min_pct", label: "Lowest (no barrier)", unit: "% of human" },
            { key: "bot_time_max_pct", label: "Highest (full barrier)", unit: "% of human" },
        ],
    },
];
const PARAM_DEFS = Object.fromEntries(PARAM_GROUPS.flatMap((g) => g.params.map((p) => [p.key, p])));

function readParams() {
    const params = {};
    document.querySelectorAll(".param").forEach((input) => {
        params[input.dataset.key] = parseFloat(input.value) / (PARAM_DEFS[input.dataset.key].scale || 1);
    });
    return params;
}

// Plain-language reading of the current values, shown under each group.
function updateParamSummaries() {
    const p = readParams();
    const say = (id, text) => { $(id).textContent = text; };
    say("summary-automation_threshold_pct", `Tasks scoring ${fmt(p.automation_threshold_pct)}% or more go to the bot.`);
    const minutes = p.period_days * p.bot_hours_per_day * 60 * p.utilization;
    say("summary-period_days", Number.isNaN(minutes)
        ? "Fill in all three values."
        : `One bot does ${Math.round(minutes).toLocaleString()} min of work in ${fmt(p.period_days)} days.`);
    say("summary-failure_min_pct", `An easy task fails ${fmt(p.failure_min_pct)}% of the time, `
        + `a fully blocked one ${fmt(p.failure_max_pct)}%.`);
    say("summary-bot_time_min_pct", `A 10-min task takes the bot ${fmt(p.bot_time_min_pct / 10)} to `
        + `${fmt(p.bot_time_max_pct / 10)} min, depending on its barriers.`);
}

function humanTimePerExecution(activityName) {
    const a = activities.find((x) => x.activity === activityName);
    return a && a.activity_instances > 0 ? a.total_duration / a.activity_instances : null;
}

function addTaskRow(tbody, name = "", minutes = "") {
    const scored = questionnaire.questions.filter((q) => q.key !== "exception_frequency");
    const tr = document.createElement("tr");
    tr.innerHTML = `
        <td><input type="text" class="t-name" placeholder="Task name"></td>
        <td><input type="number" class="t-minutes" min="0" step="any"></td>
        ${scored.map((q) => `<td><input type="number" class="t-score" data-key="${q.key}" min="0" max="100" step="any" placeholder="0-100"
            title="0 = ${escapeHtml(q.zero)}, 100 = ${escapeHtml(q.hundred)}"></td>`).join("")}
        ${ESTIMATES.map((e) => `<td><input type="number" class="t-exception" data-estimate="${e.key}" min="0" max="100" step="any" placeholder="%"></td>`).join("")}
        <td><button class="remove-row" title="Remove task">&times;</button></td>
    `;
    tr.querySelector(".t-name").value = name;
    tr.querySelector(".t-minutes").value = minutes;
    tr.querySelector(".remove-row").addEventListener("click", () => tr.remove());
    tbody.appendChild(tr);
}

async function buildQuestionnaire() {
    hide("assess-results");
    hide("assess-error");
    if (!candidates.length) {
        hide("assess-section");
        return;
    }
    if (!questionnaire) questionnaire = await (await fetch("/api/questions")).json();
    const scored = questionnaire.questions.filter((q) => q.key !== "exception_frequency");

    $("weights-table").querySelector("tbody").innerHTML = questionnaire.questions.map((q) => `<tr>
        <td>${q.label}</td><td>${escapeHtml(q.zero)}</td><td>${escapeHtml(q.hundred)}</td>
        ${OUTPUTS.map((o) => `<td><input type="number" class="q-weight" data-output="${o.key}" data-key="${q.key}"
            min="0" step="any" value="${questionnaire.default_weights[o.key][q.key]}"></td>`).join("")}
    </tr>`).join("");
    const updateWeightTotals = () => OUTPUTS.forEach((o) => {
        const total = [...document.querySelectorAll(`.q-weight[data-output="${o.key}"]`)]
            .reduce((sum, i) => sum + (parseFloat(i.value) || 0), 0);
        const cell = $(`weight-total-${o.key}`);
        cell.textContent = `${fmt(total)}%${Math.abs(total - 100) > 0.01 ? " (should be 100%)" : ""}`;
        cell.classList.toggle("not-met", Math.abs(total - 100) > 0.01);
    });
    document.querySelectorAll(".q-weight").forEach((input) => input.addEventListener("input", updateWeightTotals));
    updateWeightTotals();

    $("task-forms").innerHTML = candidates.map((activity, i) => {
        const human = humanTimePerExecution(activity);
        return `<div class="activity-card" data-idx="${i}">
            <h4>${escapeHtml(activity)}</h4>
            <p class="hint">${human === null
                ? "No executions entered, so time per execution, bots and simulation inputs can't be calculated."
                : `A person takes ${fmt(human)} min per execution. Task times should add up to this.`}</p>
            <div class="table-scroll">
                <table class="task-table">
                    <thead>
                        <tr><th rowspan="2">Task</th><th rowspan="2">Time (min)</th>
                            ${scored.map((q) => `<th rowspan="2" title="0 = ${escapeHtml(q.zero)}, 100 = ${escapeHtml(q.hundred)}">${q.label}<span class="scale-hint">0-100</span></th>`).join("")}
                            <th colspan="3">Exceptions (% of cases)</th>
                            <th rowspan="2"></th></tr>
                        <tr>${ESTIMATES.map((e) => `<th>${e.label}</th>`).join("")}</tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
            <button class="secondary add-task">Add task</button>
        </div>`;
    }).join("");

    document.querySelectorAll("#task-forms .activity-card").forEach((card) => {
        const tbody = card.querySelector("tbody");
        const human = humanTimePerExecution(candidates[card.dataset.idx]);
        addTaskRow(tbody, "", human === null ? "" : +human.toFixed(2));
        card.querySelector(".add-task").addEventListener("click", () => addTaskRow(tbody));
    });

    const defaults = questionnaire.default_params;
    $("params-form").innerHTML = PARAM_GROUPS.map((group) => `
        <div class="param-group">
            <h4>${group.title}</h4>
            <code class="formula">${group.formula}</code>
            ${group.source ? `<p class="source">${group.source}</p>` : ""}
            ${group.params.map((p) => `
                <label class="param-row">
                    <span>${p.label}${p.help ? `<span class="scale-hint">${p.help}</span>` : ""}</span>
                    <span class="param-input">
                        <input type="number" class="param" data-key="${p.key}" min="0" step="any"
                            value="${+(defaults[p.key] * (p.scale || 1)).toFixed(4)}">
                        <span class="unit">${p.unit}</span>
                    </span>
                </label>`).join("")}
            <p class="param-summary" id="summary-${group.params[0].key}"></p>
        </div>`).join("");
    document.querySelectorAll(".param").forEach((input) => input.addEventListener("input", updateParamSummaries));
    updateParamSummaries();

    show("assess-section");
}

function readTasks(card) {
    return [...card.querySelectorAll("tbody tr")].map((tr) => {
        const num = (el) => (el.value === "" ? null : parseFloat(el.value));
        const answers = {};
        tr.querySelectorAll(".t-score").forEach((s) => { answers[s.dataset.key] = s.value === "" ? null : Number(s.value); });
        const exception_pct = {};
        tr.querySelectorAll(".t-exception").forEach((x) => { exception_pct[x.dataset.estimate] = num(x); });
        return {
            task: tr.querySelector(".t-name").value.trim(),
            minutes: num(tr.querySelector(".t-minutes")),
            answers,
            exception_pct,
        };
    });
}

async function handleAssess() {
    hide("assess-error");
    const fail = (message) => {
        $("assess-error").textContent = message;
        show("assess-error");
    };

    const weights = Object.fromEntries(OUTPUTS.map((o) => [o.key, {}]));
    document.querySelectorAll(".q-weight").forEach((input) => {
        weights[input.dataset.output][input.dataset.key] = parseFloat(input.value);
    });
    if (OUTPUTS.some((o) => Object.values(weights[o.key]).some((w) => Number.isNaN(w)))) {
        return fail("Give every criterion a weight (0 or more) in all three columns.");
    }

    const params = readParams();
    if (Object.values(params).some((v) => Number.isNaN(v))) return fail("Fill in every bot assumption.");

    const assessments = [...document.querySelectorAll("#task-forms .activity-card")].map((card) => ({
        activity: candidates[card.dataset.idx],
        tasks: readTasks(card),
    }));

    const res = await fetch("/api/assess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: uploadId, weights, params, assessments }),
    });
    const data = await res.json();
    if (!res.ok) return fail(data.error || "Assessment failed.");

    const warnings = data.warnings.length
        ? `<div class="warnings"><ul>${data.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul></div>` : "";
    $("assess-output").innerHTML = warnings + data.results.map(renderActivityResult).join("");
    $("sim-export-link").href = `/api/sim-factors/${uploadId}`;
    $("sim-export-link").classList.toggle("hidden", !data.results.some((r) => r.sim_factors));
    show("assess-results");
}

function renderActivityResult(r) {
    const pct = (v) => `${v.toFixed(1)}%`;
    const mins = (v) => `${v.toFixed(2)} min`;
    const range = (t, key, f) => {
        const [o, l, p] = SCENARIO_ORDER.map((s) => t.scenarios[s.key][key]);
        if (l === null) return "-";
        return `${f(l)}<span class="scale-hint">${f(o)} / ${f(p)}</span>`;
    };

    const warnings = r.warnings.length
        ? `<div class="warnings"><ul>${r.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul></div>` : "";

    const taskRows = r.tasks.map((t) => `<tr class="${t.automated ? "candidate" : ""}">
        <td>${escapeHtml(t.task)}</td><td>${fmt(t.minutes)}</td><td>${t.automated ? "yes" : "no"}</td>
        <td>${range(t, "feasibility_pct", pct)}</td>
        <td>${t.automated ? range(t, "failure_rate_pct", pct) : "-"}</td>
        <td>${t.automated ? range(t, "bot_time", mins) : "-"}</td>
    </tr>`).join("");

    const summaryRows = [
        ["Automation feasibility", "feasibility_pct", pct],
        ["Bot failure rate", "failure_rate_pct", pct],
        ["Bot execution time", "bot_time", mins],
        ["Bot branch time (bot + tasks left to a person)", "auto_branch_time", mins],
        ["Number of bots", "bots", (v) => (v === null ? "needs executions" : v)],
    ].map(([label, key, f]) => `<tr><td>${label}</td>${SCENARIO_ORDER.map((s) => `<td>${f(r.scenarios[s.key][key])}</td>`).join("")}</tr>`).join("");

    const simTable = r.sim_factors ? `
        <h4>Simulation inputs (PMM4RPAAI-Sim factors)</h4>
        <table class="sim-table">
            <thead><tr><th>Factor</th><th>Low</th><th>Mid</th><th>High</th></tr></thead>
            <tbody>${r.sim_factors.map((f) => `<tr><td>${escapeHtml(f.label)} <code>${f.id}</code></td>
                ${f.levels.map((v) => `<td>${v}</td>`).join("")}</tr>`).join("")}</tbody>
        </table>` : "";

    return `<div class="activity-card">
        <h4>${escapeHtml(r.activity)}</h4>
        ${warnings}
        <div class="table-scroll"><table>
            <thead><tr><th>Task</th><th>Time (min)</th><th>Automated</th><th>Feasibility</th><th>Failure rate</th><th>Bot time</th></tr></thead>
            <tbody>${taskRows}</tbody>
        </table></div>
        <p class="hint">Task values show the likely estimate, with optimistic / pessimistic below.
            All three come from the same six values, each with its own weights. Failure rate and bot
            time place the task's weighted barrier within the range measured in previous studies
            (Průcha, 2023; Aydıner et al., 2023). For the activity, failure rate is the automated tasks'
            rate weighted by their time, and bot execution time is their sum.</p>
        <div class="table-scroll"><table>
            <thead><tr><th>Activity result</th>${SCENARIO_ORDER.map((s) => `<th>${s.label}</th>`).join("")}</tr></thead>
            <tbody>${summaryRows}</tbody>
        </table></div>
        ${simTable}
    </div>`;
}
