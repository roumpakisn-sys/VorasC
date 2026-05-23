from datetime import datetime, timedelta


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
    return emp["name"] if emp else "Άγνωστος"


def get_project_info(proj_id, proj_map):
    return proj_map.get(proj_id)


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
    Lightweight dashboard path:
    Επιστρέφει τα wk_groups + export_data που χρησιμοποιεί το dashboard.
    Δεν χτίζει Plotly figure για να μειωθεί ο χρόνος rerun.
    Διατηρείται η ίδια υπογραφή για πλήρη συμβατότητα.
    """
    export_data = []
    wk_groups = {}

    # Precompute short names για σταθερή/γρήγορη μορφοποίηση.
    emp_short_names = {}
    for emp in employees:
        eid = emp["id"]
        full_name = emp["name"]
        parts = full_name.split()
        emp_short_names[eid] = f"{parts[-1]} {parts[0][0]}." if len(parts) > 1 else full_name

    day_names_gr = [
        "Δευτέρα",
        "Τρίτη",
        "Τετάρτη",
        "Πέμπτη",
        "Παρασκευή",
        "Σάββατο",
        "Κυριακή",
    ]

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_assigns = assignments_by_date.get(curr_date, [])

        if not day_assigns:
            continue

        emp_day_assigns = {}
        for da in day_assigns:
            eid = da.get("employeeId")
            if eid:
                if eid not in emp_day_assigns:
                    emp_day_assigns[eid] = []
                emp_day_assigns[eid].append(da)

        groups = {}
        for a in day_assigns:
            proj = get_project_info(a["projectId"], proj_map)
            c_hex = a.get("colorHex", proj["color"] if proj else "#999999")
            c_name = a.get("colorName", "Προεπιλογή")
            notes = a.get("notes", "")
            is_canc = a.get("is_cancelled", False)
            c_reason = a.get("cancel_reason", "")
            arrival_time = a.get("arrivalTime", "")
            if arrival_time:
                arrival_time = arrival_time[:5]

            key = (
                f"{curr_date}_{a['projectId']}_{a['startTime']}_{a['endTime']}_"
                f"{c_hex}_{is_canc}_{c_reason}_{arrival_time}"
            )

            if key not in groups:
                legend_val = f"{proj['name']} ({c_name})" if proj else "Άγνωστο"
                groups[key] = {
                    "Key": key,
                    "ProjectId": a["projectId"],
                    "Date": curr_date,
                    "Project": proj["name"] if proj else "Άγνωστο",
                    "ArrivalTime": arrival_time,
                    "StartTime": str(a["startTime"])[:5],
                    "EndTime": str(a["endTime"])[:5],
                    "Start": datetime.combine(
                        datetime(1970, 1, 1),
                        datetime.strptime(str(a["startTime"])[:5], "%H:%M").time(),
                    ),
                    "End": datetime.combine(
                        datetime(1970, 1, 1),
                        datetime.strptime(str(a["endTime"])[:5], "%H:%M").time(),
                    ),
                    "Employees": [],
                    "EmployeeIds": [],
                    "AssignmentIds": [],
                    "ColorHex": c_hex,
                    "ColorName": c_name,
                    "Notes_List": [],
                    "is_cancelled": is_canc,
                    "cancel_reason": c_reason,
                    "LegendGroup": legend_val,
                    "RecurringId": a.get("recurring_id"),
                }

            if notes and notes not in groups[key]["Notes_List"]:
                groups[key]["Notes_List"].append(notes)

            if not a.get("employeeId"):
                formatted_name = "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ"
            else:
                formatted_name = emp_short_names.get(
                    a["employeeId"],
                    get_employee_name(a["employeeId"], emp_map),
                )

            prev_assigns = []
            my_eid = a.get("employeeId")
            if my_eid in emp_day_assigns:
                t_a_start_str = str(a["startTime"])[:5]
                t_a_end_str = str(a["endTime"])[:5]
                for pa in emp_day_assigns[my_eid]:
                    if pa.get("id") != a["id"]:
                        t_pa_start_str = str(pa["startTime"])[:5]
                        t_pa_end_str = str(pa["endTime"])[:5]
                        pa_proj = get_project_info(pa["projectId"], proj_map)
                        a_proj = get_project_info(a["projectId"], proj_map)
                        pa_name = pa_proj["name"].strip().lower() if pa_proj else "1"
                        a_name = a_proj["name"].strip().lower() if a_proj else "2"

                        if (
                            (pa_name != a_name)
                            and (t_pa_start_str <= t_a_start_str)
                            and (t_pa_end_str > t_a_start_str)
                            and (t_a_end_str > t_pa_end_str)
                        ):
                            prev_assigns.append(pa)

            if prev_assigns:
                prev_assigns.sort(key=lambda x: str(x["endTime"])[:5], reverse=True)
                prev_proj = get_project_info(prev_assigns[0]["projectId"], proj_map)
                if prev_proj:
                    formatted_name = f"[ΜΕΤΑ ΑΠΟ '{prev_proj['name']}' ▶ {formatted_name}]"

            groups[key]["Employees"].append(formatted_name)
            groups[key]["EmployeeIds"].append(a["employeeId"])
            groups[key]["AssignmentIds"].append(a["id"])

        for g in groups.values():
            g["Notes"] = " | ".join(g["Notes_List"])

        wk_groups.update(groups)

        # Διατηρούμε την ίδια σειρά όπως πριν για export_data.
        non_blue_groups = [g for g in groups.values() if g["ColorHex"].lower() != "#4a86e8"]
        blue_groups = [g for g in groups.values() if g["ColorHex"].lower() == "#4a86e8"]

        non_blue_lanes = []
        group_row_mapping = []

        for g in sorted(non_blue_groups, key=lambda x: x["Start"]):
            placed = False
            for lane_idx, lane_end in enumerate(non_blue_lanes):
                if g["Start"] >= lane_end:
                    row_idx = lane_idx
                    non_blue_lanes[lane_idx] = g["End"]
                    placed = True
                    break
            if not placed:
                non_blue_lanes.append(g["End"])
                row_idx = len(non_blue_lanes) - 1
            group_row_mapping.append((g, row_idx))

        num_non_blue_lanes = len(non_blue_lanes)
        blue_lanes = []

        for g in sorted(blue_groups, key=lambda x: x["Start"]):
            placed = False
            for lane_idx, lane_end in enumerate(blue_lanes):
                if g["Start"] >= lane_end:
                    row_idx = lane_idx
                    blue_lanes[lane_idx] = g["End"]
                    placed = True
                    break
            if not placed:
                blue_lanes.append(g["End"])
                row_idx = len(blue_lanes) - 1
            group_row_mapping.append((g, row_idx + num_non_blue_lanes))

        for g, _row_idx in group_row_mapping:
            export_data.append(
                {
                    "Ημερομηνία": curr_date.strftime("%d/%m/%Y"),
                    "Ημέρα": day_names_gr[i],
                    "Έργο": g["Project"],
                    "Προσωπικό": ", ".join(g["Employees"]),
                    "Ώρα Προσέλευσης": g["ArrivalTime"] if g["ArrivalTime"] else "-",
                    "Ώρα Έναρξης": g["StartTime"],
                    "Ώρα Λήξης": g["EndTime"],
                    "Παρατηρήσεις": g["Notes"],
                    "Ακυρωμένο": "ΝΑΙ" if g["is_cancelled"] else "ΟΧΙ",
                    "Λόγος Ακύρωσης": g["cancel_reason"],
                }
            )

    # Το fig δεν χρειάζεται στο dashboard path.
    return None, wk_groups, export_data
