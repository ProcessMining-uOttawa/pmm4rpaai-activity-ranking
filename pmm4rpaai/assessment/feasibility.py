"""Questionnaire-based assessment of candidate activities, task by task (phase 2 without a UI log).

Each candidate activity is split into tasks. Every task gets a value from 0 to 100 on six
criteria, read as a barrier to automation: 0 = no obstacle, 100 = complete obstacle.
The exception-frequency value is the task's exception % itself.

The same six values drive all three outputs; each output has its own weights (in %, meant to
sum to 100), because a criterion that blocks automation is not necessarily one that makes a bot
fail or run slowly. A weighted barrier is
  W(v, w) = sum(w_i / 100 * v_i)                       (0-100 when the weights sum to 100)

Per task:
  feasibility_pct  = max(0, 100 - W(v, w_feasibility))
  failure_rate_pct = FR_min + (FR_max - FR_min) * W(v, w_failure) / 100
  bot_time_ratio   = r_min + (r_max - r_min) * W(v, w_bot_time) / 100    (% of the human time)
  bot_time         = task minutes * bot_time_ratio / 100                 (automated tasks only)

The weighted barrier places the task within the range measured in previous studies:
  - bot failure rate 3-34 %: Prucha 2023, arXiv:2305.00205 -- success rate of 12 production
    bots; upper and lower quartiles (97 % and 66 % success).
  - bot time 14-39 % of the human time: Aydiner, Ortakoy & Ozsurunc 2023, IJISPM 11(1),
    Table 2 -- 54 RPA processes; fastest (treasury) and slowest (marketing) business unit.

Uncertain inputs use a three-point estimate (optimistic / likely / pessimistic): the exception %.
Every output is computed once per scenario, which gives the Low / Mid / High levels the
simulation's Taguchi design needs (PMM4RPAAI-Sim factors).

Per activity, per scenario (automated tasks = feasibility >= threshold in the likely scenario):
  feasibility_pct  = task feasibility weighted by task minutes
  failure_rate_pct = automated tasks' failure rate weighted by task minutes (the measured rates
                     are per bot, so the activity stays within the same range)
  bot_time         = sum of the automated tasks' bot times
  auto_branch_time = bot_time + human minutes of the tasks left to a person
  bots             = ceil(executions * bot_time / (days * hours * 60 * utilization))
"""

from __future__ import annotations

import math

# Each criterion's value is a barrier: "zero" / "hundred" describe the two ends of the scale.
QUESTIONS: list[dict] = [
    {"key": "rule_based", "label": "Rule-based",
     "zero": "Fully rule-based (if X then Y)", "hundred": "Entirely judgment"},
    {"key": "data_structure", "label": "Data structure",
     "zero": "Structured (forms, database fields)", "hundred": "Unstructured (free text, images, paper)"},
    {"key": "decision_complexity", "label": "Decision complexity",
     "zero": "Simple, fixed decisions", "hundred": "Expert judgment"},
    {"key": "system_interaction", "label": "System interaction",
     "zero": "Few stable digital systems", "hundred": "Non-digital or unstable systems"},
    {"key": "human_interaction", "label": "Human interaction",
     "zero": "None", "hundred": "Heavy (negotiation, calls)"},
    {"key": "exception_frequency", "label": "Exception frequency",
     "zero": "No exceptions", "hundred": "Every case is an exception"},
]
QUESTION_KEYS = [q["key"] for q in QUESTIONS]
SCORED_KEYS = [k for k in QUESTION_KEYS if k != "exception_frequency"]

# The three outputs calculated from the criteria, each with its own weight set.
OUTPUTS = ["feasibility", "failure", "bot_time"]

