"""
Task-level questionnaire with three-point estimates.

Criterion values are barriers from 0 (no obstacle) to 100 (complete obstacle). Each output has
its own weights in %, summing to 100 (the defaults):
  feasibility  20 / 20 / 15 / 15 / 15 / 15   F  = max(0, 100 - W)
  failure      10 / 15 / 10 / 25 /  0 / 40   FR = 3 + (34 - 3) x W / 100      (Prucha 2023)
  bot time      5 / 25 / 10 / 25 / 20 / 15   r  = 14 + (39 - 14) x W / 100    (Aydiner et al. 2023)
(order: rule-based, data structure, decision complexity, system interaction, human interaction,
exception frequency; W = sum(w/100 x v)).

Worked example: activity Check, 600 min over 100 executions (6 min per execution), split into
  Open email    1 min, barriers 0 0 0 0 0,      exceptions 0 / 2 / 4 %       automated
  Extract data  3 min, barriers 10 20 10 20 0,  exceptions 4 / 8 / 12 %      automated
  Negotiate     2 min, barriers 100 x 5,        exceptions 40 %              stays with a person
Extract data, likely (exceptions 8 %):
  feasibility  W = 2 + 4 + 1.5 + 3 + 0 + 1.2 = 11.7   -> F  = 88.3 %
  failure      W = 1 + 3 + 1 + 5 + 0 + 3.2   = 13.2   -> FR = 3 + 31 x 0.132 = 7.092 %
  bot time     W = 0.5 + 5 + 1 + 5 + 0 + 1.2 = 12.7   -> r  = 14 + 25 x 0.127 = 17.175 %
                                                          bot time = 3 x 0.17175 = 0.515 min
"""

import pytest

from app import create_app
from pmm4rpaai.assessment.feasibility import (
    DEFAULT_PARAMS,
    DEFAULT_WEIGHTS,
    OUTPUTS,
    QUESTION_KEYS,
    SCORED_KEYS,
    assess_activity,
    assess_task,
    automation_feasibility,
)

W = DEFAULT_WEIGHTS
P = DEFAULT_PARAMS
NO_BARRIER = {k: 0 for k in SCORED_KEYS}
FULL_BARRIER = {k: 100 for k in SCORED_KEYS}
SOME_BARRIER = {"rule_based": 10, "data_structure": 20, "decision_complexity": 10,
                "system_interaction": 20, "human_interaction": 0}

CHECK = {"activity": "Check", "total_duration": 600.0, "activity_instances": 100}


def _task(name, minutes, answers, low, likely, high):
    return {"task": name, "minutes": minutes, "answers": answers,
            "exception_pct": {"low": low, "likely": likely, "high": high}}


TASKS = [
    _task("Open email", 1, NO_BARRIER, 0, 2, 4),
    _task("Extract data", 3, SOME_BARRIER, 4, 8, 12),
    _task("Negotiate", 2, FULL_BARRIER, 40, 40, 40),
]


@pytest.mark.parametrize("output", OUTPUTS)
def test_default_weights_sum_to_100(output):
    assert sum(W[output].values()) == 100


def test_literature_ranges():
    assert (P["failure_min_pct"], P["failure_max_pct"]) == (3, 34)
    assert (P["bot_time_min_pct"], P["bot_time_max_pct"]) == (14, 39)


def test_feasibility_formula():
    values = {**SOME_BARRIER, "exception_frequency": 8}
    # 100 - (0.2 x 10 + 0.2 x 20 + 0.15 x 10 + 0.15 x 20 + 0.15 x 0 + 0.15 x 8)
    assert automation_feasibility(values, W["feasibility"]) == pytest.approx(100 - 11.7)


def test_feasibility_never_below_zero():
    # Weights summing to 200% with every barrier at 100 would give -100; max(0, ...) keeps it at 0.
    doubled = {k: 2 * w for k, w in W["feasibility"].items()}
    values = {**FULL_BARRIER, "exception_frequency": 100}
    assert automation_feasibility(values, doubled) == 0


def test_task_outputs_from_criteria():
    result = assess_task(TASKS[1], "likely", W, P)
    assert result["values"]["exception_frequency"] == 8  # the exception % is the value itself
    assert result["feasibility_pct"] == pytest.approx(88.3)
    assert result["failure_rate_pct"] == pytest.approx(3 + 31 * 0.132)
    assert result["bot_time_ratio_pct"] == pytest.approx(14 + 25 * 0.127)


def test_no_barrier_gets_best_literature_values():
    result = assess_task(_task("Easy", 1, NO_BARRIER, 0, 0, 0), "likely", W, P)
    assert result["failure_rate_pct"] == pytest.approx(3)
    assert result["bot_time_ratio_pct"] == pytest.approx(14)


