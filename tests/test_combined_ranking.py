"""
One combined ranking and shortlist for several goals, each goal weighing the same.

Worked example (every activity 100% automatable):

  activity   time   cost   time share   cost share   score (mean)
  A           50    100      0.50         0.10          0.30
  B           30    600      0.30         0.60          0.45
  C           20    300      0.20         0.30          0.25
  total      100   1000

Ranked by score: B, A, C.
"""

import io
from pathlib import Path

import pytest

from app import create_app
from pmm4rpaai.ranking.engine import rank_combined, rank_for_goal

FIXTURES = Path(__file__).parent / "fixtures"

ACTIVITIES = [
    {"activity": "A", "total_duration": 50.0, "total_cost": 100.0, "rework_duration": 0.0, "automation_rate": 1.0},
    {"activity": "B", "total_duration": 30.0, "total_cost": 600.0, "rework_duration": 0.0, "automation_rate": 1.0},
    {"activity": "C", "total_duration": 20.0, "total_cost": 300.0, "rework_duration": 0.0, "automation_rate": 1.0},
]
TIME = "reduce_total_duration"
COST = "reduce_total_cost"
REWORK = "reduce_rework_duration"


def _goals(**targets):
    return [{"category": key, "target_pct": pct} for key, pct in targets.items()]


def test_two_goals_rank_by_mean_share():
    result = rank_combined(ACTIVITIES, _goals(**{TIME: 40, COST: 40}))

    assert [a["activity"] for a in result["ranked"]] == ["B", "A", "C"]
    assert [a["score"] for a in result["ranked"]] == pytest.approx([0.45, 0.30, 0.25])
    assert [a["rank"] for a in result["ranked"]] == [1, 2, 3]


def test_shortlist_grows_until_every_target_is_reached():
    # B alone gives 60% of cost (target 40% met) but only 30% of time (target 40% not met),
    # so A is added: time 80%, cost 70%. C is not needed.
    result = rank_combined(ACTIVITIES, _goals(**{TIME: 40, COST: 40}))

    assert result["shortlist"] == ["B", "A"]
    assert [a["shortlisted"] for a in result["ranked"]] == [True, True, False]
    assert result["goals"][TIME]["achieved_share"] == pytest.approx(0.80)
    assert result["goals"][COST]["achieved_share"] == pytest.approx(0.70)
    assert result["goals"][TIME]["achieved_reduction"] == pytest.approx(80)
    assert result["goals"][COST]["achieved_reduction"] == pytest.approx(700)
    assert result["goals"][TIME]["goal_met"] and result["goals"][COST]["goal_met"]


def test_cumulative_shares_run_down_the_ranking():
    result = rank_combined(ACTIVITIES, _goals(**{TIME: 40, COST: 40}))

    assert [a["cumulative_total_duration"] for a in result["ranked"]] == pytest.approx([0.30, 0.80, 1.00])
    assert [a["cumulative_total_cost"] for a in result["ranked"]] == pytest.approx([0.60, 0.70, 1.00])


def test_goals_weigh_the_same_whatever_their_order():
    one = rank_combined(ACTIVITIES, _goals(**{TIME: 40, COST: 40}))
    other = rank_combined(ACTIVITIES, _goals(**{COST: 40, TIME: 40}))

    assert one["shortlist"] == other["shortlist"]
    assert [a["score"] for a in one["ranked"]] == pytest.approx([a["score"] for a in other["ranked"]])


@pytest.mark.parametrize("column, key", [("total_duration", TIME), ("total_cost", COST)])
@pytest.mark.parametrize("target_pct", [10, 35, 60, 100])
def test_single_goal_matches_the_single_goal_algorithm(column, key, target_pct):
    single = rank_for_goal(ACTIVITIES, column, target_pct)
    combined = rank_combined(ACTIVITIES, _goals(**{key: target_pct}))

    assert combined["shortlist"] == [a["activity"] for a in single["ranked"] if a["is_candidate"]]
    assert combined["goals"][key]["goal_met"] == single["goal_met"]
    assert combined["goals"][key]["achieved_reduction"] == pytest.approx(single["achieved_reduction"])


def test_activities_with_no_contribution_are_left_out_of_the_ranking():
    activities = ACTIVITIES + [
        {"activity": "Receive", "total_duration": 0.0, "total_cost": 0.0, "rework_duration": 0.0, "automation_rate": 1.0}
    ]
    result = rank_combined(activities, _goals(**{TIME: 100}))

    assert [a["activity"] for a in result["unranked"]] == ["Receive"]
    assert "Receive" not in result["shortlist"]
    assert result["shortlist"] == ["A", "B", "C"]


