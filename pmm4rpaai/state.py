"""In-memory session storage for the single-user local demo.

No database, no locking, no TTL: the Flask dev server is single-threaded and
state only needs to survive for the lifetime of one demo session.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionState:
    activities: list[dict]
    last_ranking: dict | None = None
    last_assessment: dict | None = None
    # metric column -> user-given process total (replaces the activity sum when ranking)
    metric_totals: dict[str, float] = field(default_factory=dict)


SESSIONS: dict[str, SessionState] = {}