# Starting weights in %, each set summing to 100; the analyst sets their own.
#   feasibility: how much each criterion blocks automation.
#   failure:     exceptions and unstable systems are what make bots fail (Wellmann et al. 2020:
#                failure rate and stability; Prucha 2023: erratic bots).
#   bot_time:    navigating systems, reading unstructured data and waiting on people slow a bot.
DEFAULT_WEIGHTS = {
    "feasibility": {
        "rule_based": 20, "data_structure": 20, "decision_complexity": 15,
        "system_interaction": 15, "human_interaction": 15, "exception_frequency": 15,
    },
    "failure": {
        "rule_based": 10, "data_structure": 15, "decision_complexity": 10,
        "system_interaction": 25, "human_interaction": 0, "exception_frequency": 40,
    },
    "bot_time": {
        "rule_based": 5, "data_structure": 25, "decision_complexity": 10,
        "system_interaction": 25, "human_interaction": 20, "exception_frequency": 15,
    },
}

# Three-point estimate: scenario -> which estimate of the uncertain inputs it uses.
SCENARIOS = {"optimistic": "low", "likely": "likely", "pessimistic": "high"}
ESTIMATES = ("low", "likely", "high")

DEFAULT_PARAMS = {
    "automation_threshold_pct": 60.0, # tasks at or above this feasibility are automated
    "period_days": 30.0,              # days the activity's executions were observed over
    "bot_hours_per_day": 24.0,
    "utilization": 0.8,               # share of working time a bot is busy
    # Range of bot failure rates measured by Prucha (2023).
    "failure_min_pct": 3.0,
    "failure_max_pct": 34.0,
    # Range of bot time as % of the human time measured by Aydiner et al. (2023).
    "bot_time_min_pct": 14.0,
    "bot_time_max_pct": 39.0,
}

# PMM4RPAAI-Sim factor ids (core/constants.py) and how each is filled from the assessment.
SIM_FACTORS = [
    {"id": "pct_auto", "label": "% automated (Auto)", "kind": "percentage"},
    {"id": "pct_ok", "label": "% auto-success (OK)", "kind": "percentage"},
    {"id": "t_auto", "label": "Auto-Time mean (s)", "kind": "duration_s"},
    {"id": "num_bots", "label": "Bot pool size", "kind": "categorical"},
]


def weighted_barrier(values: dict, weights: dict) -> float:
    """sumproduct(weights, values), weights in % and values 0-100 barriers."""
    return sum(weights[k] / 100 * values[k] for k in QUESTION_KEYS)


def automation_feasibility(values: dict, weights: dict) -> float:
    """max(0, 100 - sumproduct(weights, values))."""
    return max(0.0, 100 - weighted_barrier(values, weights))


def _within(low: float, high: float, barrier: float) -> float:
    """Place a 0-100 barrier on the range [low, high]; capped so it never leaves the range."""
    return low + (high - low) * min(max(barrier, 0.0), 100.0) / 100


def assess_task(task: dict, estimate: str, weights: dict, params: dict) -> dict:
    """One task under one estimate ("low" / "likely" / "high")."""
    values = {**task["answers"], "exception_frequency": task["exception_pct"][estimate]}
    failure_barrier = weighted_barrier(values, weights["failure"])
    time_barrier = weighted_barrier(values, weights["bot_time"])
    return {
        "values": values,
        "feasibility_pct": automation_feasibility(values, weights["feasibility"]),
        "failure_rate_pct": _within(params["failure_min_pct"], params["failure_max_pct"], failure_barrier),
        "bot_time_ratio_pct": _within(params["bot_time_min_pct"], params["bot_time_max_pct"], time_barrier),
    }


def _distinct_bot_levels(levels: list[int]) -> list[int]:
    """The Taguchi design needs 3 distinct levels; spread around the likely value if they collide."""
    if len(set(levels)) == 3:
        return levels
    center = levels[1]
    return [center - 1, center, center + 1] if center >= 2 else [1, 2, 3]


