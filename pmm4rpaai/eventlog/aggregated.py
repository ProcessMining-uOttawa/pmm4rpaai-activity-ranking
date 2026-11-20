"""Parse an already-aggregated per-activity CSV (e.g. activity_data.csv-style tables)
directly into the same shape produced by `mining.aggregate_activities`, bypassing
raw event-log mining entirely.
"""

from __future__ import annotations

from typing import IO

import pandas as pd

ACTIVITY_ALIASES = ["activity", "value", "activity_name", "name"]

METRIC_ALIASES: dict[str, list[str]] = {
    "total_duration": ["total_duration", "total duration", "duration"],
    "total_cost": ["total_cost", "total cost", "cost"],
    "rework_duration": ["rework_duration", "total rework hours", "rework_hours", "rework hours", "total_rework_hours"],
    "rework_cost": ["rework_cost", "total rework cost", "rework cost", "total_rework_cost"],
    "cases": ["cases"],
    "activity_instances": ["activity_instances", "instances"],
}

DURATION_COLUMNS = ("total_duration", "rework_duration")

# Factor converting a duration in the given unit to minutes, the app's single time unit.
TO_MINUTES = {"seconds": 1 / 60, "minutes": 1.0, "hours": 60.0}

METRIC_LABELS = {
    "total_duration": "Processing time",
    "rework_duration": "Rework time",
    "total_cost": "Cost",
}


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    lookup = {c.strip().lower(): c for c in columns}
    for alias in aliases:
        if alias in lookup:
            return lookup[alias]
    return None


def parse_aggregated_activities(
    file: str | IO[bytes] | IO[str],
    duration_unit: str = "hours",
) -> tuple[list[dict], list[str]]:
    """
    Parses a pre-aggregated activity CSV (one row per activity) into the same
    per-activity record shape the event-log mining path produces.

    duration_unit is the unit of the file's duration columns ("seconds", "minutes" or
    "hours"; the lab's activity_data.csv uses hours); they are converted to minutes.

    automation_rate is always set to 1.0 (v1 placeholder) regardless of any
    automation_rate column present in the source file.
    """
    if duration_unit not in TO_MINUTES:
        raise ValueError(f"Unknown duration unit '{duration_unit}'. Choose from: {list(TO_MINUTES)}")

    warnings: list[str] = []
    raw = pd.read_csv(file, dtype=str)
    raw.columns = [c.strip() for c in raw.columns]

    activity_col = _find_column(list(raw.columns), ACTIVITY_ALIASES)
    if activity_col is None:
        raise ValueError(
            f"Aggregated activity file is missing an activity name column "
            f"(expected one of {ACTIVITY_ALIASES}). Found columns: {list(raw.columns)}"
        )

    result = pd.DataFrame()
    result["activity"] = raw[activity_col].str.strip()

    for canonical, aliases in METRIC_ALIASES.items():
        col = _find_column(list(raw.columns), aliases)
        if col is None:
            result[canonical] = 0.0
            if canonical in METRIC_LABELS:
                warnings.append(
                    f"No '{canonical}' column found — the {METRIC_LABELS[canonical]} goal will be unavailable (assumed 0)."
                )
        else:
            result[canonical] = pd.to_numeric(raw[col], errors="coerce").fillna(0.0)

    for col in DURATION_COLUMNS:
        result[col] = result[col] * TO_MINUTES[duration_unit]

    result["automation_rate"] = 1.0

    return result.to_dict(orient="records"), warnings
