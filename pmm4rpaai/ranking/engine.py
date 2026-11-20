"""Goal-based automation-candidate ranking.

Generalizes the lab's validated per-metric scripts (total_time_reduction.py,
total_rework_duration.py, total_rework_cost.py) into one parameterized engine.

Single goal (`rank_for_goal`):
  total_metric_value = sum(activity[metric_column]), or a user-given process total
  (e.g. total processing time, which can exceed the activity sum because of waiting)
  target_reduction   = total_metric_value * (target_pct / 100)
  reducible(activity) = activity[metric_column] * activity["automation_rate"]
  rank activities by reducible, descending
  select the minimal top-ranked prefix whose cumulative reducible >= target_reduction

Several goals (`rank_combined`): one ranking and one shortlist for all goals together.
  share(activity, goal) = reducible(activity) / total_metric_value(goal)
  score(activity)       = mean of its shares over the goals (every goal weighs the same)
  rank activities by score, descending
  shortlist from the top until every goal's cumulative share reaches its target
With one goal this is the single-goal algorithm.
"""

from __future__ import annotations

GOALS: dict[str, dict[str, str]] = {
    "reduce_total_duration": {"label": "Processing time", "column": "total_duration"},
    "reduce_total_cost": {"label": "Cost", "column": "total_cost"},
    "reduce_rework_duration": {"label": "Rework time", "column": "rework_duration"},
}

# Tolerance for "cumulative share has reached the target", absorbing float rounding.
_EPSILON = 1e-12


def rank_for_goal(
    activities: list[dict],
    metric_column: str,
    target_pct: float,
    total_override: float | None = None,
) -> dict:
    """
    Ranks activities against one goal metric.

    total_override, when given, replaces the summed activity metric as the process
    total the target % is taken from.

    Returns a dict with:
      ranked             - activities sorted by reducible value (desc), each annotated with
                            rank, reducible, cumulative_reducible, is_candidate
      total_metric_value, target_reduction, achieved_reduction, goal_met
    """
    total_metric_value = (
        total_override if total_override is not None else sum(a[metric_column] for a in activities)
    )
    target_reduction = total_metric_value * (target_pct / 100)

    ranked = sorted(
        activities,
        key=lambda a: a[metric_column] * a["automation_rate"],
        reverse=True,
    )

    cumulative = 0.0
    goal_met = False
    annotated = []
    for rank, a in enumerate(ranked, start=1):
        reducible = a[metric_column] * a["automation_rate"]
        is_candidate = not goal_met
        if is_candidate:
            cumulative += reducible
            if cumulative >= target_reduction:
                goal_met = True

        annotated.append({
            **a,
            "rank": rank,
            "reducible": reducible,
            "cumulative_reducible": round(cumulative, 2),
            "is_candidate": is_candidate,
        })

    return {
        "ranked": annotated,
        "total_metric_value": total_metric_value,
        "target_reduction": target_reduction,
        "achieved_reduction": cumulative,
        "goal_met": goal_met,
    }


def rank_combined(
    activities: list[dict],
    goals: list[dict],
    total_overrides: dict[str, float] | None = None,
) -> dict:
    """
    Ranks activities against all goals at once, with equal weight per goal.

    goals is a list of {"category": key of GOALS, "target_pct": number}.
    total_overrides maps a metric column to a user-given process total that replaces the
    activity sum for that column.

    Returns a dict with:
      ranked    - activities with a score above 0, best first, each annotated with rank,
                  score, shortlisted and, per goal column, share_<col> / cumulative_<col>
                  (fractions of that goal's total)
      unranked  - activities contributing nothing to any goal (score 0), not shortlisted
      goals     - per goal key: label, column, total, target_pct, target_reduction,
                  achieved_share, achieved_reduction (both for the shortlist), goal_met
      shortlist - names of the shortlisted activities, in rank order
    """
    total_overrides = total_overrides or {}
    columns = [GOALS[g["category"]]["column"] for g in goals]
    totals = {
        col: total_overrides[col] if col in total_overrides else sum(a.get(col, 0) or 0 for a in activities)
        for col in columns
    }
    targets = {GOALS[g["category"]]["column"]: g["target_pct"] / 100 for g in goals}

    scored = []
    for a in activities:
        shares = {
            col: ((a.get(col, 0) or 0) * a["automation_rate"] / totals[col]) if totals[col] > 0 else 0.0
            for col in columns
        }
        scored.append((a, shares, sum(shares.values()) / len(columns)))

    scored.sort(key=lambda item: (item[2], item[0].get("total_duration", 0) or 0), reverse=True)

    cumulative = {col: 0.0 for col in columns}
    shortlist_share = {col: 0.0 for col in columns}
    reached = {col: False for col in columns}
    ranked, unranked, shortlist = [], [], []
    for a, shares, score in scored:
        if score <= 0:
            unranked.append({**a, "score": 0.0, "shortlisted": False})
            continue
        shortlisted = not all(reached.values())
        row = {**a, "rank": len(ranked) + 1, "score": score, "shortlisted": shortlisted}
        for col in columns:
            cumulative[col] += shares[col]
            row[f"share_{col}"] = shares[col]
            row[f"cumulative_{col}"] = cumulative[col]
            if shortlisted:
                shortlist_share[col] = cumulative[col]
            if not reached[col] and cumulative[col] >= targets[col] - _EPSILON:
                reached[col] = True
        if shortlisted:
            shortlist.append(a["activity"])
        ranked.append(row)

    goal_summary = {}
    for g in goals:
        col = GOALS[g["category"]]["column"]
        goal_summary[g["category"]] = {
            "label": GOALS[g["category"]]["label"],
            "column": col,
            "total": totals[col],
            "total_is_entered": col in total_overrides,
            "target_pct": g["target_pct"],
            "target_reduction": totals[col] * targets[col],
            "achieved_share": shortlist_share[col],
            "achieved_reduction": shortlist_share[col] * totals[col],
            "goal_met": reached[col],
        }

    return {"ranked": ranked, "unranked": unranked, "goals": goal_summary, "shortlist": shortlist}
