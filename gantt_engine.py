import pandas as pd
from datetime import datetime, date, timedelta
import textwrap


def get_local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()


def get_employee_name(emp_id, emp_map):
    if not emp_id:
        return "Χωρίς Προσωπικό"
    emp = emp_map.get(emp_id)
    return emp.get("name", "Άγνωστος") if emp else "Άγνωστος"


def get_project_info(proj_id, proj_map):
    return proj_map.get(proj_id)


def _to_time_dt(time_value):
    return datetime.combine(
        datetime(1970, 1, 1),
        datetime.strptime(str(time_value)[:5], "%H:%M").time(),
    )


def generate_gantt_chart(
    start_of_week,
    zoom_factor,
    presentation_mode,
    data_version,
    assignments_by_date,
    leaves,
    employees,
    projects,
    emp_map,
    proj_map,
):
    """
    Δημιουργεί τα δεδομένα του Gantt.

    Η σελίδα χρησιμοποιεί κυρίως τα wk_groups και export_data.
    Το πρώτο επιστρεφόμενο αντικείμενο κρατιέται για συμβατότητα με την παλιά Plotly έκδοση.
    """
    export_data = []
    wk_groups = {}

    emp_short_names = {}
    for emp in employees or []:
        if not isinstance(emp, dict) or "id" not in emp:
            continue
        eid = emp["id"]
        full_name = emp.get("name", "Άγνωστος")
        parts = full_name.split()
        emp_short_names[eid] = f"{parts[-1]} {parts[0][0]}." if len(parts) > 1 else full_name

    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_assigns = assignments_by_date.get(curr_date, []) if assignments_by_date else []
        if not day_assigns:
            continue

        emp_day_assigns = {}
        for da in day_assigns:
            if not isinstance(da, dict):
                continue
            eid = da.get("employeeId")
            if eid:
                emp_day_assigns.setdefault(eid, []).append(da)

        groups = {}
        for a in day_assigns:
            if not isinstance(a, dict):
                continue

            project_id = a.get("projectId")
            proj = get_project_info(project_id, proj_map)
            project_name = proj.get("name", "Άγνωστο") if proj else "Άγνωστο"

            c_hex = a.get("colorHex") or (proj.get("color") if proj else "#999999") or "#999999"
            c_name = a.get("colorName", "Προεπιλογή")
            notes = a.get("notes", "") or ""
            is_canc = bool(a.get("is_cancelled", False))
            c_reason = a.get("cancel_reason", "") or ""
            is_general = bool(a.get("is_general", False))

            arrival_time = a.get("arrivalTime", "") or ""
            if arrival_time:
                arrival_time = str(arrival_time)[:5]

            start_time = str(a.get("startTime", "09:00"))[:5]
            end_time = str(a.get("endTime", "17:00"))[:5]

            key = (
                f"{curr_date}_{project_id}_{start_time}_{end_time}_{c_hex}_"
                f"{is_canc}_{c_reason}_{arrival_time}_{is_general}"
            )

            if key not in groups:
                legend_val = f"{project_name} ({c_name})"
                groups[key] = {
                    "Key": key,
                    "ProjectId": project_id,
                    "Date": curr_date,
                    "Project": project_name,
                    "ArrivalTime": arrival_time,
                    "StartTime": start_time,
                    "EndTime": end_time,
                    "Start": _to_time_dt(start_time),
                    "End": _to_time_dt(end_time),
                    "Employees": [],
                    "EmployeeIds": [],
                    "AssignmentIds": [],
                    "ColorHex": c_hex,
                    "ColorName": c_name,
                    "Notes_List": [],
                    "Notes": "",
                    "is_cancelled": is_canc,
                    "cancel_reason": c_reason,
                    "LegendGroup": legend_val,
                    "RecurringId": a.get("recurring_id"),
                    "IsGeneral": is_general,
                }

            if notes and notes not in groups[key]["Notes_List"]:
                groups[key]["Notes_List"].append(notes)

            employee_id = a.get("employeeId")
            if not employee_id:
                formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
            else:
                formatted_name = emp_short_names.get(employee_id, get_employee_name(employee_id, emp_map))

                # Διατηρεί τη λογική εμφάνισης "μετά από" για επιτρεπόμενη επικάλυψη.
                prev_assigns = []
                for pa in emp_day_assigns.get(employee_id, []):
                    if pa.get("id") == a.get("id"):
                        continue
                    pa_start = str(pa.get("startTime", ""))[:5]
                    pa_end = str(pa.get("endTime", ""))[:5]
                    pa_proj = get_project_info(pa.get("projectId"), proj_map)
                    a_proj = get_project_info(project_id, proj_map)
                    pa_name = pa_proj.get("name", "1").strip().lower() if pa_proj else "1"
                    a_name = a_proj.get("name", "2").strip().lower() if a_proj else "2"

                    if (
                        pa_name != a_name
                        and pa_start <= start_time
                        and pa_end > start_time
                        and end_time > pa_end
                    ):
                        prev_assigns.append(pa)

                if prev_assigns:
                    prev_assigns.sort(key=lambda x: str(x.get("endTime", ""))[:5], reverse=True)
                    prev_proj = get_project_info(prev_assigns[0].get("projectId"), proj_map)
                    if prev_proj:
                        formatted_name = f"[ΜΕΤΑ ΑΠΟ '{prev_proj.get('name', 'Άγνωστο')}' ▶ {formatted_name}]"

            groups[key]["Employees"].append(formatted_name)
            groups[key]["EmployeeIds"].append(employee_id)
            groups[key]["AssignmentIds"].append(a.get("id"))

        for g in groups.values():
            g["Notes"] = " | ".join(g["Notes_List"])
            export_data.append({
                "Ημερομηνία": curr_date.strftime("%d/%m/%Y"),
                "Ημέρα": day_names_gr[i],
                "Έργο": g["Project"],
                "Προσωπικό": ", ".join(g["Employees"]),
                "Ώρα Προσέλευσης": g["ArrivalTime"] if g["ArrivalTime"] else "-",
                "Ώρα Έναρξης": g["StartTime"],
                "Ώρα Λήξης": g["EndTime"],
                "Παρατηρήσεις": g["Notes"],
                "Γενικός": "ΝΑΙ" if g.get("IsGeneral", False) else "ΟΧΙ",
                "Ακυρωμένο": "ΝΑΙ" if g["is_cancelled"] else "ΟΧΙ",
                "Λόγος Ακύρωσης": g["cancel_reason"],
            })

        wk_groups.update(groups)

    # Συμβατότητα με την παλιά επιστροφή fig, wk_groups, export_data.
    return None, wk_groups, export_data
