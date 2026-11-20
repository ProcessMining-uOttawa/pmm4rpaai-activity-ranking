"""
Typed-in process: a total processing time plus each activity's time. The time goal's
target % is taken from the entered total, not from the sum of the activity times.
"""

import pytest

from app import create_app
from pmm4rpaai.ranking.engine import rank_for_goal

ACTIVITIES = [
    {"activity": "Register", "total_duration": 5.0, "automation_rate": 1.0},
    {"activity": "Check", "total_duration": 30.0, "automation_rate": 1.0},
    {"activity": "Approve", "total_duration": 15.0, "automation_rate": 1.0},
]


def test_total_override_sets_target_from_entered_total():
    # Activities sum to 50, but the process takes 400 (waiting included): 10% = 40.
    result = rank_for_goal(ACTIVITIES, "total_duration", 10, total_override=400)

    assert result["total_metric_value"] == 400
    assert result["target_reduction"] == pytest.approx(40)
    assert [a["activity"] for a in result["ranked"] if a["is_candidate"]] == ["Check", "Approve"]
    assert result["achieved_reduction"] == pytest.approx(45)
    assert result["goal_met"]


def test_without_override_total_is_activity_sum():
    result = rank_for_goal(ACTIVITIES, "total_duration", 10)

    assert result["total_metric_value"] == 50
    assert [a["activity"] for a in result["ranked"] if a["is_candidate"]] == ["Check"]


@pytest.fixture
def client():
    return create_app().test_client()


def _enter(client, total, rows):
    return client.post("/api/manual-activities", json={"total_processing_time": total, "activities": rows})


def test_manual_entry_then_rank_picks_step_for_10_pct(client):
    res = _enter(client, 100, [
        {"activity": "Register", "duration": 4},
        {"activity": "Check", "duration": 12},
        {"activity": "Approve", "duration": 8},
    ])
    assert res.status_code == 200
    upload_id = res.get_json()["upload_id"]

    res = client.post("/api/rank", json={
        "upload_id": upload_id,
        "goals": [{"category": "reduce_total_duration", "target_pct": 10}],
    })
    assert res.status_code == 200
    data = res.get_json()
    goal = data["goals"]["reduce_total_duration"]

    assert goal["total"] == 100
    assert goal["total_is_entered"]
    assert goal["target_reduction"] == pytest.approx(10)
    assert data["shortlist"] == ["Check"]
    assert goal["goal_met"]


def test_manual_entry_goal_unreachable_when_activities_too_small(client):
    upload_id = _enter(client, 1000, [{"activity": "Check", "duration": 50}]).get_json()["upload_id"]

    goal = client.post("/api/rank", json={
        "upload_id": upload_id,
        "goals": [{"category": "reduce_total_duration", "target_pct": 10}],
    }).get_json()["goals"]["reduce_total_duration"]

    assert not goal["goal_met"]
    assert goal["achieved_reduction"] == pytest.approx(50)


def test_manual_entry_warns_when_activities_exceed_total(client):
    data = _enter(client, 10, [{"activity": "Check", "duration": 12}]).get_json()
    assert any("more than the total processing time" in w for w in data["warnings"])


@pytest.mark.parametrize("total, rows, message", [
    (None, [{"activity": "A", "duration": 1}], "Total processing time"),
    (0, [{"activity": "A", "duration": 1}], "Total processing time"),
    (10, [], "at least one activity"),
    (10, [{"activity": "", "duration": 1}], "needs a name"),
    (10, [{"activity": "A", "duration": -1}], "0 or more"),
    (10, [{"activity": "A", "duration": None}], "0 or more"),
    (10, [{"activity": "A", "duration": 1}, {"activity": "A", "duration": 2}], "listed twice"),
])
def test_manual_entry_rejects_bad_input(client, total, rows, message):
    res = _enter(client, total, rows)
    assert res.status_code == 400
    assert message in res.get_json()["error"]
