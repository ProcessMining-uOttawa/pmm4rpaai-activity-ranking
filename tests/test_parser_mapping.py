"""Column mapping, the duration column and the cost options of the event-log parser."""

import io

import pytest

from pmm4rpaai.eventlog.parser import guess_mapping, parse_eventlog


def _csv(text: str) -> io.StringIO:
    return io.StringIO(text)


def test_explicit_mapping_overrides_header_names():
    csv_text = "id,what,from,to\n7,Register,2024-01-01T00:00:00,2024-01-01T00:05:00\n"
    mapping = {"case_id": "id", "activity": "what", "start_time": "from", "end_time": "to"}
    df, _warnings = parse_eventlog(_csv(csv_text), mapping)
    assert list(df["case_id"]) == ["7"]
    assert list(df["duration"]) == [5.0]


def test_mapping_to_unknown_column_raises():
    csv_text = "case_id,activity,start_time,end_time\n1,Register,2024-01-01T00:00:00,2024-01-01T00:01:00\n"
    mapping = {"case_id": "nope", "activity": "activity", "start_time": "start_time", "end_time": "end_time"}
    with pytest.raises(ValueError, match="not in the file"):
        parse_eventlog(_csv(csv_text), mapping)


def test_guess_prefers_exact_names_then_patterns():
    columns = ["Case ID", "Activity", "Start time", "End time", "Resource", "Hourly rate"]
    guess = guess_mapping(columns)
    assert guess["case_id"] == "Case ID"
    assert guess["activity"] == "Activity"
    assert guess["start_time"] == "Start time"
    assert guess["end_time"] == "End time"
    assert guess["rate"] == "Hourly rate"
    assert guess["cost"] is None and guess["duration"] is None


def test_guess_does_not_use_one_column_twice():
    guess = guess_mapping(["case", "event", "timestamp"])
    assert guess["start_time"] == "timestamp"
    assert guess["end_time"] is None


def test_duration_column_used_when_there_is_no_end_time():
    csv_text = "case_id,activity,duration\n1,Register,12\n1,Check,3.5\n"
    df, _warnings = parse_eventlog(_csv(csv_text))
    assert list(df["duration"]) == [12.0, 3.5]


def test_no_way_to_measure_time_raises():
    csv_text = "case_id,activity,timestamp\n1,Register,2024-01-01T00:00:00\n"
    with pytest.raises(ValueError, match="duration column"):
        parse_eventlog(_csv(csv_text))


def test_negative_duration_rows_are_skipped_with_warning():
    csv_text = (
        "case_id,activity,start_time,end_time\n"
        "1,Register,2024-01-01T00:00:00,2024-01-01T00:01:00\n"
        "2,Register,2024-01-01T00:05:00,2024-01-01T00:01:00\n"
    )
    df, warnings = parse_eventlog(_csv(csv_text))
    assert len(df) == 1
    assert any("before the start" in w for w in warnings)


def test_cost_from_hourly_rate_column_with_default_for_gaps():
    csv_text = "case_id,activity,duration,hourly rate\n1,Register,60,40\n1,Check,30,\n"
    df, _warnings = parse_eventlog(_csv(csv_text), default_rate=20)
    assert list(df["cost"]) == [40.0, 10.0]


def test_cost_from_default_rate_alone():
    csv_text = "case_id,activity,duration\n1,Register,90\n"
    df, _warnings = parse_eventlog(_csv(csv_text), default_rate=30)
    assert list(df["cost"]) == [45.0]


def test_cost_column_wins_and_rate_fills_missing_cost():
    csv_text = "case_id,activity,duration,cost,rate\n1,Register,60,99,40\n1,Check,60,,40\n"
    df, _warnings = parse_eventlog(_csv(csv_text))
    assert list(df["cost"]) == [99.0, 40.0]