def test_full_barrier_gets_worst_literature_values():
    result = assess_task(_task("Hard", 1, FULL_BARRIER, 100, 100, 100), "likely", W, P)
    assert result["failure_rate_pct"] == pytest.approx(34)
    assert result["bot_time_ratio_pct"] == pytest.approx(39)


def test_values_stay_in_range_when_weights_exceed_100():
    doubled = {o: {k: 2 * w for k, w in ws.items()} for o, ws in W.items()}
    result = assess_task(_task("Hard", 1, FULL_BARRIER, 100, 100, 100), "likely", doubled, P)
    assert result["failure_rate_pct"] == pytest.approx(34)
    assert result["bot_time_ratio_pct"] == pytest.approx(39)


@pytest.mark.parametrize("estimate, expected", [("low", 88.9), ("likely", 88.3), ("high", 87.7)])
def test_exception_estimates_move_feasibility(estimate, expected):
    assert assess_task(TASKS[1], estimate, W, P)["feasibility_pct"] == pytest.approx(expected)


@pytest.fixture(scope="module")
def check():
    return assess_activity(CHECK, TASKS, W, P)


def test_threshold_picks_automated_tasks(check):
    assert [t["automated"] for t in check["tasks"]] == [True, True, False]


def test_task_bot_time(check):
    extract, negotiate = check["tasks"][1], check["tasks"][2]
    assert extract["scenarios"]["likely"]["bot_time"] == pytest.approx(3 * 0.17175)
    assert negotiate["scenarios"]["likely"]["bot_time"] is None


def test_activity_results_likely(check):
    likely = check["scenarios"]["likely"]
    # Feasibility weighted by task minutes: (99.7 x 1 + 88.3 x 3 + 9 x 2) / 6.
    assert likely["feasibility_pct"] == pytest.approx((99.7 + 88.3 * 3 + 9 * 2) / 6)
    # Failure of the automated tasks weighted by minutes: (3.248 x 1 + 7.092 x 3) / 4.
    assert likely["failure_rate_pct"] == pytest.approx((3.248 + 7.092 * 3) / 4)
    # Open email 1 x 14.075 % + Extract data 3 x 17.175 %.
    assert likely["bot_time"] == pytest.approx(0.14075 + 0.51525)
    assert likely["auto_branch_time"] == pytest.approx(0.656 + 2)
    assert likely["bots"] == 1


def test_sim_factor_levels(check):
    levels = {f["id"]: f["levels"] for f in check["sim_factors"]}
    assert levels["pct_auto"] == pytest.approx([63.4, 63.8, 64.1], abs=0.05)
    assert levels["pct_ok"] == pytest.approx([93.4, 93.9, 94.3], abs=0.05)
    # Bot branch time in seconds, shortest (optimistic) first.
    assert levels["t_auto"] == pytest.approx([159.0, 159.4, 159.7], abs=0.05)
    # Every scenario needs 1 bot; spread so the Taguchi design gets 3 distinct levels.
    assert levels["num_bots"] == [1, 2, 3]
    assert any("stay with a person" in w for w in check["warnings"])


def test_lower_threshold_automates_more_tasks():
    result = assess_activity(CHECK, TASKS, W, {**P, "automation_threshold_pct": 5})
    assert [t["automated"] for t in result["tasks"]] == [True, True, True]
    assert result["tasks"][2]["scenarios"]["likely"]["bot_time"] is not None


def test_analyst_can_change_literature_ranges():
    params = {**P, "bot_time_min_pct": 50, "bot_time_max_pct": 50, "failure_min_pct": 20, "failure_max_pct": 20}
    likely = assess_activity(CHECK, TASKS, W, params)["scenarios"]["likely"]
    assert likely["bot_time"] == pytest.approx(2)
    assert likely["failure_rate_pct"] == pytest.approx(20)


def test_bots_spread_around_likely_value():
    busy = {**CHECK, "total_duration": 600_000.0, "activity_instances": 100_000}
    tasks = [_task("Work", 6, NO_BARRIER, 0, 0, 0)]
    # 100,000 x 6 x 14 % = 84,000 min / 34,560 -> 3 bots in every scenario; spread around 3.
    levels = {f["id"]: f["levels"] for f in assess_activity(busy, tasks, W, P)["sim_factors"]}
    assert levels["num_bots"] == [2, 3, 4]


def test_no_executions_gives_no_sim_factors():
    result = assess_activity({**CHECK, "activity_instances": 0}, TASKS, W, P)
    assert result["sim_factors"] is None
    assert result["scenarios"]["likely"]["bots"] is None
    assert any("number of executions" in w for w in result["warnings"])


def test_nothing_automated_gives_no_sim_factors():
    result = assess_activity(CHECK, [TASKS[2]], W, P)
    assert result["sim_factors"] is None
    assert result["scenarios"]["likely"]["failure_rate_pct"] == 0
    assert any("No task reaches" in w for w in result["warnings"])