def assess_activity(activity: dict, tasks: list[dict], weights: dict, params: dict) -> dict:
    """
    activity: per-activity record (total_duration in minutes, activity_instances).
    tasks:    [{task, minutes, answers{SCORED_KEYS: 0-100 barrier}, exception_pct{low, likely, high}}]
    weights:  {feasibility | failure | bot_time: {QUESTION_KEYS: weight in %}}
    """
    warnings: list[str] = []
    executions = activity.get("activity_instances") or 0
    human_time = activity["total_duration"] / executions if executions > 0 else None
    task_minutes = sum(t["minutes"] for t in tasks)

    if human_time is not None and abs(task_minutes - human_time) > 0.1 * human_time:
        warnings.append(
            f"Task times add up to {task_minutes:g} min, but the activity takes "
            f"{human_time:.2f} min per execution."
        )

    per_task = []
    for t in tasks:
        results = {s: assess_task(t, est, weights, params) for s, est in SCENARIOS.items()}
        automated = results["likely"]["feasibility_pct"] >= params["automation_threshold_pct"]
        for result in results.values():
            result["bot_time"] = t["minutes"] * result["bot_time_ratio_pct"] / 100 if automated else None
        per_task.append({"task": t["task"], "minutes": t["minutes"], "automated": automated, "scenarios": results})

    automated_tasks = [t for t in per_task if t["automated"]]
    automated_minutes = sum(t["minutes"] for t in automated_tasks)
    manual_minutes = sum(t["minutes"] for t in per_task if not t["automated"])
    capacity = params["period_days"] * params["bot_hours_per_day"] * 60 * params["utilization"]

    def time_weighted(tasks_, s, key, total):
        return sum(t["scenarios"][s][key] * t["minutes"] for t in tasks_) / total if total > 0 else 0.0

    scenarios = {}
    for s in SCENARIOS:
        bot_time = sum(t["scenarios"][s]["bot_time"] for t in automated_tasks)
        bots = None
        if executions > 0:
            bots = max(1, math.ceil(executions * bot_time / capacity)) if bot_time > 0 else 0
        scenarios[s] = {
            "feasibility_pct": time_weighted(per_task, s, "feasibility_pct", task_minutes),
            "failure_rate_pct": time_weighted(automated_tasks, s, "failure_rate_pct", automated_minutes),
            "bot_time": bot_time,
            "auto_branch_time": bot_time + manual_minutes,
            "bots": bots,
        }

    sim_factors = None
    if not automated_tasks:
        warnings.append("No task reaches the automation threshold, so there is nothing to simulate.")
    elif executions <= 0:
        warnings.append("Enter the number of executions to get the number of bots and simulation inputs.")
    else:
        order = ["pessimistic", "likely", "optimistic"]  # low -> high for % automated and % success
        levels = {
            "pct_auto": [round(scenarios[s]["feasibility_pct"], 1) for s in order],
            "pct_ok": [round(100 - scenarios[s]["failure_rate_pct"], 1) for s in order],
            # Shortest bot branch is the optimistic one; seconds, as the simulation expects.
            "t_auto": [round(scenarios[s]["auto_branch_time"] * 60, 1) for s in reversed(order)],
            "num_bots": _distinct_bot_levels([scenarios[s]["bots"] for s in reversed(order)]),
        }
        sim_factors = [{**f, "levels": levels[f["id"]]} for f in SIM_FACTORS]
        for f in sim_factors:
            if len(set(f["levels"])) < 3:
                warnings.append(
                    f"'{f['label']}' has repeated levels {f['levels']}; widen the exception estimates."
                )
        if manual_minutes > 0:
            warnings.append(
                f"{manual_minutes:g} min of tasks stay with a person; they are added to the bot branch "
                "time (Auto-Time), because the simulation sends a whole case to the bot or to a person."
            )

    return {
        "activity": activity["activity"],
        "executions": executions,
        "human_time_per_execution": human_time,
        "task_minutes": task_minutes,
        "tasks": per_task,
        "scenarios": scenarios,
        "sim_factors": sim_factors,
        "warnings": warnings,
    }
