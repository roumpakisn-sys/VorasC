import base64
import html as html_utils
from datetime import datetime, timedelta

import streamlit as st

import config
import utils
from availability_rules import fetch_rules, matches, rule_window


def get_local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()


def build_html_gantt(wk_groups, start_of_week, zoom_factor, key_to_safe_id, gantt_height_px,
                     *, focused_key=None, scroll_to_focus=False, staff_drag_token=None, email_menu=False):
    import gantt_email
    import placement_confirmation

    timeline_width_px = int(2400 * zoom_factor)
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    # Ψηλότερες μπάρες + μικρότερα κενά
    BAR_HEIGHT_PX = 44
    LANE_STEP_PX = 46
    ROW_PAD_TOP_PX = 6
    ROW_PAD_BOTTOM_PX = 6
    STACKED_BAR_WIDTH = 54

    emp_short_names = {}
    employee_details_by_id = {}
    external_crews = []
    # Always load real persisted rules; an unavailable table must never be treated as all-available.
    availability_rules, availability_error = fetch_rules(utils.supabase)
    rules_ready = not availability_error
    if not rules_ready:
        st.warning(
            "Δεν είναι δυνατός ο έλεγχος δηλωμένης διαθεσιμότητας: "
            + availability_error
            + " Οι λίστες «ΔΙΑΘΕΣΙΜΟΙ» δεν εμφανίζονται μέχρι να αποκατασταθεί η σύνδεση."
        )
    for emp in st.session_state.employees:
        eid = emp["id"]
        employee_details_by_id[eid] = emp
        full_name = emp["name"]
        parts = full_name.split()
        emp_short_names[eid] = f"{parts[-1]} {parts[0][0]}." if len(parts) > 1 else full_name
        if emp.get("status", "Ενεργός") == "Ενεργός" and emp.get("is_external_crew", False):
            external_crews.append(emp)

    def is_on_leave_fast(eid, check_date):
        for l in st.session_state.leaves:
            if l["employeeId"] == eid and l["startDate"] <= check_date <= l["endDate"]:
                return True
        return False

    def drag_worker(eid, label_html, *, from_list=False, full_name=None):
        if not staff_drag_token:
            return label_html
        origin = " data-staff-origin='availability'" if from_list else ""
        action = "Σύρε για ανάθεση" if from_list else "Σύρε το όνομα στη μπάρα προορισμού"
        title = html_utils.escape(f"{full_name} · {action}" if full_name else action, quote=True)
        return (
            f"<span class='gantt-transfer-worker' draggable='true'{origin} "
            f"data-employee='{html_utils.escape(str(eid), quote=True)}' title='{title}'>"
            f"{label_html}</span>"
        )

    html = ""

    html += (
        "<div id='gantt-master-container' "
        f"data-staff-drag-token='{html_utils.escape(staff_drag_token or '', quote=True)}' "
        f"style='overflow: auto; height: {gantt_height_px}px; min-height: 360px; width: 100%; max-width: 100%; position: relative; border: 4px solid var(--gantt-edge, #1e293b); border-radius: 12px; "
        "background: var(--gantt-surface, #ffffff); user-select: none; cursor: grab; "
        "box-shadow: 0px 12px 35px rgba(0,0,0,0.4); font-family: \"Segoe UI\", Tahoma, Geneva, Verdana, sans-serif;'>"
    )

    if staff_drag_token:
        html += """
        <style>
            #gantt-master-container .gantt-transfer-worker {
                --gantt-context-color: #fda4af;
                pointer-events: auto;
                cursor: grab;
                display: inline-block;
                vertical-align: middle;
                box-sizing: border-box;
                max-width: 100%;
                overflow-wrap: anywhere;
                padding: 1px 5px;
                border-radius: 8px;
                background: #1e293b;
                box-shadow: inset 0 0 0 1px #64748b, 0 1px 2px rgb(15 23 42 / 22%);
                transition: background-color 120ms ease, box-shadow 120ms ease;
            }
            #gantt-master-container .gantt-transfer-worker::before {
                content: "";
                display: inline-block;
                width: 8px;
                height: 12px;
                margin-right: 4px;
                vertical-align: text-bottom;
                background: radial-gradient(circle, #bae6fd 1px, transparent 1.25px) 0 0 / 4px 4px;
            }
            #gantt-master-container .gantt-transfer-worker[data-staff-origin] { color: #f8fafc; }
            #gantt-master-container [data-staff-transfer-bar] .gantt-bar-content {
                display: flex;
                flex-direction: column;
                align-self: stretch;
                min-height: 0;
                gap: 1px;
                padding: 1px 3px;
                -webkit-line-clamp: unset;
            }
            #gantt-master-container .gantt-transfer-project,
            #gantt-master-container .gantt-transfer-schedule {
                flex: 0 0 auto;
                line-height: 11px;
                overflow: hidden;
                white-space: nowrap;
                text-overflow: ellipsis;
            }
            #gantt-master-container .gantt-transfer-roster {
                flex: 1 1 auto;
                min-height: 0;
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                align-content: flex-start;
                gap: 2px;
                overflow-y: auto;
                overscroll-behavior-y: contain;
                pointer-events: auto;
            }
            #gantt-master-container .gantt-transfer-roster::-webkit-scrollbar { width: 4px; }
            #gantt-master-container .gantt-transfer-roster::-webkit-scrollbar-thumb {
                background: #334155;
                border-radius: 3px;
            }
            #gantt-master-container .gantt-transfer-roster::-webkit-scrollbar-track {
                background: rgba(255, 255, 255, 0.55);
            }
            @supports not selector(::-webkit-scrollbar) {
                #gantt-master-container .gantt-transfer-roster { scrollbar-width: thin; }
            }
            #gantt-master-container [data-gantt-stacked][data-staff-transfer-bar] .gantt-bar-content {
                padding: 0 1px;
                gap: 0;
            }
            #gantt-master-container [data-gantt-stacked] .gantt-transfer-project {
                font-size: 9px;
                line-height: 10px;
            }
            #gantt-master-container [data-gantt-stacked] .gantt-transfer-schedule { display: none; }
            #gantt-master-container [data-gantt-stacked] .gantt-transfer-roster .gantt-transfer-worker {
                padding: 0 1px;
                font-size: 9px;
                line-height: 10px;
                text-overflow: clip;
            }
            #gantt-master-container [data-gantt-stacked] .gantt-transfer-roster .gantt-transfer-worker::before {
                display: none;
            }
            #gantt-master-container .gantt-transfer-roster:focus-visible {
                outline: 1px solid #fff;
                outline-offset: -1px;
            }
            #gantt-master-container .gantt-transfer-roster .gantt-transfer-worker {
                color: #f8fafc;
                padding: 0 4px;
                overflow: hidden;
                white-space: nowrap;
                text-overflow: ellipsis;
                line-height: 12px;
            }
            #gantt-master-container .gantt-transfer-roster .gantt-transfer-worker::before {
                height: 9px;
                vertical-align: baseline;
            }
            #gantt-master-container[data-staff-drag-token]:not([data-staff-drag-token=""]) .mygantt-bar:hover {
                transform: none;
            }
            #gantt-master-container .gantt-transfer-worker:hover,
            #gantt-master-container .gantt-transfer-worker.gantt-drag-origin {
                background: #164e63;
                box-shadow: inset 0 0 0 1px #7dd3fc, 0 1px 2px rgb(15 23 42 / 22%);
            }
            #gantt-master-container.gantt-staff-dragging .mygantt-bar:hover { transform: none; }
            #gantt-master-container .mygantt-bar.gantt-drop-hover {
                outline: 2px solid #2563eb !important;
                outline-offset: 2px !important;
                box-shadow: inset 0 0 0 2px #fff, 0 0 0 5px rgb(96 165 250 / 34%) !important;
                z-index: 40 !important;
            }
            #gantt-master-container [data-staff-unassign-target].gantt-drop-hover {
                outline: 2px solid #b45309;
                outline-offset: -2px;
                background-color: #fffbeb !important;
            }
            #gantt-master-container [data-staff-unassign-target].gantt-drop-hover::after {
                content: "Αφαίρεση από τη βάρδια";
                position: absolute;
                bottom: 6px;
                right: 8px;
                padding: 3px 7px;
                border-radius: 5px;
                background: #92400e;
                color: #fff;
                font-size: 11px;
                font-weight: 700;
                pointer-events: none;
            }
            @media (prefers-reduced-motion: reduce) {
                #gantt-master-container .gantt-transfer-worker { transition: none; }
            }
        </style>
        """

    html += """
    <style>
      :root[data-staff-theme="dark"] {
          --gantt-surface: #0f172a;
          --gantt-alternate: #131e31;
          --gantt-today: #1b2c46;
          --gantt-header: #1e293b;
          --gantt-edge: #475569;
          --gantt-line: #334155;
          --gantt-grid: #314158;
          --gantt-tick: #64748b;
          --gantt-text: #e2e8f0;
          --gantt-heading: #f8fafc;
          --gantt-leave: #fca5a5;
          --gantt-available: #86efac;
          --gantt-later: #7dd3fc;
          --gantt-restricted: #c4b5fd;
          --gantt-unavailable: #fcd34d;
          --gantt-menu-bg: #1e293b;
          --gantt-menu-active: #334b6d;
          --gantt-menu-focus: #93c5fd;
      }
      #gantt-master-container::-webkit-scrollbar { width:12px; height:12px; }
      #gantt-master-container::-webkit-scrollbar-track { background:var(--gantt-header, #f1f5f9); border-radius:8px; }
      #gantt-master-container::-webkit-scrollbar-thumb {
          background:#94a3b8; border-radius:8px; border:3px solid var(--gantt-header, #f1f5f9);
      }
      #gantt-master-container::-webkit-scrollbar-thumb:hover { background:#64748b; }
      .mygantt-bar:hover {
          transform:scale(1.02); z-index:30 !important;
          box-shadow:0 6px 12px rgba(0,0,0,0.3) !important; outline:2px solid #1e293b !important;
      }
      .gantt-bar-content {
          flex:1 1 auto; min-width:0; max-height:100%; overflow:hidden;
          box-sizing:border-box; padding:0 3px; line-height:1.15;
          pointer-events:none; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical;
          overflow-wrap:anywhere;
      }
      .gantt-floating-actions {
          position:fixed; z-index:9999; display:grid; place-items:center;
          box-sizing:border-box; width:24px; height:24px; padding:0;
          border:1px solid #64748b; border-radius:6px; background:#1e293b;
          color:#fff; font:700 18px/1 system-ui,sans-serif; cursor:pointer;
          box-shadow:0 2px 6px rgba(15,23,42,0.24);
      }
      .gantt-floating-actions[hidden] { display:none; }
      .gantt-floating-actions:hover, .gantt-floating-actions[aria-expanded='true'] { background:#334155; }
      .gantt-floating-actions:focus-visible { outline:2px solid #60a5fa; outline-offset:2px; }
      .gantt-bar-menu {
          position:fixed; z-index:10000; box-sizing:border-box; width:min(18rem, calc(100vw - 12px));
          max-height:calc(100vh - 12px); overflow:auto; padding:5px;
          background:var(--gantt-menu-bg, #fff); border:1px solid var(--gantt-edge, #cbd5e1); border-radius:9px;
          box-shadow:0 8px 24px rgba(15,23,42,0.22); font:13px/1.3 system-ui,sans-serif; color:var(--gantt-text, #0f172a);
      }
      .gantt-bar-menu button {
          display:block; width:100%; text-align:left; padding:8px 10px; border:0; border-radius:5px;
          color:inherit; background:transparent; font:inherit; cursor:pointer;
      }
      .gantt-bar-menu button:hover, .gantt-bar-menu button:focus-visible {
          background:var(--gantt-menu-active, #e0e7ff); outline:2px solid var(--gantt-menu-focus, #6366f1); outline-offset:-2px;
      }
      .gantt-bar-menu > button + .gantt-email-options {
          margin-top:4px; padding-top:4px; border-top:1px solid var(--gantt-line, #e2e8f0);
      }
    </style>
    """

    html += "<div style='display: flex; position: sticky; top: 0; z-index: 100; background: var(--gantt-header, #f8fafc); border-bottom: 3px solid var(--gantt-edge, #1e293b); min-width: max-content;'>"
    html += "<div style='width: 230px; min-width: 230px; position: sticky; left: 0; z-index: 101; background: var(--gantt-header, #f8fafc); border-right: 3px solid var(--gantt-edge, #1e293b); padding: 10px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: var(--gantt-heading, #1e293b); font-size: 14px;'>Ημέρα / Προσωπικό</div>"
    html += f"<div class='gantt-timeline-header' style='position: relative; width: {timeline_width_px}px; min-width: {timeline_width_px}px; height: 45px; background: var(--gantt-header, #f8fafc);'>"

    for h in range(4, 25):
        pct = ((h - 4) / 20) * 100
        lbl = f"{h:02d}:00" if h < 24 else "00:00"
        html += f"<div style='position: absolute; left: {pct}%; height: 100%; border-left: 2px solid var(--gantt-tick, #94a3b8); padding-left: 4px; padding-top: 14px; font-weight: bold; font-size: 13px; color: var(--gantt-text, #334155);'>{lbl}</div>"
    html += "</div></div>"

    unassign_attr = " data-staff-unassign-target" if staff_drag_token else ""
    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"

        leaves_today = []
        for l in st.session_state.leaves:
            if l["startDate"] <= curr_date <= l["endDate"]:
                emp_n = emp_short_names.get(l["employeeId"], utils.get_employee_name(l["employeeId"]))
                # Στην αριστερή λίστα αδειών, η αναρρωτική επισημαίνεται διακριτικά.
                # Παλαιότερες εγγραφές χωρίς leaveType αντιμετωπίζονται ως κανονική άδεια.
                leave_type = str(l.get("leaveType") or l.get("leave_type") or "").strip().lower()
                sick_marker = (
                    " <small style='font-size: 9px; font-weight: normal;'>ανναρ.</small>"
                    if "αναρ" in leave_type or "sick" in leave_type
                    else ""
                )
                emp_label = f"{html_utils.escape(str(emp_n))}{sick_marker}"
                sub_id = l.get("substituteId")
                if sub_id:
                    sub_n = emp_short_names.get(sub_id, utils.get_employee_name(sub_id))
                    leaves_today.append(f"{emp_label} (Αντ: {html_utils.escape(str(sub_n))})")
                else:
                    leaves_today.append(emp_label)

        def _time_to_sort_minutes(time_value):
            """
            Μετατρέπει ώρα HH:MM σε λεπτά για σωστή σύγκριση.
            Αν η ώρα είναι μετά τα μεσάνυχτα και πριν τις 04:00, θεωρείται συνέχεια της ημέρας.
            """
            raw = str(time_value or "")[:5]
            try:
                hour, minute = map(int, raw.split(":"))
            except Exception:
                return None

            if hour < 4:
                hour += 24

            return hour * 60 + minute

        available_after_6 = []
        available_after_10 = []
        unavailable_staff = []
        restricted_staff = []
        day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
        limit_6 = 6 * 60
        limit_10 = 10 * 60

        for emp in external_crews:
            eid = emp["id"]
            if any(l["employeeId"] == eid and l["startDate"] <= curr_date <= l["endDate"] for l in st.session_state.leaves):
                continue

            emp_label = emp_short_names.get(eid, emp["name"])
            escaped_name = html_utils.escape(str(emp_label))
            drag_name = drag_worker(eid, escaped_name, from_list=True)

            employee_day_assigns = [
                a for a in day_assigns
                if a.get("employeeId") == eid
                and not a.get("is_cancelled", False)
            ]

            end_minutes = [
                _time_to_sort_minutes(a.get("endTime"))
                for a in employee_day_assigns
            ]
            end_minutes = [value for value in end_minutes if value is not None]

            latest_end_minutes = max(end_minutes) if end_minutes else None

            # Daily, persistent availability restrictions are distinct from
            # ordinary shift occupancy and official leave.
            employee_rules = [
                r for r in availability_rules
                if isinstance(r, dict) and matches(r, curr_date, eid)
                and r.get("kind") in ("unavailable", "only_available")
            ] if rules_ready else []
            entire_day_blocked = False
            partial_rules = []
            for rule in employee_rules:
                window = rule_window(rule)
                if window is None:
                    # Invalid stored rules must never result in a green "available" label.
                    entire_day_blocked = True
                    continue
                if rule.get("kind") == "unavailable" and window == (0, 1440):
                    entire_day_blocked = True
                elif window != (0, 1440):
                    kind_label = "μόνο" if rule.get("kind") == "only_available" else "όχι"
                    partial_rules.append(
                        f"{kind_label} {window[0] // 60:02d}:{window[0] % 60:02d}"
                        f"–{window[1] // 60:02d}:{window[1] % 60:02d}"
                    )
            if entire_day_blocked and not employee_day_assigns:
                unavailable_staff.append(
                    f"{drag_name} "
                    "<small style='font-size: 9px; font-weight: normal;'>"
                    "(δηλωμένη μη διαθεσιμότητα)</small>"
                )
            if partial_rules and not entire_day_blocked:
                restricted_staff.append(
                    f"{escaped_name} "
                    "<small style='font-size: 9px; font-weight: normal;'>"
                    f"({html_utils.escape(', '.join(partial_rules))})</small>"
                )

            # Δύο κατηγορίες διαθεσιμότητας:
            # 1) ΔΙΑΘΕΣΙΜΟΙ:
            #    δεν έχουν βάρδια στη μέρα ή η τελευταία βάρδια τους λήγει έως 06:00.
            # 2) ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ:
            #    η τελευταία βάρδια τους λήγει μετά τις 06:00 και έως 10:00.
            #
            # Διατηρούμε ΑΚΡΙΒΩΣ την υπάρχουσα λογική διαθεσιμότητας.
            if rules_ready and not entire_day_blocked and not partial_rules:
                if latest_end_minutes is None or latest_end_minutes <= limit_6:
                    available_after_6.append(drag_name)
                elif latest_end_minutes <= limit_10:
                    available_after_10.append(drag_name)

            # Η τρίτη λίστα περιλαμβάνει ΟΛΟΥΣ όσους έχουν ανατεθεί
            # σε τουλάχιστον μία ενεργή βάρδια, ανεξάρτητα από ώρα λήξης.
            # Οι ώρες είναι το άθροισμα όλων των έργων της ημέρας.
            if employee_day_assigns:
                total_minutes = 0
                for a in employee_day_assigns:
                    start_minutes = _time_to_sort_minutes(a.get("startTime"))
                    finish_minutes = _time_to_sort_minutes(a.get("endTime"))
                    if start_minutes is None or finish_minutes is None:
                        continue
                    if finish_minutes <= start_minutes:
                        finish_minutes += 24 * 60
                    total_minutes += finish_minutes - start_minutes

                if total_minutes > 0:
                    hours, minutes = divmod(total_minutes, 60)
                    hours_label = f"{hours} ώρ." + (f" {minutes} λ." if minutes else "")
                    declared_label = " · δηλωμένη μη διαθεσιμότητα" if entire_day_blocked else ""
                    unavailable_staff.append(
                        f"{drag_name} "
                        f"<small style='font-size: 9px; font-weight: normal;'>"
                        f"({hours_label}{declared_label})</small>"
                    )

        label_html = f"<div style='font-size: 14px; font-weight: bold; margin-bottom: 8px; color: var(--gantt-heading, inherit);'>🗓️ {day_str}</div>"
        if leaves_today:
            label_html += f"<div style='color: var(--gantt-leave, #d32f2f); margin-bottom: 8px; font-size: 11px;'><b>Άδειες:</b><br>{'<br>'.join(leaves_today)}</div>"
        if available_after_6:
            label_html += f"<div style='color: var(--gantt-available, #15803d); margin-bottom: 8px; font-size: 11px;'><b>ΔΙΑΘΕΣΙΜΟΙ:</b><br>{'<br>'.join(available_after_6)}</div>"
        if available_after_10:
            label_html += f"<div style='color: var(--gantt-later, #0369a1); font-size: 11px;'><b>ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ:</b><br>{'<br>'.join(available_after_10)}</div>"
        if restricted_staff:
            label_html += (
                "<div style='color: var(--gantt-restricted, #7c3aed); margin-top: 8px; font-size: 11px;'>"
                f"<b>ΠΕΡΙΟΡΙΣΜΕΝΗ ΔΙΑΘΕΣΙΜΟΤΗΤΑ:</b><br>{'<br>'.join(restricted_staff)}</div>"
            )
        if unavailable_staff:
            label_html += f"<div style='color: var(--gantt-unavailable, #b45309); margin-top: 8px; font-size: 11px;'><b>ΜΗ ΔΙΑΘΕΣΙΜΟΙ:</b><br>{'<br>'.join(unavailable_staff)}</div>"

        day_groups = [g for g in wk_groups.values() if g["Date"] == curr_date]

        # Οι μπλε μπάρες μπαίνουν πάντα κάτω από όλες τις άλλες μπάρες της ημέρας.
        # Δεν αλλάζει η αποθήκευση ούτε η λογική των βαρδιών· μόνο η οπτική στοίβαξη.
        blue_stack_hex = config.BLUE_STACK_HEX.lower()
        non_blue_groups = [g for g in day_groups if str(g.get("ColorHex", "")).lower() != blue_stack_hex]
        blue_groups = [g for g in day_groups if str(g.get("ColorHex", "")).lower() == blue_stack_hex]

        def t2p(t_str):
            h, m = map(int, t_str.split(":"))
            if h < 4:
                h += 24
            mins = (h - 4) * 60 + m
            return max(0, min(100, (mins / 1200.0) * 100))

        group_lanes = []

        def pack_lanes(groups, offset=0):
            lane_ends = []
            for group in sorted(groups, key=lambda g: g["StartTime"]):
                start = group["StartTime"]
                end = group["EndTime"]
                lane = next((i for i, lane_end in enumerate(lane_ends) if start >= lane_end), len(lane_ends))
                if lane == len(lane_ends):
                    lane_ends.append(end)
                else:
                    lane_ends[lane] = end
                group_lanes.append((group, offset + lane))
            return len(lane_ends)

        non_blue_lane_count = pack_lanes(non_blue_groups)
        total_lanes = non_blue_lane_count + pack_lanes(blue_groups, non_blue_lane_count)
        row_height = max(1, total_lanes) * LANE_STEP_PX + ROW_PAD_TOP_PX + ROW_PAD_BOTTOM_PX
        if curr_date == get_local_today():
            bg_color_row = "var(--gantt-today, #eef2ff)"
        elif i % 2 == 1:
            bg_color_row = "var(--gantt-alternate, #f8fafc)"
        else:
            bg_color_row = "var(--gantt-surface, #ffffff)"

        html += f"<div style='display: flex; min-width: max-content; border-bottom: 2px solid var(--gantt-line, #e2e8f0); background-color: {bg_color_row}; min-height: {row_height}px;'>"
        html += f"<div{unassign_attr} style='width: 230px; min-width: 230px; position: sticky; left: 0; z-index: 50; background-color: {bg_color_row}; border-right: 3px solid var(--gantt-edge, #1e293b); padding: 10px; box-sizing: border-box;'>{label_html}</div>"
        html += f"<div style='position: relative; width: {timeline_width_px}px; min-width: {timeline_width_px}px; background-image: linear-gradient(to right, var(--gantt-grid, rgba(148, 163, 184, 0.3)) 1px, transparent 1px); background-size: calc(100% / 20) 100%; padding-top: {ROW_PAD_TOP_PX}px; padding-bottom: {ROW_PAD_BOTTOM_PX}px;'>"

        for g, lane_idx in group_lanes:
            left_pct = t2p(g["StartTime"])
            width_pct = t2p(g["EndTime"]) - left_pct
            top_px = lane_idx * LANE_STEP_PX + ROW_PAD_TOP_PX

            def _employee_text_html(employee_name, *, name_only=False):
                """
                Μορφοποίηση μόνο του ονόματος εργαζόμενου μέσα στη μπάρα.
                - Κανονικά ονόματα: λευκά γράμματα.
                - Ένδειξη [ΜΕΤΑ ΑΠΟ ...]: κόκκινη ένδειξη, λευκό το όνομα.
                Δεν αλλάζει δεδομένα ή λογική, μόνο HTML εμφάνιση.
                """
                text_value = str(employee_name or "").upper().strip()
                if text_value.startswith("[ΜΕΤΑ ΑΠΟ ") and "▶" in text_value:
                    before_arrow, after_arrow = text_value.split("▶", 1)
                    after_arrow = after_arrow.strip()
                    closing = ""
                    if after_arrow.endswith("]"):
                        after_arrow = after_arrow[:-1].strip()
                        closing = "]"

                    if name_only:
                        text_value = after_arrow
                    else:
                        red_part = html_utils.escape(before_arrow.strip() + " ▶")
                        white_name = html_utils.escape(after_arrow)
                        red_closing = html_utils.escape(closing)
                        return (
                            "<span style='color:var(--gantt-context-color, #dc2626); font-weight:900;'>"
                            + red_part
                            + " </span>"
                            + "<span style='color:#ffffff; font-weight:900; text-shadow:0 1px 2px rgba(0,0,0,0.55);'>"
                            + white_name
                            + "</span>"
                            + "<span style='color:var(--gantt-context-color, #dc2626); font-weight:900;'>"
                            + red_closing
                            + "</span>"
                        )

                return (
                    "<span style='color:#ffffff; font-weight:900; text-shadow:0 1px 2px rgba(0,0,0,0.55);'>"
                    + html_utils.escape(text_value)
                    + "</span>"
                )

            def _group_employee_labels(employee_names):
                """
                Ομαδοποιεί εργαζόμενους που έχουν ίδια ένδειξη:
                [ΜΕΤΑ ΑΠΟ 'ΕΡΓΟ' ▶ ΟΝΟΜΑ]
                ώστε να εμφανίζονται ως:
                [ΜΕΤΑ ΑΠΟ 'ΕΡΓΟ' ▶ ΟΝΟΜΑ1, ΟΝΟΜΑ2]
                """
                grouped_after = {}
                normal_names = []

                for raw_name in employee_names or []:
                    text_value = str(raw_name or "").upper().strip()

                    if text_value.startswith("[ΜΕΤΑ ΑΠΟ ") and "▶" in text_value:
                        before_arrow, after_arrow = text_value.split("▶", 1)
                        after_arrow = after_arrow.strip()

                        if after_arrow.endswith("]"):
                            after_arrow = after_arrow[:-1].strip()

                        prefix = before_arrow.strip()
                        grouped_after.setdefault(prefix, [])
                        if after_arrow and after_arrow not in grouped_after[prefix]:
                            grouped_after[prefix].append(after_arrow)
                    else:
                        if text_value and text_value not in normal_names:
                            normal_names.append(text_value)

                result = list(normal_names)

                for prefix, names in grouped_after.items():
                    if names:
                        result.append(f"{prefix} ▶ {', '.join(names)}]")

                return result

            grouped_employee_labels = _group_employee_labels(g["Employees"])
            emps_plain = ", ".join(grouped_employee_labels).upper()
            emps_html = ", ".join(_employee_text_html(emp) for emp in grouped_employee_labels)
            handles = []
            if staff_drag_token and not g.get("is_cancelled"):
                seen = set()
                employee_ids = [eid for eid in g.get("EmployeeIds", []) if eid]
                for eid, employee_label in zip(employee_ids, g["Employees"]):
                    if eid in seen:
                        continue
                    seen.add(eid)
                    full_name = employee_details_by_id.get(eid, {}).get("name")
                    short_label = _employee_text_html(employee_label, name_only=True)
                    label = html_utils.escape(full_name) if full_name else short_label
                    handles.append(drag_worker(eid, label, full_name=full_name))
            proj_name = g.get("ProjectDisplay", g["Project"]).upper()
            arr_str = f"[Προσ: {g['ArrivalTime']}] " if g["ArrivalTime"] else ""

            if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_plain:
                emps_plain = "⚠️ " + emps_plain
                emps_html = "⚠️ " + emps_html

            base_text_plain = f"{arr_str}{g['StartTime']}-{g['EndTime']} | {proj_name} | {emps_plain}"
            schedule = f"{html_utils.escape(arr_str)}{g['StartTime']}-{g['EndTime']}"
            project_html = html_utils.escape(proj_name)
            summary = f"{schedule} | {project_html}"
            pending_html = ""

            pending = g.get("CustomerConfirmation")
            if pending is not None and not g["is_cancelled"]:
                pending_label = placement_confirmation.PENDING_LABEL
                follow_up = placement_confirmation.follow_up_label(pending)
                base_text_plain = " · ".join(part for part in (pending_label, follow_up, base_text_plain) if part)
                pending_html = (
                    "<span style='background:#fef3c7;color:#78350f;padding:0 3px;border-radius:3px;'>"
                    f"{pending_label}</span> "
                )
                summary = f"{pending_html}{summary}"
            notes_html = ""
            if g["Notes"]:
                notes_upper = g["Notes"].upper()
                base_text_plain += f" ({notes_upper})"
                notes_html = f" ({html_utils.escape(notes_upper)})"

            base_text = f"{summary} | {emps_html}{notes_html}"
            if g["is_cancelled"]:
                base_text = f"<s>{base_text}</s>"
                if g["cancel_reason"]:
                    cancel_reason_upper = g["cancel_reason"].upper()
                    base_text_plain += f" [{cancel_reason_upper}]"
                    base_text += f"<br><span style='color:#dc2626;'>[{html_utils.escape(cancel_reason_upper)}]</span>"

            bg_color = g["ColorHex"]
            tooltip = html_utils.escape(base_text_plain, quote=True)
            project_copy_attr = html_utils.escape(str(g["Project"]), quote=True)
            full_bar_copy_attr = html_utils.escape(base_text_plain, quote=True)

            # Αντιγραφή ομάδας προσωπικού: πλήρη ονόματα και Α.Δ.Τ.
            # Χρησιμοποιούμε EmployeeIds (όχι τα συντομευμένα εμφανιζόμενα ονόματα)
            # και αποφεύγουμε διπλότυπα για την ίδια μπάρα.
            crew_lines = []
            crew_html_items = []
            seen_crew_ids = set()
            for employee_id in g.get("EmployeeIds", []):
                if not employee_id or employee_id in seen_crew_ids:
                    continue
                seen_crew_ids.add(employee_id)
                details = employee_details_by_id.get(employee_id, {})
                full_employee_name = str(
                    details.get("name") or utils.get_employee_name(employee_id)
                ).strip()
                card_number = str(details.get("id_number") or "").strip()
                card_display = card_number if card_number else "δεν έχει καταχωρηθεί"
                item_text = f"{full_employee_name}, με Α.Δ.Τ.: {card_display}"
                crew_lines.append(f"- {item_text}")
                crew_html_items.append(f"<li>{html_utils.escape(item_text)}</li>")

            if not crew_lines:
                crew_lines.append("- Χωρίς προσωπικό")
                crew_html_items.append("<li>Χωρίς προσωπικό</li>")

            crew_copy_text = "Ομάδα εργαζομένων:\n\n" + "\n".join(crew_lines)
            crew_copy_html = (
                "<div><strong>Ομάδα εργαζομένων:</strong></div>"
                "<ul>" + "".join(crew_html_items) + "</ul>"
            )
            crew_text_attr = html_utils.escape(crew_copy_text, quote=True)
            crew_html_attr = html_utils.escape(crew_copy_html, quote=True)

            # Κόκκινη περιμετρική ένδειξη για μπάρες που έχουν τικαριστεί ως "Γενικός".
            # Χρησιμοποιούμε border + outline + inset box-shadow, ώστε να φαίνεται καθαρά
            # πάνω σε οποιοδήποτε χρώμα μπάρας. Δεν αλλάζει λειτουργία ή δεδομένα.
            is_general_bar = bool(g.get("IsGeneral", False) or g.get("is_general", False))
            bar_border = "3px solid #dc2626" if is_general_bar else "1px solid rgba(0,0,0,0.5)"
            bar_outline = "3px solid #dc2626" if is_general_bar else "none"
            bar_outline_offset = "-3px" if is_general_bar else "0"
            bar_shadow = (
                "inset 0 0 0 3px #dc2626, 0 0 0 2px rgba(220,38,38,0.55), 0 3px 8px rgba(0,0,0,0.25)"
                if is_general_bar
                else "0 3px 6px rgba(0,0,0,0.15)"
            )

            if pending is not None and not g["is_cancelled"]:
                bar_border = "2px dashed #92400e" if not is_general_bar else "3px dashed #dc2626"
                bar_outline = "none"

            safe_id = key_to_safe_id.get(g["Key"], "")
            is_focused = g["Key"] == focused_key
            focus_attr = " data-gantt-search-target='true'" if is_focused and scroll_to_focus else ""
            focus_style = "outline: 3px solid #2563eb; outline-offset: 2px; z-index: 25;" if is_focused else ""
            drop_attr = " data-staff-drop-target='true'" if staff_drag_token and not g.get("is_cancelled") else ""

            copy_actions = (
                ("crew", f"data-crew-text='{crew_text_attr}' data-crew-html='{crew_html_attr}'",
                 "Αντιγραφή ονομάτων και Α.Δ.Τ. εργαζομένων"),
                ("full", f"data-full-content='{full_bar_copy_attr}'", "Αντιγραφή περιεχομένου μπάρας"),
                ("project", f"data-project='{project_copy_attr}'", "Αντιγραφή ονόματος έργου"),
            )
            width_px = width_pct * timeline_width_px / 100
            stacked_attr = " data-gantt-stacked='true'" if width_px < STACKED_BAR_WIDTH else ""
            buttons = "".join(
                f"<button type='button' class='gantt-copy-{kind}-btn' {data}>{label}</button>"
                for kind, data, label in copy_actions
            )
            email_options = gantt_email.menu_html(g, employee_details_by_id) if email_menu else ""
            actions = f"<template class='gantt-action-options'>{buttons}{email_options}</template>"

            transfer_attr = ""
            if handles:
                transfer_attr = " data-staff-transfer-bar"
                base_text = (
                    f"<strong class='gantt-transfer-project' title='{html_utils.escape(proj_name, quote=True)}'>"
                    f"{project_html}</strong>"
                    f"<div class='gantt-transfer-schedule'>{pending_html}{schedule}{notes_html}</div>"
                    "<div class='gantt-transfer-roster' role='group' aria-label='Προσωπικό για μεταφορά' tabindex='0'>"
                    f"{''.join(handles)}</div>"
                )

            html += (
                f"<a href='javascript:void(0);' id='{safe_id}' draggable='false' class='mygantt-bar' aria-keyshortcuts='Shift+F10'{focus_attr}{drop_attr}{stacked_attr}{transfer_attr} "
                f"style='position: absolute; left: {left_pct}%; width: {width_pct}%; top: {top_px}px; height: {BAR_HEIGHT_PX}px; "
                f"background-color: {bg_color}; border: {bar_border}; border-radius: 6px; "
                f"box-shadow: {bar_shadow}; outline: {bar_outline}; outline-offset: {bar_outline_offset}; display: flex; align-items: center; justify-content: center; "
                f"font-size: 11px; font-weight: bold; color: black; text-decoration: none; cursor: pointer; transition: all 0.1s; "
                f"box-sizing: border-box; overflow: hidden; z-index: 10; padding-block: 0; margin-block: 0; text-align: center; {focus_style}' title='{tooltip}'>"
                f"<div class='gantt-bar-content'>{base_text}</div>"
                f"{actions}</a>"
            )

        html += "</div></div>"

    html += (
        "</div><button type='button' id='gantt-floating-actions' class='gantt-floating-actions' "
        "aria-label='Ενέργειες μπάρας' aria-expanded='false' title='Ενέργειες μπάρας' tabindex='-1' hidden>⋯</button>"
    )

    if staff_drag_token:
        html += "<a href='javascript:void(0);' id='gantt-staff-drop-event' data-staff-drop-event style='display:none'></a>"

    # --- JS Injector (Base64) ---
    # FIX: σε κάθε rerun κάνουμε cleanup παλιών listeners και ξαναδένουμε στο νέο gantt element.
    # Επίσης κρατάμε και vertical θέση (scrollTop), όχι μόνο horizontal.
    js_code = """
    (function () {
      var s = document.getElementById('gantt-master-container');
      if (!s) return;

      if (window.ganttDragCleanup) {
        try { window.ganttDragCleanup(); } catch (e) {}
        window.ganttDragCleanup = null;
      }

      var savedScrollLeft = sessionStorage.getItem('ganttScrollLeft');
      var savedScrollTop = sessionStorage.getItem('ganttScrollTop');

      var target = s.querySelector('[data-gantt-search-target]');
      if (target) {
        var bounds = s.getBoundingClientRect();
        var bar = target.getBoundingClientRect();
        s.scrollLeft += bar.left - bounds.left - s.clientWidth / 3;
        s.scrollTop += bar.top - bounds.top - s.clientHeight / 3;
      } else if (savedScrollLeft !== null) {
          s.scrollLeft = parseFloat(savedScrollLeft);
      } else {
          setTimeout(function(){ s.scrollLeft = s.scrollWidth * 0.10; }, 50);
      }

      if (!target && savedScrollTop !== null) {
          s.scrollTop = parseFloat(savedScrollTop);
      }

      var isDown = false;
      var startX = 0;
      var scrollLeftStart = 0;
      var moved = false;
      var DRAG_THRESHOLD = 5;
      window.gIsDragging = false;
      var staffDrag = null;
      var dragHandle = null;
      var hoverTarget = null;
      var blockBarClickUntil = 0;
      var menu = null;
      var actionButton = document.getElementById('gantt-floating-actions');
      var actionBar = null;
      var actionTimer;

      function onScroll() {
        hideBarActions();
        clearTimeout(onScroll._t);
        onScroll._t = setTimeout(function() {
          sessionStorage.setItem('ganttScrollLeft', String(s.scrollLeft));
          sessionStorage.setItem('ganttScrollTop', String(s.scrollTop));
        }, 100);
      }

      function startDrag(pageX) {
        isDown = true;
        moved = false;
        window.gIsDragging = false;
        startX = pageX - s.offsetLeft;
        scrollLeftStart = s.scrollLeft;
        s.style.cursor = 'grabbing';
        if (document.body) document.body.style.userSelect = 'none';
      }

      function moveDrag(pageX, ev) {
        if (!isDown) return;
        if (ev) ev.preventDefault();
        var walk = (pageX - s.offsetLeft) - startX;
        if (Math.abs(walk) > DRAG_THRESHOLD) {
          moved = true;
          window.gIsDragging = true;
        }
        s.scrollLeft = scrollLeftStart - walk * 1.5;
      }

      function endDrag() {
        if (!isDown) return;
        isDown = false;
        s.style.cursor = 'grab';
        if (document.body) document.body.style.userSelect = '';
        setTimeout(function(){ window.gIsDragging = false; }, 80);
      }

      function onMouseDown(e) {
        if (e.target.closest('.gantt-transfer-roster')) return;
        if (e.target.closest('.gantt-transfer-worker')) return;
        if (e.button !== 0) return;
        startDrag(e.pageX);
      }

      function onMouseMoveLocal(e) {
        moveDrag(e.pageX, e);
      }

      function onMouseMoveWin(e) {
        moveDrag(e.pageX, e);
      }

      function onMouseUp() {
        endDrag();
      }

      function onMouseLeave() {
        endDrag();
      }

      function onBlur() {
        endDrag();
      }

      function onTouchStart(e) {
        if (e.target.closest('.gantt-transfer-roster')) return;
        if (!e.touches || !e.touches[0]) return;
        isDown = true;
        moved = false;
        window.gIsDragging = false;
        startX = e.touches[0].pageX - s.offsetLeft;
        scrollLeftStart = s.scrollLeft;
      }

      function onTouchMove(e) {
        if (!isDown || !e.touches || !e.touches[0]) return;
        var walk = (e.touches[0].pageX - s.offsetLeft) - startX;
        if (Math.abs(walk) > DRAG_THRESHOLD) {
          moved = true;
          window.gIsDragging = true;
        }
        s.scrollLeft = scrollLeftStart - walk * 1.5;
      }

      function onTouchEnd() {
        endDrag();
      }

      function onDragStart(e) {
        var handle = e.target.closest('.gantt-transfer-worker');
        if (!handle || !s.dataset.staffDragToken) {
          e.preventDefault();
          return;
        }
        var sourceBar = handle.closest('a.mygantt-bar');
        if (!sourceBar && handle.dataset.staffOrigin !== 'availability') {
          e.preventDefault();
          return;
        }
        staffDrag = { source: sourceBar ? sourceBar.id : null, employee: handle.dataset.employee };
        isDown = false;
        moved = false;
        window.gIsDragging = false;
        e.dataTransfer.effectAllowed = sourceBar ? 'move' : 'copy';
        e.dataTransfer.setData('text/plain', JSON.stringify(staffDrag));
        dragHandle = handle;
        dragHandle.classList.add('gantt-drag-origin');
        s.classList.add('gantt-staff-dragging');
        hideBarActions();
        e.stopPropagation();
      }

      function clearStaffHover() {
        if (hoverTarget) hoverTarget.classList.remove('gantt-drop-hover');
        hoverTarget = null;
      }

      function dropTarget(e) {
        if (!staffDrag) return null;
        var bar = e.target.closest('a[data-staff-drop-target]');
        if (bar) return bar.id !== staffDrag.source ? bar : null;
        return staffDrag.source ? e.target.closest('[data-staff-unassign-target]') : null;
      }

      function onStaffDragOver(e) {
        if (!staffDrag) return;
        var destination = dropTarget(e);
        if (destination) {
          e.preventDefault();
          e.dataTransfer.dropEffect = staffDrag.source ? 'move' : 'copy';
        }
        if (destination !== hoverTarget) {
          clearStaffHover();
          if (destination) {
            hoverTarget = destination;
            hoverTarget.classList.add('gantt-drop-hover');
          }
        }
        var rect = s.getBoundingClientRect();
        if (e.clientX < rect.left + 35) s.scrollLeft -= 18;
        if (e.clientX > rect.right - 35) s.scrollLeft += 18;
        if (e.clientY < rect.top + 35) s.scrollTop -= 18;
        if (e.clientY > rect.bottom - 35) s.scrollTop += 18;
      }

      function onStaffDrop(e) {
        var destination = dropTarget(e);
        if (!destination) return;
        e.preventDefault();
        e.stopPropagation();
        var eventLink = document.querySelector('[data-staff-drop-event]');
        if (eventLink) {
          eventLink.id = 'gantt_staff_drop:' + encodeURIComponent(JSON.stringify({
            token: s.dataset.staffDragToken, source: staffDrag.source,
            target: destination.id || null, employee: staffDrag.employee,
            nonce: Date.now().toString(36) + Math.random().toString(36).slice(2)
          }));
          eventLink.click();
        }
        onStaffDragEnd();
      }

      function onStaffDragEnd() {
        staffDrag = null;
        if (dragHandle) dragHandle.classList.remove('gantt-drag-origin');
        dragHandle = null;
        s.classList.remove('gantt-staff-dragging');
        clearStaffHover();
        blockBarClickUntil = Date.now() + 250;
      }

      function copyTextToClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
          return navigator.clipboard.writeText(text);
        }
        return copyTextFallback(text);
      }

      function copyTextFallback(text, htmlText) {
        return new Promise(function(resolve, reject) {
          var textarea = document.createElement('textarea');
          textarea.value = text;
          textarea.setAttribute('readonly', '');
          textarea.dataset.ganttClipboard = '';
          textarea.style.position = 'fixed';
          textarea.style.left = '-9999px';
          textarea.style.top = '-9999px';

          function setFormattedClipboard(event) {
            if (!event.clipboardData) return;
            event.clipboardData.setData('text/plain', text);
            event.clipboardData.setData('text/html', htmlText);
            event.preventDefault();
          }

          document.body.appendChild(textarea);
          if (htmlText) document.addEventListener('copy', setFormattedClipboard);
          try {
            textarea.select();
            if (document.execCommand('copy')) resolve();
            else reject(new Error('copy command failed'));
          } catch (err) {
            reject(err);
          } finally {
            if (htmlText) document.removeEventListener('copy', setFormattedClipboard);
            document.body.removeChild(textarea);
          }
        });
      }

      function copyFormattedToClipboard(text, htmlText) {
        if (navigator.clipboard && window.isSecureContext &&
            typeof navigator.clipboard.write === 'function' &&
            typeof ClipboardItem !== 'undefined' &&
            typeof Blob !== 'undefined' && htmlText) {
          try {
            var clipboardItem = new ClipboardItem({
              'text/plain': new Blob([text], {type: 'text/plain'}),
              'text/html': new Blob([htmlText], {type: 'text/html'})
            });
            return navigator.clipboard.write([clipboardItem]).catch(function() {
              return copyTextFallback(text, htmlText).catch(function() { return copyTextToClipboard(text); });
            });
          } catch (err) {
            // Try the copy event if the browser rejects the ClipboardItem.
          }
        }
        return copyTextFallback(text, htmlText).catch(function() { return copyTextToClipboard(text); });
      }

      function copyBarAction(button) {
        var bar = actionBar;
        var text = button.getAttribute('data-email-copy') || button.getAttribute('data-crew-text') ||
          button.getAttribute('data-full-content') || button.getAttribute('data-project');
        if (!text) return;
        var formatted = button.getAttribute('data-email-html') || button.getAttribute('data-crew-html');
        var copy = formatted ? copyFormattedToClipboard(text, formatted) : copyTextToClipboard(text);

        function showResult(ok) {
          if (bar !== actionBar) return;
          clearTimeout(actionButton.copyFeedbackTimeout);
          actionButton.textContent = ok ? '✓' : '!';
          actionButton.copyFeedbackTimeout = setTimeout(function() { actionButton.textContent = '⋯'; }, 900);
        }
        copy.then(function() { showResult(true); }).catch(function() { showResult(false); });
      }

      function closeBarMenu(restoreFocus) {
        if (!menu) return;
        menu.remove();
        menu = null;
        actionButton.setAttribute('aria-expanded', 'false');
        if (restoreFocus && actionBar && actionBar.isConnected) actionBar.focus({preventScroll: true});
      }

      function hideBarActions() {
        clearTimeout(actionTimer);
        closeBarMenu();
        actionBar = null;
        if (actionButton) {
          clearTimeout(actionButton.copyFeedbackTimeout);
          actionButton.textContent = '⋯';
          actionButton.hidden = true;
        }
      }

      function findActionBar(target) {
        var bar = target && target.closest('a.mygantt-bar');
        return bar && s.contains(bar) ? bar : null;
      }

      function showBarActions(bar) {
        clearTimeout(actionTimer);
        if (!actionButton) return false;
        if (actionBar === bar && !actionButton.hidden) return true;
        closeBarMenu();

        var frame = s.getBoundingClientRect();
        var rect = bar.getBoundingClientRect();
        var header = s.querySelector('.gantt-timeline-header');
        var labels = header && header.previousElementSibling;
        var viewport = document.documentElement;
        var left = Math.max(0, frame.left + s.clientLeft, labels ? labels.getBoundingClientRect().right : 0);
        var top = Math.max(0, frame.top + s.clientTop, header ? header.getBoundingClientRect().bottom : 0);
        var right = Math.min(viewport.clientWidth, frame.left + s.clientLeft + s.clientWidth);
        var bottom = Math.min(viewport.clientHeight, frame.top + s.clientTop + s.clientHeight);
        var barLeft = Math.max(rect.left, left);
        var barRight = Math.min(rect.right, right);
        var barTop = Math.max(rect.top, top);
        var barBottom = Math.min(rect.bottom, bottom);
        if (barRight <= barLeft || barBottom <= barTop) {
          hideBarActions();
          return false;
        }

        actionButton.hidden = false;
        var width = actionButton.offsetWidth;
        var height = actionButton.offsetHeight;
        var gap = 3;
        var x;
        var y = Math.min(barTop, bottom - height);
        if (barRight + gap + width <= right) {
          x = barRight + gap;
        } else if (barLeft - gap - width >= left) {
          x = barLeft - gap - width;
        } else {
          x = Math.max(left, barRight - width);
          y = barTop - gap - height;
          if (y < top) y = barBottom + gap;
          if (y + height > bottom) {
            hideBarActions();
            return false;
          }
        }

        clearTimeout(actionButton.copyFeedbackTimeout);
        actionButton.textContent = '⋯';
        actionButton.style.left = x + 'px';
        actionButton.style.top = y + 'px';
        actionBar = bar;
        return true;
      }

      function onActionsPointerOver(e) {
        if (e.pointerType === 'touch' || isDown || staffDrag || menu) return;
        clearTimeout(actionTimer);
        if (e.target === actionButton) return;
        var bar = findActionBar(e.target);
        if (bar) {
          if (!actionBar) showBarActions(bar);
          else if (bar !== actionBar) actionTimer = setTimeout(function() { showBarActions(bar); }, 110);
        } else if (actionBar) {
          actionTimer = setTimeout(hideBarActions, 180);
        }
      }

      function onActionsPointerOut(e) {
        if (!e.relatedTarget && !menu) hideBarActions();
      }

      function onBarContextMenu(e) {
        var bar = findActionBar(e.target);
        if (!bar || staffDrag || !showBarActions(bar)) return;
        e.preventDefault();
        toggleBarMenu();
      }

      function toggleBarMenu() {
        var wasOpen = !!menu;
        closeBarMenu();
        if (wasOpen || !actionBar) return;

        var template = actionBar.querySelector('.gantt-action-options');
        if (!template || !template.content.querySelector('button')) return;
        menu = document.createElement('div');
        menu.className = 'gantt-bar-menu';
        menu.setAttribute('role', 'group');
        menu.setAttribute('aria-label', actionButton.getAttribute('aria-label'));
        menu.appendChild(template.content.cloneNode(true));
        // ClickDetector replaces its last body child on each render.
        s.parentElement.appendChild(menu);
        actionButton.setAttribute('aria-expanded', 'true');

        var anchor = actionButton.getBoundingClientRect();
        var width = document.documentElement.clientWidth;
        var height = document.documentElement.clientHeight;
        var below = anchor.bottom + 4;
        var above = anchor.top - menu.offsetHeight - 4;
        var top = below + menu.offsetHeight > height - 6 && above >= 6 ? above : below;
        menu.style.left = Math.max(6, Math.min(anchor.right - menu.offsetWidth, width - menu.offsetWidth - 6)) + 'px';
        menu.style.top = Math.max(6, Math.min(top, height - menu.offsetHeight - 6)) + 'px';
        menu.querySelector('button').focus({preventScroll: true});
      }

      function onMenuKeyDown(e) {
        if (!menu) {
          if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) onBarContextMenu(e);
          return;
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          closeBarMenu(true);
        } else if (menu.contains(e.target) && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
          e.preventDefault();
          var buttons = Array.from(menu.querySelectorAll('button'));
          var delta = e.key === 'ArrowDown' ? 1 : -1;
          buttons[(buttons.indexOf(e.target) + delta + buttons.length) % buttons.length].focus();
        }
      }

      function onMenuFocus(e) {
        if (e.target === actionButton || e.target.matches('[data-gantt-clipboard]') || (menu && menu.contains(e.target))) return;
        var bar = findActionBar(e.target);
        if (bar && !staffDrag) {
          closeBarMenu();
          showBarActions(bar);
        } else {
          hideBarActions();
        }
      }

      function onClickCapture(e) {
        if (e.target === actionButton) {
          e.preventDefault();
          e.stopPropagation();
          toggleBarMenu();
          return;
        }

        if (menu && menu.contains(e.target)) {
          var option = e.target.closest('button');
          if (option) {
            e.preventDefault();
            e.stopPropagation();
            closeBarMenu(true);
            copyBarAction(option);
          }
          return;
        }
        closeBarMenu();

        var link = findActionBar(e.target);
        if (link && (window.gIsDragging || moved || Date.now() < blockBarClickUntil)) {
          e.preventDefault();
          e.stopPropagation();
        }
      }

      s.addEventListener('scroll', onScroll);
      if (target) onScroll();
      s.addEventListener('mousedown', onMouseDown, true);
      s.addEventListener('mousemove', onMouseMoveLocal, true);
      window.addEventListener('mousemove', onMouseMoveWin, true);
      s.addEventListener('mouseup', onMouseUp, true);
      s.addEventListener('mouseleave', onMouseLeave, true);
      window.addEventListener('mouseup', onMouseUp, true);
      window.addEventListener('blur', onBlur);

      s.addEventListener('touchstart', onTouchStart, { passive: true, capture: true });
      s.addEventListener('touchmove', onTouchMove, { passive: true, capture: true });
      s.addEventListener('touchend', onTouchEnd, { passive: true, capture: true });

      s.addEventListener('dragstart', onDragStart);
      s.addEventListener('dragover', onStaffDragOver);
      s.addEventListener('drop', onStaffDrop);
      s.addEventListener('dragend', onStaffDragEnd);
      document.addEventListener('click', onClickCapture, true);
      document.addEventListener('keydown', onMenuKeyDown);
      document.addEventListener('focusin', onMenuFocus);
      document.addEventListener('pointerover', onActionsPointerOver);
      document.addEventListener('pointerout', onActionsPointerOut);
      s.addEventListener('contextmenu', onBarContextMenu);
      window.addEventListener('resize', hideBarActions);

      // Follow the app theme in the live iframe. Downloaded HTML keeps its light palette.
      var themeObserver;
      try {
        if (window.parent !== window) {
          const appRoot = window.parent.document.documentElement;
          const applyTheme = () => {
            document.documentElement.dataset.staffTheme = appRoot.dataset.staffTheme || "";
          };
          applyTheme();
          themeObserver = new MutationObserver(applyTheme);
          themeObserver.observe(appRoot, { attributes: true, attributeFilter: ['data-staff-theme'] });
        }
      } catch (e) {
        // A standalone chart may be embedded by a page on another origin.
      }

      window.ganttDragCleanup = function () {
        if (themeObserver) themeObserver.disconnect();
        hideBarActions();
        s.removeEventListener('scroll', onScroll);
        s.removeEventListener('mousedown', onMouseDown, true);
        s.removeEventListener('mousemove', onMouseMoveLocal, true);

        window.removeEventListener('mousemove', onMouseMoveWin, true);
        s.removeEventListener('mouseup', onMouseUp, true);
        s.removeEventListener('mouseleave', onMouseLeave, true);
        window.removeEventListener('mouseup', onMouseUp, true);
        window.removeEventListener('blur', onBlur);

        s.removeEventListener('touchstart', onTouchStart, { capture: true });
        s.removeEventListener('touchmove', onTouchMove, { capture: true });
        s.removeEventListener('touchend', onTouchEnd, { capture: true });

        s.removeEventListener('dragstart', onDragStart);
        s.removeEventListener('dragover', onStaffDragOver);
        s.removeEventListener('drop', onStaffDrop);
        s.removeEventListener('dragend', onStaffDragEnd);
        document.removeEventListener('click', onClickCapture, true);
        document.removeEventListener('keydown', onMenuKeyDown);
        document.removeEventListener('focusin', onMenuFocus);
        document.removeEventListener('pointerover', onActionsPointerOver);
        document.removeEventListener('pointerout', onActionsPointerOut);
        s.removeEventListener('contextmenu', onBarContextMenu);
        window.removeEventListener('resize', hideBarActions);
      };
    })();
    """

    b64_js = base64.b64encode(js_code.encode("utf-8")).decode("utf-8")
    html += f"<img src='x' style='display:none;' onerror='eval(atob(\"{b64_js}\"))'>"

    return html

