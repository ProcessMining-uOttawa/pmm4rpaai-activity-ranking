from pathlib import Path

import pytest

from app import create_app
from pmm4rpaai.eventlog.aggregated import parse_aggregated_activities

FIXTURES = Path(__file__).parent / "fixtures"


def _test_repair(unit=None):
    kwargs = {} if unit is None else {"duration_unit": unit}
    activities, _warnings = parse_aggregated_activities(FIXTURES / "activity_data.csv", **kwargs)
    return next(a for a in activities if a["activity"] == "Test Repair")


def test_durations_default_to_hours_and_are_converted_to_minutes():
    # activity_data.csv: Test Repair total_duration = 188.23 hours.
    assert _test_repair()["total_duration"] == pytest.approx(188.23 * 60)


@pytest.mark.parametrize("unit, factor", [("hours", 60), ("minutes", 1), ("seconds", 1 / 60)])
def test_durations_converted_from_given_unit(unit, factor):
    assert _test_repair(unit)["total_duration"] == pytest.approx(188.23 * factor)


def test_unknown_unit_rejected():
    with pytest.raises(ValueError, match="Unknown duration unit"):
        parse_aggregated_activities(FIXTURES / "activity_data.csv", duration_unit="days")


def test_upload_endpoint_uses_unit_field():
    client = create_app().test_client()
    with open(FIXTURES / "activity_data.csv", "rb") as f:
        res = client.post(
            "/api/upload-activities",
            data={"file": (f, "activity_data.csv"), "duration_unit": "minutes"},
            content_type="multipart/form-data",
        )

    assert res.status_code == 200
    test_repair = next(a for a in res.get_json()["activities"] if a["activity"] == "Test Repair")
    assert test_repair["total_duration"] == pytest.approx(188.23)