def test_warns_when_task_times_do_not_match_activity():
    result = assess_activity(CHECK, [TASKS[0]], W, P)
    assert any("Task times add up to 1 min" in w for w in result["warnings"])


@pytest.fixture
def client():
    return create_app().test_client()


def _manual(client, executions=100):
    return client.post("/api/manual-activities", json={
        "total_processing_time": 1000,
        "activities": [{"activity": "Check", "duration": 600, "executions": executions}],
    }).get_json()["upload_id"]


def _assess(client, upload_id, tasks=None, **overrides):
    body = {
        "upload_id": upload_id,
        "weights": W,
        "assessments": [{"activity": "Check", "tasks": TASKS if tasks is None else tasks}],
        **overrides,
    }
    return client.post("/api/assess", json=body)


def test_assess_endpoint_and_sim_export(client):
    upload_id = _manual(client)
    res = _assess(client, upload_id)
    assert res.status_code == 200
    data = res.get_json()
    assert data["warnings"] == []
    assert data["results"][0]["scenarios"]["likely"]["bot_time"] == pytest.approx(0.656)

    export = client.get(f"/api/sim-factors/{upload_id}")
    assert export.status_code == 200
    assert "attachment" in export.headers["Content-Disposition"]
    exported = export.get_json()
    assert exported["time_unit"] == "seconds"
    factors = exported["activities"][0]["factors"]
    assert [f["id"] for f in factors] == ["pct_auto", "pct_ok", "t_auto", "num_bots"]
    assert all(len(f["levels"]) == 3 for f in factors)


def test_assess_endpoint_warns_when_weights_do_not_sum_to_100(client):
    res = _assess(client, _manual(client), weights={**W, "failure": {k: 10 for k in QUESTION_KEYS}})
    assert res.status_code == 200
    assert any("failure weights add up to 60%" in w for w in res.get_json()["warnings"])


def test_sim_export_needs_assessment(client):
    assert client.get(f"/api/sim-factors/{_manual(client)}").status_code == 409


def test_questions_endpoint(client):
    data = client.get("/api/questions").get_json()
    assert [q["key"] for q in data["questions"]] == QUESTION_KEYS
    assert data["default_params"] == DEFAULT_PARAMS
    assert data["default_weights"] == DEFAULT_WEIGHTS


@pytest.mark.parametrize("overrides, message", [
    ({"weights": {**W, "bot_time": {**W["bot_time"], "rule_based": -1}}}, "bot_time weight for 'rule_based'"),
    ({"weights": {**W, "failure": {k: 0 for k in QUESTION_KEYS}}}, "At least one failure weight"),
    ({"weights": {k: v for k, v in W.items() if k != "feasibility"}}, "feasibility weight"),
    ({"params": {"utilization": 0}}, "'utilization' must be greater than 0"),
    ({"params": {"failure_max_pct": 101}}, "Bot failure rate must be from 0 to 100%"),
    ({"params": {"failure_min_pct": 40}}, "Lowest bot failure rate must not exceed the highest"),
    ({"params": {"bot_time_min_pct": 50}}, "Lowest bot time % must not exceed the highest"),
    ({"assessments": []}, "at least one activity"),
    ({"assessments": [{"activity": "Nope", "tasks": TASKS}]}, "Unknown activity"),
])
def test_assess_endpoint_rejects_bad_request(client, overrides, message):
    res = _assess(client, _manual(client), **overrides)
    assert res.status_code == 400
    assert message in res.get_json()["error"]


@pytest.mark.parametrize("tasks, message", [
    ([], "add at least one task"),
    ([{**TASKS[0], "task": ""}], "needs a name"),
    ([TASKS[0], TASKS[0]], "listed twice"),
    ([{**TASKS[0], "minutes": None}], "number of minutes"),
    ([{**TASKS[0], "answers": {**NO_BARRIER, "rule_based": 101}}], "from 0 to 100"),
    ([{**TASKS[0], "answers": {**NO_BARRIER, "rule_based": None}}], "from 0 to 100"),
    ([{**TASKS[0], "exception_pct": {"low": 1, "likely": None, "high": 3}}], "optimistic, likely and pessimistic"),
    ([{**TASKS[0], "exception_pct": {"low": 5, "likely": 2, "high": 3}}], "optimistic <= likely <= pessimistic"),
])
def test_assess_endpoint_rejects_bad_tasks(client, tasks, message):
    res = _assess(client, _manual(client), tasks=tasks)
    assert res.status_code == 400
    assert message in res.get_json()["error"]


def test_manual_entry_rejects_fractional_executions(client):
    res = client.post("/api/manual-activities", json={
        "total_processing_time": 10,
        "activities": [{"activity": "A", "duration": 1, "executions": 2.5}],
    })
    assert res.status_code == 400
    assert "whole number" in res.get_json()["error"]
