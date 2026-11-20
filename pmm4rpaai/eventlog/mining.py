"""Aggregate a normalized event log into per-activity metrics.

Input: the DataFrame produced by `pmm4rpaai.eventlog.parser.parse_eventlog`
(columns: case_id, start_time, end_time, activity, resource, role, cost, duration).
"""

from __future__ import annotations

import pandas as pd


def aggregate_activities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns one row per activity with columns:
    activity, cases, activity_instances, min_duration, median_duration,
    average_duration, max_duration, total_duration, total_cost,
    rework_instances, rework_duration, rework_cost, automation_rate.

    Durations are in minutes. An activity's 2nd+ occurrence within the same
    case counts as "rework" for that case.
    """
    # Without start times (duration-only logs) the file's row order is the execution order.
    sort_keys = ["case_id"] if df["start_time"].isna().all() else ["case_id", "start_time"]
    work = df.sort_values(sort_keys, kind="stable").copy()
    if "duration" not in work.columns:
        work["duration"] = (work["end_time"] - work["start_time"]).dt.total_seconds() / 60
    work["cost"] = pd.to_numeric(work["cost"], errors="coerce")
    work["occurrence_in_case"] = work.groupby(["case_id", "activity"]).cumcount()
    work["is_rework"] = work["occurrence_in_case"] > 0

    main = work.groupby("activity").agg(
        cases=("case_id", "nunique"),
        activity_instances=("activity", "size"),
        min_duration=("duration", "min"),
        median_duration=("duration", "median"),
        average_duration=("duration", "mean"),
        max_duration=("duration", "max"),
        total_duration=("duration", "sum"),
        total_cost=("cost", "sum"),
    ).reset_index()

    rework = (
        work[work["is_rework"]]
        .groupby("activity")
        .agg(
            rework_instances=("activity", "size"),
            rework_duration=("duration", "sum"),
            rework_cost=("cost", "sum"),
        )
        .reset_index()
    )

    result = main.merge(rework, on="activity", how="left")
    for col in ("rework_instances", "rework_duration", "rework_cost"):
        result[col] = result[col].fillna(0)

    result["automation_rate"] = 1.0

    return result
