"""STAFF.PRO - persistent work availability (separate from official leave).

Rules:
  scope weekday (0=Monday ... 6=Sunday) or date (rule_date)
  kind unavailable, only_available, preferred
  start_time/end_time both null => whole calendar day.
The evaluator is pure and works for overnight shifts.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any


TABLE = "employee_availability_rules"


def as_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def mins(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (datetime, time)):
        return value.hour * 60 + value.minute
    try:
        hour, minute = [int(x) for x in str(value)[:5].split(":")]
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return 60 * hour + minute
    except (ValueError, TypeError):
        pass
    return None


def matches(rule: dict, day: date, employee_id: str) -> bool:
    if str(rule.get("employee_id")) != str(employee_id):
        return False
    if rule.get("is_active") is False:
        return False
    if rule.get("scope") == "date":
        return as_day(rule.get("rule_date")) == day
    return rule.get("scope") == "weekday" and str(rule.get("weekday")) == str(day.weekday())


def rule_window(rule: dict) -> tuple[int, int] | None:
    a = mins(rule.get("start_time"))
    b = mins(rule.get("end_time"))
    if a is None and b is None:
        return (0, 1440)
    if a is None or b is None or a >= b:
        return None
    return a, b


def covered(start: int, end: int, windows: list[tuple[int, int]]) -> bool:
    """Does a union of allowed windows fully cover [start, end)?"""
    boundary = start
    for a, b in sorted(windows):
        if a <= boundary < b:
            boundary = max(boundary, b)
            if boundary >= end:
                return True
        elif a > boundary:
            break
    return boundary >= end


def assess_rules(employee_id: str, shift: dict, rules: list[dict] | None):
    """Return (eligible, human-readable reason, small preference bonus)."""
    if not rules:
        return True, "", 0
    day = as_day(shift.get("date"))
    s = mins(shift.get("startTime"))
    e = mins(shift.get("endTime"))
    if day is None or s is None or e is None or s == e:
        return False, "Μη έγκυρη ημερομηνία ή ώρα βάρδιας", 0
    start = datetime.combine(day, time.min) + timedelta(minutes=s)
    end = datetime.combine(day, time.min) + timedelta(minutes=e)
    if end < start:
        end += timedelta(days=1)
    cursor = start
    pref = False
    while cursor < end:
        boundary = datetime.combine(cursor.date() + timedelta(days=1), time.min)
        finish = min(end, boundary)
        first_min = cursor.hour * 60 + cursor.minute
        last_min = 1440 if finish == boundary else finish.hour * 60 + finish.minute
        applicable = [
            r for r in rules if isinstance(r, dict) and matches(r, cursor.date(), employee_id)
        ]
        possible = []
        for rule in applicable:
            w = rule_window(rule)
            kind = rule.get("kind")
            if w is None:
                return False, "Μη έγκυρος κανόνας διαθεσιμότητας", 0
            if kind == "unavailable" and w[0] < last_min and w[1] > first_min:
                return False, "Δηλωμένη μη διαθεσιμότητα", 0
            if kind == "only_available":
                possible.append(w)
            if kind == "preferred" and w[0] <= first_min and w[1] >= last_min:
                pref = True
        if possible and not covered(first_min, last_min, possible):
            return False, "Εκτός δηλωμένων διαθέσιμων ωρών", 0
        cursor = finish
    return True, "", 8 if pref else 0


def fetch_rules(supabase):
    """Return (rules, error). Never silently treat a failed DB fetch as empty."""
    if supabase is None:
        return [], "Δεν υπάρχει σύνδεση Supabase."
    try:
        response = supabase.table(TABLE).select("*").execute()
        return list(response.data or []), ""
    except Exception as exc:
        return [], f"Ο πίνακας διαθεσιμότητας δεν είναι διαθέσιμος ({exc})."


def save_rule(supabase, record: dict):
    return supabase.table(TABLE).insert(record).execute()


def delete_rule(supabase, record_id: str):
    return supabase.table(TABLE).delete().eq("id", record_id).execute()
