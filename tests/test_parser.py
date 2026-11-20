import io

import pytest

from pmm4rpaai.eventlog.parser import parse_eventlog


def _csv(text: str) -> io.StringIO:
    return io.StringIO(text)


@pytest.mark.parametrize("case_id_header", ["case_id", "case id", "CaseId", "Case"])
def test_case_id_alias_resolution(case_id_header):
    csv_text = f"{case_id_header},activity,start_time,end_time\n1,Register,2024-01-01T00:00:00,2024-01-01T00:01:00\n"
    df, warnings = parse_eventlog(_csv(csv_text))
    assert list(df["case_id"]) == ["1"]
    assert list(df["activity"]) == ["Register"]


def test_missing_required_column_raises():
    csv_text = "start_time,end_time\n2024-01-01T00:00:00,2024-01-01T00:01:00\n"
    with pytest.raises(ValueError, match="missing required column"):
        parse_eventlog(_csv(csv_text))


def test_missing_cost_column_warns_instead_of_crashing():
    csv_text = "case_id,activity,start_time,end_time\n1,Register,2024-01-01T00:00:00,2024-01-01T00:01:00\n"
    df, warnings = parse_eventlog(_csv(csv_text))
    assert df["cost"].isna().all()
    assert any("cost" in w.lower() for w in warnings)


def test_strips_whitespace_from_activity_names():
    csv_text = "case_id,activity,start_time,end_time\n1, Register ,2024-01-01T00:00:00,2024-01-01T00:01:00\n"
    df, warnings = parse_eventlog(_csv(csv_text))
    assert df["activity"].iloc[0] == "Register"


def test_unparseable_timestamp_row_dropped_with_warning():
    csv_text = (
        "case_id,activity,start_time,end_time\n"
        "1,Register,2024-01-01T00:00:00,2024-01-01T00:01:00\n"
        "2,Register,not-a-timestamp,2024-01-01T00:01:00\n"
    )
    df, warnings = parse_eventlog(_csv(csv_text))
    assert len(df) == 1
    assert any("unparseable" in w.lower() for w in warnings)
