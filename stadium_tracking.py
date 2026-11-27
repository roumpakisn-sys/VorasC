"""Attendance, cleaning tasks and match-day summaries for the stadium."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5
import re
import unicodedata

import config
import placement_hours


STADIUM_WORDS = frozenset({"ΓΗΠΕΔΟ", "ΑΡΗΣ", "ΑΓΩΝΑΣ"})
PRE_MATCH_PROJECT = "Πριν τον αγώνα"
COMPETITIONS = ("Πρωτάθλημα", "Κύπελλο")
MATCH_NO_SHIFT = "Χωρίς βάρδια"
MATCH_NO_STAFF = "Χωρίς προσωπικό"
MATCH_PENDING = "Εκκρεμούν παρουσίες"
MATCH_COMPLETE = "Ολοκληρώθηκε"
STATUSES = ("Εκκρεμεί", "Σε εξέλιξη", "Ολοκληρώθηκε")
CATEGORIES = (
    "Δάπεδα", "WC", "Υαλοπίνακες", "Γραφεία / επιφάνειες", "Κερκίδες",
    "Κουζίνα", "Απορρίμματα", "Απολύμανση", "Αναλώσιμα", "Εξωτερικοί χώροι",
    "Γενικός καθαρισμός", "Άλλη εργασία",
)


def _normalized_label(value):
    letters = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(c for c in letters if not unicodedata.combining(c)).upper().split())


def is_yellow_bar(group):
    """Compare the rendered Gantt color with its existing yellow palette entry."""
    color = (group.get("ColorHex") or "").strip().lstrip("#").casefold()
    return color == config.BASIC_COLORS["Κίτρινο"].lstrip("#").casefold()


def stadium_bars(groups, selected_day, *, include_unstaffed=False):
    """Find active yellow bars whose title refers to the stadium or a match."""
    bars = []
    for group in groups.values():
        if group["Date"] != selected_day or group["is_cancelled"]:
            continue
        if not include_unstaffed and not group["HasAssignedEmployee"]:
            continue
        if not is_yellow_bar(group):
            continue
        title = _normalized_label(f"{group['Project']} {group.get('ProjectDisplay') or ''}")
        if (STADIUM_WORDS.intersection(re.findall(r"[^\W_]+", title))
                or _normalized_label(group["Project"]) == _normalized_label(PRE_MATCH_PROJECT)):
            bars.append(group)

    return sorted(bars, key=lambda group: (
        "ΑΡΗΣ ΓΗΠΕΔΟ" not in _normalized_label(group["Project"]),
        group["StartTime"], group["EndTime"], group["Project"],
    ))


def match_shift_ids(match_day, generation):
    """Concurrent creation for the same day uses the same pair of IDs."""
    return [str(uuid5(NAMESPACE_URL, f"vorasc:stadium:shift:{match_day}:{generation}:{kind}"))
            for kind in ("match", "pre-match")]


def build_match_shifts(match_day, kickoff, opponent, projects):
    """Build two unstaffed yellow placements and any missing catalog entries."""
    opponent = " ".join((opponent or "").split())
    if not opponent:
        raise ValueError("Συμπλήρωσε την αντίπαλη ομάδα.")
    try:
        start_time = datetime.strptime(kickoff or "", "%H:%M").time()
    except ValueError as exc:
        raise ValueError("Συμπλήρωσε την ώρα έναρξης του αγώνα.") from exc

    match_time = datetime.combine(match_day, start_time)
    start = match_time - timedelta(hours=2)
    end = match_time + timedelta(hours=2)
    if start.date() != match_day:
        raise ValueError("Η βάρδια του αγώνα θα ξεκινούσε την προηγούμενη ημερομηνία.")

    specs = (
        (f"ΑΡΗΣ – {opponent}", start.strftime("%H:%M"), end.strftime("%H:%M")),
        (PRE_MATCH_PROJECT, "08:00", "13:00"),
    )
    color = config.BASIC_COLORS["Κίτρινο"]
    shifts, new_projects = [], []
    project_ids = {str(project["id"]) for project in projects}
    for title, start_time, end_time in specs:
        label = _normalized_label(title)
        existing = next((project for project in projects if _normalized_label(project["name"]) == label), None)
        if existing:
            project_id = existing["id"]
            new_projects.append(None)
        else:
            project_id = str(uuid5(NAMESPACE_URL, f"vorasc:stadium:project:{label}"))
            while project_id in project_ids:
                project_id = str(uuid5(NAMESPACE_URL, project_id))
            new_projects.append({"id": project_id, "name": title, "color": color})
        shifts.append({
            "employeeId": "", "projectId": project_id, "date": match_day,
            "arrivalTime": "", "startTime": start_time, "endTime": end_time,
            "colorName": "Κίτρινο", "colorHex": color, "notes": "",
            "is_cancelled": False, "cancel_reason": "", "recurring_id": None, "is_general": False,
        })
    return shifts, new_projects


def worked_minutes(arrival, departure, break_minutes):
    start = arrival.hour * 60 + arrival.minute
    end = departure.hour * 60 + departure.minute
    duration = (end - start) % 1440
    if not duration:
        raise ValueError("Η προσέλευση και η αποχώρηση πρέπει να διαφέρουν.")
    if not 0 <= break_minutes <= duration:
        raise ValueError("Το διάλειμμα πρέπει να χωράει μέσα στη βάρδια.")
    return duration - break_minutes


def attendance_time_defaults(assignment, previous):
    if previous and previous.get("did_work", True):
        start, end = previous["arrival"], previous["departure"]
    else:
        start, end = assignment["startTime"], assignment["endTime"]
    return tuple(datetime.strptime(str(value)[:5], "%H:%M").time() for value in (start, end))


def attendance_payload(assignment, employee_name, clock_in, clock_out, pause, area, notes, previous, *, did_work=True):
    minutes = worked_minutes(clock_in, clock_out, pause) if did_work else 0
    return {
        "expected": {**assignment, "date": assignment["date"].isoformat()},
        "assignment_notes": placement_hours.combine_notes(assignment.get("notes"), minutes / 60),
        "expected_attendance_at": previous.get("updated_at"),
        "employee_name": employee_name,
        "did_work": did_work,
        "arrival": clock_in.strftime("%H:%M") if did_work else None,
        "departure": clock_out.strftime("%H:%M") if did_work else None,
        "break_minutes": pause if did_work else 0,
        "area": area.strip(),
        "notes": notes.strip(),
    }


def attendance_key(row):
    return row["assignment_id"], row["project_id"], row["employee_id"], str(row["work_date"])


def assignment_attendance_key(assignment):
    return assignment["id"], assignment["projectId"], assignment["employeeId"], assignment["date"].isoformat()


def match_readiness(bars, scheduled, recorded):
    """Return the match-day status and its first bar that needs attention."""
    if not bars:
        return MATCH_NO_SHIFT, None

    for bar in bars:
        if not bar["HasAssignedEmployee"]:
            return MATCH_NO_STAFF, bar

    expected = {
        row["id"]: assignment_attendance_key(row) for row in scheduled
        if row.get("employeeId") and not row.get("is_cancelled")
    }
    for bar in bars:
        if any(expected[key] not in recorded for key in bar["AssignmentIds"] if key in expected):
            return MATCH_PENDING, bar
    return MATCH_COMPLETE, bars[0]


def period_rows(client, table, order_fields, date_field, start, end):
    """Read the whole selected month even when attendance exceeds the API page size."""
    rows = []
    while True:
        query = client.table(table).select("*").gte(date_field, start.isoformat()).lt(date_field, end.isoformat())
        for field in order_fields:
            query = query.order(field)
        page = query.range(len(rows), len(rows) + 999).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows


def month_bounds(day):
    start = day.replace(day=1)
    return start, (start + timedelta(days=32)).replace(day=1)


def summary(attendance, tasks, matches, selected_day):
    start, end = month_bounds(selected_day)
    by_day = defaultdict(dict)
    by_worker = defaultdict(dict)
    names = {}
    for row in attendance:
        day = date.fromisoformat(str(row["work_date"]))
        minutes = row["worked_minutes"]
        if minutes <= 0 or not start <= day < end:
            continue
        employee = row["employee_id"]
        by_day[day][employee] = by_day[day].get(employee, 0) + minutes
        by_worker[employee][day] = by_day[day][employee]
        names[employee] = row["employee_name"]

    completed = Counter(
        date.fromisoformat(str(row["work_date"])) for row in tasks
        if row["status"] == STATUSES[-1]
    )
    match_days = {date.fromisoformat(str(row["match_date"])) for row in matches}
    daily = [
        (start + timedelta(days=offset)) for offset in range((end - start).days)
    ]
    return {
        "daily": [
            (day, day in match_days, len(by_day[day]), sum(by_day[day].values()), completed[day])
            for day in daily
        ],
        "workers": sorted(
            (names[employee], len(workdays), sum(workdays.values()))
            for employee, workdays in by_worker.items()
        ),
        "selected": sorted((names[worker], minutes) for worker, minutes in by_day[selected_day].items()),
    }

