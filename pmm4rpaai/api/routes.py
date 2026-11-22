from __future__ import annotations

import csv
import io
import json
import uuid

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from pmm4rpaai.eventlog.parser import MAPPABLE_FIELDS, guess_mapping, parse_eventlog, read_columns
from pmm4rpaai.eventlog.mining import aggregate_activities
from pmm4rpaai.eventlog.aggregated import parse_aggregated_activities
from pmm4rpaai.ranking.engine import GOALS, rank_combined
from pmm4rpaai.state import SESSIONS, SessionState

bp = Blueprint("api", __name__, url_prefix="/api")


def _store_activities(activities: list[dict], warnings: list[str], metric_totals: dict[str, float] | None = None):
    upload_id = str(uuid.uuid4())
    SESSIONS[upload_id] = SessionState(activities=activities, metric_totals=metric_totals or {})
    return jsonify({
        "upload_id": upload_id,
        "activities": activities,
        "warnings": warnings,
        "metric_totals": metric_totals or {},
    })


def _positive_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


@bp.post("/preview")
def preview():
    """Column names of an event log and a guess of which column holds each field."""
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify({"error": "No file provided."}), 400

    try:
        columns, rows = read_columns(file.stream)
    except (ValueError, UnicodeDecodeError) as exc:
        return jsonify({"error": f"Couldn't read that file as CSV: {exc}"}), 400
    if not columns or rows == 0:
        return jsonify({"error": "That file has no rows to read."}), 400

    guess = guess_mapping(columns)
    return jsonify({"columns": columns, "rows": rows, "mapping": {f: guess[f] for f in MAPPABLE_FIELDS}})


@bp.post("/upload")
def upload():
    """
    Mines an event log. Optional form fields: `mapping`, a JSON object naming the column
    of each field ({field: column or ""}; guessed when omitted), and `default_rate`, the
    hourly cost rate for rows without a cost or rate value.
    """
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify({"error": "No file provided."}), 400

    secure_filename(file.filename)  # validated, not persisted to disk

    mapping = None
    if request.form.get("mapping"):
        try:
            mapping = json.loads(request.form["mapping"])
        except json.JSONDecodeError:
            mapping = None
        if not isinstance(mapping, dict):
            return jsonify({"error": "mapping must be a JSON object."}), 400

    default_rate = None
    if request.form.get("default_rate", "") != "":
        try:
            default_rate = float(request.form["default_rate"])
        except ValueError:
            default_rate = -1.0
        if not 0 <= default_rate < float("inf"):
            return jsonify({"error": "Default hourly rate must be a number of 0 or more."}), 400

    try:
        df, warnings = parse_eventlog(file.stream, mapping, default_rate)
    except (ValueError, UnicodeDecodeError) as exc:
        return jsonify({"error": str(exc)}), 400

    if df.empty:
        return jsonify({"error": "No usable rows were found with this column mapping."}), 400

    activities_df = aggregate_activities(df)
    response = _store_activities(activities_df.to_dict(orient="records"), warnings)
    payload = response.get_json()
    payload["cases"] = int(df["case_id"].nunique())
    payload["rows"] = int(len(df))
    return jsonify(payload)


@bp.post("/upload-activities")
def upload_activities():
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify({"error": "No file provided."}), 400

    secure_filename(file.filename)  # validated, not persisted to disk

    try:
        activities, warnings = parse_aggregated_activities(
            file.stream, request.form.get("duration_unit", "hours")
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not activities:
        return jsonify({"error": "Aggregated activity file has no usable rows."}), 400

    return _store_activities(activities, warnings)


@bp.post("/manual-activities")
def manual_activities():
    """Takes a typed-in process: its total processing time and each activity's time, in minutes."""
    body = request.get_json(silent=True) or {}
    total = body.get("total_processing_time")
    rows = body.get("activities") or []

    if not _positive_number(total):
        return jsonify({"error": "Total processing time must be a positive number."}), 400
    if not rows:
        return jsonify({"error": "Enter at least one activity."}), 400

    activities = []
    seen = set()
    for row in rows:
        name = str(row.get("activity") or "").strip()
        duration = row.get("duration")
        if not name:
            return jsonify({"error": "Every activity needs a name."}), 400
        if name in seen:
            return jsonify({"error": f"Activity '{name}' is listed twice."}), 400
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            return jsonify({"error": f"Time for '{name}' must be a number of 0 or more."}), 400
        # Optional: how many times the activity was performed in the period.
        executions = row.get("executions")
        if executions is None:
            executions = 0
        elif not isinstance(executions, int) or isinstance(executions, bool) or executions < 0:
            return jsonify({"error": f"Executions for '{name}' must be a whole number of 0 or more."}), 400
        seen.add(name)
        activities.append({
            "activity": name,
            "activity_instances": executions,
            "total_duration": float(duration),
            "total_cost": 0.0,
            "rework_duration": 0.0,
            "rework_cost": 0.0,
            "automation_rate": 1.0,
        })

    warnings = []
    activity_sum = sum(a["total_duration"] for a in activities)
    if activity_sum > total:
        warnings.append(
            f"Activity times add up to {activity_sum:g}, more than the total processing time ({total:g})."
        )

    return _store_activities(activities, warnings, {"total_duration": float(total)})


@bp.post("/rank")
def rank():
    body = request.get_json(silent=True) or {}
    upload_id = body.get("upload_id")
    goals = body.get("goals")

    session = SESSIONS.get(upload_id)
    if session is None:
        return jsonify({"error": "Unknown upload_id. Upload an event log first."}), 404

    if not goals:
        return jsonify({"error": "At least one goal is required."}), 400

    seen = set()
    for g in goals:
        category = g.get("category")
        target_pct = g.get("target_pct")

        if category not in GOALS:
            return jsonify({"error": f"Unknown goal category '{category}'. Choose from: {list(GOALS)}"}), 400
        if category in seen:
            return jsonify({"error": f"Goal '{category}' is listed twice."}), 400
        seen.add(category)
        if not _positive_number(target_pct) or target_pct > 100:
            return jsonify({"error": f"target_pct for '{category}' must be above 0 and at most 100."}), 400

    result = rank_combined(session.activities, goals, session.metric_totals)
    session.last_ranking = result
    return jsonify(result)


@bp.get("/export/<upload_id>")
def export(upload_id: str):
    session = SESSIONS.get(upload_id)
    if session is None:
        return jsonify({"error": "Unknown upload_id."}), 404
    if session.last_ranking is None:
        return jsonify({"error": "No ranking has been run yet for this upload."}), 409

    ranking = session.last_ranking
    rows = []
    for a in ranking["ranked"] + ranking["unranked"]:
        row = {
            "rank": a.get("rank", ""),
            "activity": a["activity"],
            "executions": a.get("activity_instances", ""),
            "cases": a.get("cases", ""),
            "total_duration_min": round(a.get("total_duration", 0) or 0, 2),
            "total_cost": round(a.get("total_cost", 0) or 0, 2),
            "rework_duration_min": round(a.get("rework_duration", 0) or 0, 2),
        }
        for goal in ranking["goals"].values():
            col = goal["column"]
            row[f"share_{col}"] = round(a.get(f"share_{col}", 0), 5)
            row[f"cumulative_{col}"] = round(a[f"cumulative_{col}"], 5) if f"cumulative_{col}" in a else ""
        if len(ranking["goals"]) > 1:
            row["combined_score"] = round(a["score"], 5)
        row["shortlisted"] = "yes" if a["shortlisted"] else "no"
        rows.append(row)
    fieldnames = list(rows[0].keys()) if rows else []

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=activity_ranking.csv"},
    )
