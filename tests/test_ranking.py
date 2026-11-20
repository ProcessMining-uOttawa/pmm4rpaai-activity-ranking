"""
Characterization test: reproduces the exact output previously produced by the
retired identify_candidates.py script (captured in tests/fixtures/activities_results.csv),
proving the generalized rank_for_goal() didn't change behavior.

Note: tests/fixtures/activities.csv now holds a flat automation_rate=1.0 (the new v1
placeholder), so it no longer matches activities_results.csv's varied rates — that file
was generated from a run with per-activity automation rates. We reconstruct the exact
input those varied rates imply straight from activities_results.csv itself, so this test
is independent of what activities.csv currently contains.
"""

from pathlib import Path

import pandas as pd
import pytest

from pmm4rpaai.ranking.engine import rank_for_goal

FIXTURES = Path(__file__).parent / "fixtures"
TARGET_PCT = 20


@pytest.fixture(scope="module")
def golden():
    return pd.read_csv(FIXTURES / "activities_results.csv")


@pytest.fixture(scope="module")
def activities(golden):
    return golden[["activity", "total_duration", "total_cost", "automation_rate"]].to_dict(orient="records")


def _golden_lookup(golden, column):
    return golden.set_index("activity")[
        [f"rank_{column}", f"potential_savings_{column}", f"cumulative_savings_{column}", f"is_candidate_{column}"]
    ]


@pytest.mark.parametrize("column", ["total_duration", "total_cost"])
def test_rank_for_goal_matches_golden_output(activities, golden, column):
    result = rank_for_goal(activities, column, TARGET_PCT)
    expected = _golden_lookup(golden, column)

    for row in result["ranked"]:
        exp = expected.loc[row["activity"]]
        assert row["rank"] == exp[f"rank_{column}"]
        assert row["reducible"] == pytest.approx(exp[f"potential_savings_{column}"])
        assert row["cumulative_reducible"] == pytest.approx(exp[f"cumulative_savings_{column}"])
        assert row["is_candidate"] == exp[f"is_candidate_{column}"]
