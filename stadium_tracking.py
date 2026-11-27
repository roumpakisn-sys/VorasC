"""Attendance, cleaning tasks and match-day summaries for the stadium."""
from collections import Counter, defaultdict
from datetime import date, timedelta
import re
import unicodedata

import config
import placement_hours


STADIUM_WORDS = frozenset({"ΓΗΠΕΔΟ", "ΑΡΗΣ", "ΑΓΩΝΑΣ"})
COMPETITIONS = ("Πρωτάθλημα", "Κύπελλο")
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


def stadium_bars(groups, selected_day):
    """Offer active, staffed yellow bars whose title refers to the stadium or a match."""
    bars = []
    for group in groups.values():
        if group["Date"] != selected_day or group["is_cancelled"] or not group["HasAssignedEmployee"]:
            continue
        if not is_yellow_bar(group):
            continue
        title = _normalized_label(f"{group['Project']} {group.get('ProjectDisplay') or ''}")
        if STADIUM_WORDS.intersection(re.findall(r"[^\W_]+", title)):
            bars.append(group)

    return sorted(bars, key=lambda group: (
        "ΑΡΗΣ ΓΗΠΕΔΟ" not in _normalized_label(group["Project"]),
        group["StartTime"], group["EndTime"], group["Project"],
    ))


def worked_minutes(arrival, departure, break_minutes):
    start = arrival.hour * 60 + arrival.minute
    end = departure.hour * 60 + departure.minute
    duration = (end - start) % 1440
    if not duration:
        raise ValueError("Η προσέλευση και η αποχώρηση πρέπει να διαφέρουν.")
    if not 0 <= break_minutes <= duration:
        raise ValueError("Το διάλειμμα πρέπει να χωράει μέσα στη βάρδια.")
    return duration - break_minutes


def attendance_payload(assignment, employee_name, clock_in, clock_out, pause, area, notes, previous):
    minutes = worked_minutes(clock_in, clock_out, pause)
    return {
        "expected": {**assignment, "date": assignment["date"].isoformat()},
        "assignment_notes": placement_hours.combine_notes(assignment.get("notes"), minutes / 60),
        "expected_attendance_at": previous.get("updated_at"),
        "employee_name": employee_name,
        "arrival": clock_in.strftime("%H:%M"),
        "departure": clock_out.strftime("%H:%M"),
        "break_minutes": pause,
        "area": area.strip(),
        "notes": notes.strip(),
    }


def attendance_key(row):
    return row["assignment_id"], row["project_id"], row["employee_id"], str(row["work_date"])


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

