"""Pure, testable matching rules for STAFF.PRO smart replacements.

No database credentials, Streamlit state, or external network dependencies.
No geographic or region criterion is used for eligibility or ranking.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any


def as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip().split("T")[0][:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                pass
    return None


def clock_minutes(value: Any) -> int | None:
    if isinstance(value, (datetime, time)):
        return value.hour * 60 + value.minute
    raw = str(value or "").strip()[:5]
    try:
        hh, mm = (int(v) for v in raw.split(":"))
    except (ValueError, TypeError):
        return None
    if hh not in range(24) or mm not in range(60):
        return None
    return hh * 60 + mm


def interval(assignment: dict) -> tuple[datetime, datetime] | None:
    day = as_date(assignment.get("date"))
    start_m = clock_minutes(assignment.get("startTime"))
    end_m = clock_minutes(assignment.get("endTime"))
    if day is None or start_m is None or end_m is None:
        return None
    start_dt = datetime.combine(day, time.min) + timedelta(minutes=start_m)
    end_dt = datetime.combine(day, time.min) + timedelta(minutes=end_m)
    if end_dt == start_dt:
        return None  # Zero-length/ambiguous 24-hour shift is not a safe match.
    if end_dt < start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def minutes_worked(a: dict) -> int:
    times = interval(a)
    return round((times[1] - times[0]).total_seconds() / 60) if times else 0


def is_cancelled(a: dict) -> bool:
    return a.get("is_cancelled") is True or str(a.get("is_cancelled", "")).strip().lower() == "true"


def empty_shifts(assignments: list[dict], selected_date: date) -> list[dict]:
    """One vacancy per actual assignment, not one per visual merged Gantt bar."""
    return sorted(
        (
            a for a in assignments
            if isinstance(a, dict)
            and as_date(a.get("date")) == selected_date
            and not str(a.get("employeeId") or "").strip()
            and not is_cancelled(a)
            and a.get("id")
            and interval(a) is not None
        ),
        key=lambda a: (clock_minutes(a.get("startTime")) or 0, str(a.get("projectId") or ""), str(a.get("id"))),
    )


def leave_dates_hit(emp_id: str, shift: dict, leaves: list[dict]) -> bool:
    span = interval(shift)
    if not span:
        return True  # Unknown date/time is never silently treated as available.
    start_dt, end_dt = span
    last_day = (end_dt - timedelta(microseconds=1)).date()
    for leave in leaves:
        if str(leave.get("employeeId")) != str(emp_id):
            continue
        left = as_date(leave.get("startDate"))
        right = as_date(leave.get("endDate"))
        if left and right and left <= last_day and right >= start_dt.date():
            return True
    return False


def candidate_assessment(
    employee: dict,
    vacant: dict,
    all_assignments: list[dict],
    all_leaves: list[dict],
    *,
    travel_buffer_minutes: int = 0,
    maximum_day_hours: float = 10,
    today: date | None = None,
) -> dict:
    """Assess availability and transparent, advisory score.

    Strictly excludes overlapping shifts, sick/regular leave, inactive personnel,
    too-small handover gaps and overload. Never silently authorizes overlap.
    Historical experience uses earlier, non-cancelled real assignments only.
    """
    today = today or date.today()
    eid = str(employee.get("id") or "")
    name = str(employee.get("name") or "Άγνωστος")
    result = {
        "employee_id": eid,
        "name": name,
        "eligible": False,
        "reason": "",
        "score": 0,
        "day_hours": 0.0,
        "projected_hours": 0.0,
        "experience_days": 0,
        "existing_shifts": "—",
    }
    if not eid or employee.get("status", "Ενεργός") != "Ενεργός":
        result["reason"] = "Μη ενεργός εργαζόμενος"
        return result
    shift_span = interval(vacant)
    if not shift_span:
        result["reason"] = "Μη έγκυρο ωράριο κενής βάρδιας"
        return result
    if leave_dates_hit(eid, vacant, all_leaves):
        result["reason"] = "Άδεια την ημέρα της βάρδιας"
        return result

    target_day = as_date(vacant.get("date"))
    buffer_gap = max(0, int(travel_buffer_minutes))
    own_shifts = [a for a in all_assignments
                  if isinstance(a, dict) and str(a.get("employeeId") or "") == eid
                  and not is_cancelled(a) and a.get("id") != vacant.get("id")]

    target_s, target_e = shift_span
    nearby = []
    busy = []
    for a in own_shifts:
        span = interval(a)
        if span is None:
            # Missing invalid times on a shift on the same day: cannot verify safety.
            if as_date(a.get("date")) == target_day:
                result["reason"] = "Άλλη βάρδια με μη έγκυρο ωράριο"
                return result
            continue
        other_s, other_e = span
        if other_s < target_e and other_e > target_s:
            result["reason"] = f"Επικάλυψη με {other_s:%H:%M}–{other_e:%H:%M}"
            return result
        gap_before = (target_s - other_e).total_seconds() / 60
        gap_after = (other_s - target_e).total_seconds() / 60
        if 0 <= gap_before < buffer_gap or 0 <= gap_after < buffer_gap:
            result["reason"] = f"Κενό κάτω από {buffer_gap} λεπτά μεταξύ βαρδιών"
            return result
        if as_date(a.get("date")) == target_day:
            nearby.append(a)
            busy.append((other_s, other_e))

    day_mins = sum(minutes_worked(a) for a in nearby)
    new_mins = minutes_worked(vacant)
    projected = (day_mins + new_mins) / 60
    result["day_hours"] = round(day_mins / 60, 2)
    result["projected_hours"] = round(projected, 2)
    result["existing_shifts"] = ", ".join(
        f"{s:%H:%M}–{e:%H:%M}" for s, e in sorted(busy)
    ) or "—"
    if projected > maximum_day_hours + 1e-9:
        result["reason"] = f"Πάνω από {maximum_day_hours:g} ώρες την ημέρα"
        return result

    # Only completed or earlier-day placements count as experience;
    # scheduled future work is not evidence that work was done.
    cutoff = min(target_day, today + timedelta(days=1))
    history = {
        as_date(a.get("date")) for a in own_shifts
        if a.get("projectId") == vacant.get("projectId")
        and as_date(a.get("date")) is not None
        and as_date(a.get("date")) < cutoff
    }
    result["experience_days"] = len(history)
    result["score"] = round(60 + min(40, len(history) * 8) - day_mins / 60 * 3)
    result["eligible"] = True
    result["reason"] = (
        f"{result['experience_days']} προηγ. ημέρες στο έργο · "
        f"{result['day_hours']:g} ήδη προγρ. ώρες"
    )
    return result


def rank_candidates(
    vacant: dict,
    employees: list[dict],
    assignments: list[dict],
    leaves: list[dict],
    *,
    only_external: bool = False,
    travel_buffer_minutes: int = 0,
    maximum_day_hours: float = 10,
    today: date | None = None,
) -> tuple[list[dict], list[dict]]:
    eligible = []
    blocked = []
    for emp in employees:
        if not isinstance(emp, dict):
            continue
        if only_external and not emp.get("is_external_crew", False):
            continue
        if emp.get("status", "Ενεργός") != "Ενεργός":
            continue
        report = candidate_assessment(
            emp, vacant, assignments, leaves,
            travel_buffer_minutes=travel_buffer_minutes,
            maximum_day_hours=maximum_day_hours,
            today=today,
        )
        (eligible if report["eligible"] else blocked).append(report)
    eligible.sort(key=lambda x: (-x["score"], x["projected_hours"], x["name"].casefold()))
    blocked.sort(key=lambda x: x["name"].casefold())
    return eligible, blocked
