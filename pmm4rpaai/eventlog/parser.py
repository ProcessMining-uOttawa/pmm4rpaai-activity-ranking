"""Parse a raw business-process event log CSV into a normalized DataFrame.

Real event logs vary in header naming, so each field is either mapped to a column by
the caller or guessed: first by exact (case-insensitive) alias, then by a looser
pattern on the header text.
"""

from __future__ import annotations

import re
from typing import IO

import pandas as pd

COLUMN_ALIASES: dict[str, list[str]] = {
    "case_id": ["case_id", "case id", "caseid", "case"],
    "start_time": ["start_time", "start time", "start", "start timestamp", "starttimestamp"],
    "end_time": ["end_time", "end time", "end", "end timestamp", "endtimestamp", "complete_time", "complete timestamp"],
    "activity": ["activity", "task", "activity name", "concept:name"],
    "duration": ["duration", "duration_minutes", "duration (min)", "duration (minutes)"],
    "cost": ["cost", "total_cost", "activity_cost"],
    "rate": ["hourly rate", "hourly_rate", "rate", "cost rate", "hourly cost rate"],
    "resource": ["resource", "performer", "org:resource"],
    "role": ["role"],
}

# Looser header patterns, tried in order when no exact alias matches.
COLUMN_PATTERNS: dict[str, list[str]] = {
    "case_id": [r"case", r"trace"],
    "activity": [r"activity", r"concept:name", r"task", r"event"],
    "start_time": [r"start", r"begin", r"^time", r"timestamp"],
    "end_time": [r"end", r"complete", r"finish"],
    "duration": [r"duration"],
    "rate": [r"rate"],
    "cost": [r"cost"],
    "resource": [r"resource"],
    "role": [r"role"],
}

FIELDS = list(COLUMN_ALIASES)
REQUIRED_COLUMNS = ["case_id", "activity"]
TIME_COLUMNS = ["start_time", "end_time"]
# Fields the user maps in the UI (resource and role are carried along but not mapped).
MAPPABLE_FIELDS = ["case_id", "activity", "start_time", "end_time", "duration", "cost", "rate"]


def find_column(columns: list[str], canonical: str) -> str | None:
    """Return the first column in `columns` matching `canonical` (case-insensitive alias lookup)."""
    lookup = {c.strip().lower(): c for c in columns}
    for alias in COLUMN_ALIASES[canonical]:
        if alias in lookup:
            return lookup[alias]
    return None


def guess_mapping(columns: list[str]) -> dict[str, str | None]:
    """Best guess of which column holds each field; a column is used for one field only."""
    guess: dict[str, str | None] = {f: find_column(columns, f) for f in FIELDS}
    taken = {c for c in guess.values() if c is not None}
    for field in FIELDS:
        if guess[field] is not None:
            continue
        for pattern in COLUMN_PATTERNS[field]:
            match = next((c for c in columns if c not in taken and re.search(pattern, c, re.IGNORECASE)), None)
            if match is not None:
                guess[field] = match
                taken.add(match)
                break
    return guess


def read_columns(file: str | IO[bytes] | IO[str]) -> tuple[list[str], int]:
    """Column names and row count of a CSV, for the mapping step."""
    raw = pd.read_csv(file, dtype=str)
    return list(raw.columns), len(raw)


def _resolve(columns: list[str], mapping: dict[str, str | None] | None) -> dict[str, str | None]:
    if mapping is None:
        return guess_mapping(columns)
    resolved: dict[str, str | None] = {}
    for field in FIELDS:
        column = mapping.get(field) or None
        if column is not None and column not in columns:
            raise ValueError(f"Column '{column}' (mapped to {field}) is not in the file. Found columns: {columns}")
        resolved[field] = column
    return resolved


