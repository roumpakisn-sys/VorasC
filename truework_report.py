"""Monthly coverage for the yellow assignments shown in the Gantt."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import config
import periodic_visits
import placement_confirmation
import placement_details
from gantt_helpers import assignment_absence_names, assignment_color
from replacement_engine import as_date, interval, is_cancelled, leave_dates_hit


COVERED = "Με προσωπικό"
PARTIAL = "Μερικώς ακάλυπτη"
UNSTAFFED = "Ακάλυπτη"
CANCELLED = "Ακυρωμένη"
PENDING = placement_confirmation.PENDING_LABEL


@dataclass
class Shift:
    project_id: str
    day: date
    start: str
    end: str
    arrival: str
    address: str
    cancelled: bool
    pending: bool
    cancel_reason: str
    workers: set[str] = field(default_factory=set)
    absences: set[str] = field(default_factory=set)
    replacements: set[str] = field(default_factory=set)
    vacancies: int = 0

    @property
    def status(self):
        if self.cancelled:
            return CANCELLED
        if self.pending:
            return PENDING
        if not self.workers:
            return UNSTAFFED
        if self.vacancies:
            return PARTIAL
        return COVERED


def month_assignments(assignments_by_date, projects, first, end):
    yellow = config.BASIC_COLORS["Κίτρινο"].lstrip("#").casefold()
    return [
        row for day, rows in assignments_by_date.items() if first <= day < end
        for row in rows
        if assignment_color(row, projects.get(row.get("projectId"))).strip().lstrip("#").casefold() == yellow
    ]


def _slot_key(assignment_id, project_id, day):
    return str(assignment_id), str(project_id), day


def month_shifts(assignments, employees, leaves, attendance=()):
    """Aggregate slots by shift while keeping every unfilled position visible."""
    leaves_by_employee = defaultdict(list)
    for leave in leaves:
        leaves_by_employee[str(leave.get("employeeId") or "")].append(leave)

    attendance_by_slot = defaultdict(dict)
    for row in attendance:
        key = _slot_key(row["assignment_id"], row["project_id"], as_date(row["work_date"]))
        attendance_by_slot[key][str(row["employee_id"])] = row

    shifts = {}
    for row in assignments:
        day = as_date(row.get("date"))
        project_id = str(row.get("projectId") or "")
        start, end, arrival = (str(row.get(key) or "")[:5] for key in ("startTime", "endTime", "arrivalTime"))
        notes = row.get("notes") or ""
        _, details = placement_details.split_notes(notes)
        _, visit = periodic_visits.split_notes(notes)
        cancelled = is_cancelled(row)
        pending = not cancelled and placement_confirmation.is_pending(row)
        cancel_reason = (row.get("cancel_reason") or "") if cancelled else ""
        address = details["address"]
        key = (project_id, day, start, end, arrival, address, bool(row.get("is_general")),
               visit["visit_id"] if visit else None, cancelled, pending, cancel_reason)
        if key not in shifts:
            shifts[key] = Shift(project_id, day, start, end, arrival, address, cancelled, pending, cancel_reason)
        shift = shifts[key]
        absence_names = assignment_absence_names(notes)
        records = attendance_by_slot.get(_slot_key(row.get("id"), project_id, day), {})
        employee_id = str(row.get("employeeId") or "").strip()
        for recorded_id, record in records.items():
            if not record.get("did_work", True):
                absence_names.add(record.get("employee_name") or employees.get(recorded_id) or "Άγνωστος εργαζόμενος")
        shift.absences.update(absence_names)
        if cancelled:
            continue
        if not employee_id:
            shift.vacancies += 1
            continue

        record = records.get(employee_id)
        name = employees.get(employee_id) or (record or {}).get("employee_name") or "Άγνωστος εργαζόμενος"
        employee_leaves = leaves_by_employee.get(employee_id)
        on_leave = (record is None and employee_leaves and interval(row) is not None
                    and leave_dates_hit(employee_id, row, employee_leaves))
        if on_leave or (record is not None and not record.get("did_work", True)):
            shift.absences.add((record or {}).get("employee_name") or name)
            shift.vacancies += 1
        else:
            shift.workers.add(name)
            if any(absent.casefold() != name.casefold() for absent in absence_names):
                shift.replacements.add(name)

    return sorted(shifts.values(), key=lambda s: (s.day, s.start, s.end, s.project_id, s.address))