def test_goal_with_nothing_to_reduce_is_not_met():
    result = rank_combined(ACTIVITIES, _goals(**{TIME: 10, REWORK: 10}))

    assert not result["goals"][REWORK]["goal_met"]
    assert result["goals"][REWORK]["total"] == 0
    # The unreachable goal keeps the shortlist open, so every contributing activity is on it.
    assert result["shortlist"] == ["A", "B", "C"]


def test_entered_total_replaces_the_activity_sum():
    result = rank_combined(ACTIVITIES, _goals(**{TIME: 10}), {"total_duration": 400})

    assert result["goals"][TIME]["total"] == 400
    assert result["goals"][TIME]["target_reduction"] == pytest.approx(40)
    assert result["shortlist"] == ["A"]
    assert result["goals"][TIME]["achieved_share"] == pytest.approx(0.125)


# ---- through the API ----

@pytest.fixture
def client():
    return create_app().test_client()


LOG = (
    "case,task,begin,finish,rate\n"
    "1,Enter,2024-01-01T08:00:00,2024-01-01T08:30:00,20\n"
    "1,Check,2024-01-01T09:00:00,2024-01-01T09:10:00,60\n"
    "1,Enter,2024-01-01T10:00:00,2024-01-01T10:30:00,20\n"
    "2,Enter,2024-01-02T08:00:00,2024-01-02T08:30:00,20\n"
    "2,Check,2024-01-02T09:00:00,2024-01-02T09:10:00,\n"
)


def _upload(client, **fields):
    data = {"file": (io.BytesIO(LOG.encode()), "log.csv"), **fields}
    return client.post("/api/upload", data=data, content_type="multipart/form-data")


def test_preview_guesses_columns(client):
    res = client.post("/api/preview", data={"file": (io.BytesIO(LOG.encode()), "log.csv")},
                      content_type="multipart/form-data")
    body = res.get_json()

    assert res.status_code == 200
    assert body["columns"] == ["case", "task", "begin", "finish", "rate"]
    assert body["rows"] == 5
    assert body["mapping"] == {
        "case_id": "case", "activity": "task", "start_time": "begin", "end_time": "finish",
        "duration": None, "cost": None, "rate": "rate",
    }


def test_upload_then_rank_two_goals(client):
    res = _upload(client, default_rate="30")
    body = res.get_json()
    assert res.status_code == 200
    assert body["cases"] == 2

    by_name = {a["activity"]: a for a in body["activities"]}
    # Enter: 3 x 30 min at 20/h = 30. Check: 10 min at 60/h + 10 min at the default 30/h = 15.
    assert by_name["Enter"]["total_duration"] == pytest.approx(90)
    assert by_name["Enter"]["total_cost"] == pytest.approx(30)
    assert by_name["Check"]["total_cost"] == pytest.approx(15)
    assert by_name["Enter"]["rework_duration"] == pytest.approx(30)

    res = client.post("/api/rank", json={
        "upload_id": body["upload_id"],
        "goals": [{"category": TIME, "target_pct": 10}, {"category": COST, "target_pct": 10}],
    })
    ranking = res.get_json()
    assert res.status_code == 200
    assert ranking["shortlist"] == ["Enter"]
    assert ranking["ranked"][0]["score"] == pytest.approx((90 / 110 + 30 / 45) / 2)

    export = client.get(f"/api/export/{body['upload_id']}")
    lines = export.get_data(as_text=True).splitlines()
    assert lines[0].split(",")[:2] == ["rank", "activity"]
    assert "combined_score" in lines[0] and lines[0].endswith("shortlisted")
    assert lines[1].startswith("1,Enter,") and lines[1].endswith(",yes")


def test_rank_rejects_bad_targets(client):
    upload_id = _upload(client).get_json()["upload_id"]
    for target in (0, -5, 150, "ten"):
        res = client.post("/api/rank", json={
            "upload_id": upload_id, "goals": [{"category": TIME, "target_pct": target}],
        })
        assert res.status_code == 400


def test_repair_log_two_goals_end_to_end(client):
    with open(FIXTURES / "RepairExample-eventlog.csv", "rb") as f:
        res = client.post("/api/upload", data={"file": (f, "repair.csv")}, content_type="multipart/form-data")
    body = res.get_json()
    assert res.status_code == 200

    ranking = client.post("/api/rank", json={
        "upload_id": body["upload_id"],
        "goals": [{"category": TIME, "target_pct": 20}, {"category": COST, "target_pct": 20}],
    }).get_json()

    assert ranking["shortlist"]
    assert all(g["goal_met"] for g in ranking["goals"].values())
    scores = [a["score"] for a in ranking["ranked"]]
    assert scores == sorted(scores, reverse=True)
    for g in ranking["goals"].values():
        assert ranking["ranked"][-1][f"cumulative_{g['column']}"] == pytest.approx(1.0)