def parse_eventlog(
    file: str | IO[bytes] | IO[str],
    mapping: dict[str, str | None] | None = None,
    default_rate: float | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse a raw event log CSV into a normalized DataFrame with columns:
    case_id, start_time, end_time, activity, resource, role, cost, duration
    (duration in minutes; resource/role/cost are all-NaN if unavailable).

    mapping names the source column of each field ({field: column or None}); when it is
    omitted the columns are guessed. Duration is end time minus start time, or the
    mapped duration column (minutes) when there is no end time.

    Cost per row is the cost column where it has a value; otherwise processing time
    multiplied by the hourly rate (the rate column, falling back to default_rate).

    Returns (dataframe, warnings).
    """
    warnings: list[str] = []
    raw = pd.read_csv(file, dtype=str)
    resolved = _resolve(list(raw.columns), mapping)

    missing_required = [c for c in REQUIRED_COLUMNS if resolved[c] is None]
    if missing_required:
        raise ValueError(
            f"Event log is missing required column(s): {', '.join(missing_required)}. "
            f"Found columns: {list(raw.columns)}"
        )

    has_span = resolved["start_time"] is not None and resolved["end_time"] is not None
    if not has_span and resolved["duration"] is None:
        raise ValueError(
            "Choose a start time and an end time, or a duration column, so execution times can be measured."
        )

    df = pd.DataFrame()
    for field in ("case_id", "start_time", "end_time", "activity", "resource", "role"):
        src = resolved[field]
        df[field] = raw[src] if src is not None else pd.NA

    # Real-world logs (including our own lab's sample) can have stray leading/trailing
    # whitespace in string fields from unquoted commas in the source CSV — strip it so
    # grouping/aggregation doesn't silently split one activity into two.
    for col in ("case_id", "activity", "resource", "role"):
        if resolved[col] is not None:
            df[col] = df[col].str.strip()
    for col in ("case_id", "activity"):
        df[col] = df[col].replace("", pd.NA)

    for col in TIME_COLUMNS:
        if resolved[col] is not None:
            parsed = pd.to_datetime(df[col], errors="coerce")
            bad = int(parsed.isna().sum() - df[col].isna().sum())
            if bad > 0 and has_span:
                warnings.append(f"Dropped {bad} row(s) with an unparseable '{col}' timestamp.")
            df[col] = parsed

    if has_span:
        df["duration"] = (df["end_time"] - df["start_time"]).dt.total_seconds() / 60
    else:
        df["duration"] = pd.to_numeric(raw[resolved["duration"]], errors="coerce")

    cost = pd.to_numeric(raw[resolved["cost"]], errors="coerce") if resolved["cost"] is not None else None
    rate = None
    if resolved["rate"] is not None:
        rate = pd.to_numeric(raw[resolved["rate"]], errors="coerce")
        if default_rate is not None:
            rate = rate.fillna(default_rate)
    elif default_rate is not None:
        rate = pd.Series(float(default_rate), index=raw.index)
    from_rate = df["duration"] / 60 * rate if rate is not None else None

    if cost is not None and from_rate is not None:
        df["cost"] = cost.fillna(from_rate)
    elif cost is not None:
        df["cost"] = cost
    elif from_rate is not None:
        df["cost"] = from_rate
        warnings.append("Cost is calculated as processing time × hourly rate.")
    else:
        df["cost"] = pd.NA
        warnings.append("No 'cost' column found — cost-based analysis will be unavailable.")

    before = len(df)
    df = df.dropna(subset=["case_id", "activity", "duration"])
    if has_span:
        df = df.dropna(subset=["start_time", "end_time"])
    dropped = before - len(df)
    if dropped:
        warnings.append(f"Skipped {dropped} row(s) because the case, activity or time couldn't be read.")

    negative = int((df["duration"] < 0).sum())
    if negative:
        df = df[df["duration"] >= 0]
        warnings.append(f"Skipped {negative} row(s) whose end time is before the start time.")

    if cost is not None and len(df):
        missing_cost = int(df["cost"].isna().sum())
        if missing_cost:
            pct = round(100 * missing_cost / len(df), 1)
            warnings.append(
                f"{pct}% of Cost values are missing ({missing_cost} of {len(df)} rows) — "
                "cost-based goals may be unreliable."
            )

    return df.reset_index(drop=True), warnings
