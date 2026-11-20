from pathlib import Path

import pandas as pd
import pytest

from pmm4rpaai.eventlog.mining import aggregate_activities
from pmm4rpaai.eventlog.parser import parse_eventlog

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def mined():
    df, _warnings = parse_eventlog(FIXTURES / "RepairExample-eventlog.csv")
    return aggregate_activities(df)


@pytest.fixture(scope="module")
def oracle():
    # The lab's own independently-computed activity_data.csv — a real external oracle,
    # not derived from our code. total_duration there is in hours; ours is in minutes.
    df = pd.read_csv(FIXTURES / "activity_data.csv")
    return df.set_index("value")


def test_case_and_instance_counts_match_oracle(mined, oracle):
    by_activity = mined.set_index("activity")

    assert by_activity.loc["Register", "cases"] == oracle.loc["Register", "cases"] == 1104
    assert by_activity.loc["Register", "activity_instances"] == oracle.loc["Register", "activity_instances"] == 1104

    assert by_activity.loc["Test Repair", "cases"] == oracle.loc["Test Repair", "cases"] == 1102
    assert by_activity.loc["Test Repair", "activity_instances"] == oracle.loc["Test Repair", "activity_instances"] == 1508


def test_total_duration_matches_oracle_within_rounding(mined, oracle):
    by_activity = mined.set_index("activity")

    for activity in ["Test Repair", "Analyze Defect", "Repair (Complex)"]:
        ours_hours = by_activity.loc[activity, "total_duration"] / 60
        oracle_hours = oracle.loc[activity, "total_duration"]
        assert ours_hours == pytest.approx(oracle_hours, abs=1.0)

    # Instant system events (start_time == end_time) contribute zero duration.
    for activity in ["Register", "Inform User", "Archive Repair"]:
        assert by_activity.loc[activity, "total_duration"] == 0


def test_rework_detected_for_case_10(mined):
    df, _warnings = parse_eventlog(FIXTURES / "RepairExample-eventlog.csv")
    case_10 = df[df["case_id"] == "10"]

    assert (case_10["activity"] == "Repair (Simple)").sum() == 2
    assert (case_10["activity"] == "Test Repair").sum() == 2

    by_activity = mined.set_index("activity")
    assert by_activity.loc["Repair (Simple)", "rework_instances"] > 0
    assert by_activity.loc["Test Repair", "rework_instances"] > 0


def test_automation_rate_defaults_to_one(mined):
    assert (mined["automation_rate"] == 1.0).all()
