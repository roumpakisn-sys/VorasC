import base64
from datetime import datetime, timedelta

import streamlit as st

import config
import utils


def get_local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=3)).date()


def build_html_gantt(wk_groups, start_of_week, zoom_factor, key_to_safe_id, gantt_height_px):
    timeline_width_px = int(2400 * zoom_factor)
    day_names_gr = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

    # Ψηλότερες μπάρες + μικρότερα κενά
    BAR_HEIGHT_PX = 44
    LANE_STEP_PX = 46
    ROW_PAD_TOP_PX = 6
    ROW_PAD_BOTTOM_PX = 6
    TEXT_LINES = 4

    emp_short_names = {}
    external_crews = []
    for emp in st.session_state.employees:
        eid = emp["id"]
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

    html = ""

    html += (
        "<div id='gantt-master-container' "
        f"style='overflow: auto; height: {gantt_height_px}px; min-height: 360px; width: 100%; max-width: 100%; position: relative; border: 4px solid #1e293b; border-radius: 12px; "
        "background: #ffffff; user-select: none; cursor: grab; "
        "box-shadow: 0px 12px 35px rgba(0,0,0,0.4); font-family: \"Segoe UI\", Tahoma, Geneva, Verdana, sans-serif;'>"
    )

    html += "<style>#gantt-master-container::-webkit-scrollbar { width: 12px; height: 12px; } #gantt-master-container::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 8px; } #gantt-master-container::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 8px; border: 3px solid #f1f5f9; } #gantt-master-container::-webkit-scrollbar-thumb:hover { background: #64748b; } .mygantt-bar:hover { transform: scale(1.02); z-index: 30 !important; box-shadow: 0 6px 12px rgba(0,0,0,0.3) !important; outline: 2px solid #1e293b !important; }</style>"

    html += "<div style='display: flex; position: sticky; top: 0; z-index: 100; background: #f8fafc; border-bottom: 3px solid #1e293b; min-width: max-content;'>"
    html += "<div style='width: 230px; min-width: 230px; position: sticky; left: 0; z-index: 101; background: #f8fafc; border-right: 3px solid #1e293b; padding: 10px; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #1e293b; font-size: 14px;'>Ημέρα / Προσωπικό</div>"
    html += f"<div class='gantt-timeline-header' style='position: relative; width: {timeline_width_px}px; min-width: {timeline_width_px}px; height: 45px; background: #f8fafc;'>"

    for h in range(4, 25):
        pct = ((h - 4) / 20) * 100
        lbl = f"{h:02d}:00" if h < 24 else "00:00"
        html += f"<div style='position: absolute; left: {pct}%; height: 100%; border-left: 2px solid #94a3b8; padding-left: 4px; padding-top: 14px; font-weight: bold; font-size: 13px; color: #334155;'>{lbl}</div>"
    html += "</div></div>"

    for i in range(7):
        curr_date = start_of_week + timedelta(days=i)
        day_str = f"{day_names_gr[i]} {curr_date.strftime('%d/%m')}"

        leaves_today = []
        for l in st.session_state.leaves:
            if l["startDate"] <= curr_date <= l["endDate"]:
                emp_n = emp_short_names.get(l["employeeId"], utils.get_employee_name(l["employeeId"]))
                sub_id = l.get("substituteId")
                if sub_id:
                    sub_n = emp_short_names.get(sub_id, utils.get_employee_name(sub_id))
                    leaves_today.append(f"{emp_n} (Αντ: {sub_n})")
                else:
                    leaves_today.append(f"{emp_n}")

        available_ext_crew = []
        day_assigns = st.session_state.assignments_by_date.get(curr_date, [])
        for emp in external_crews:
            eid = emp["id"]
            if not any(l["employeeId"] == eid and l["startDate"] <= curr_date <= l["endDate"] for l in st.session_state.leaves):
                is_busy_after_10 = any(
                    a.get("employeeId") == eid
                    and not a.get("is_cancelled", False)
                    and str(a.get("endTime", ""))[:5] > "10:00"
                    for a in day_assigns
                )
                if not is_busy_after_10:
                    available_ext_crew.append(emp_short_names.get(eid, emp["name"]))

        label_html = f"<div style='font-size: 14px; font-weight: bold; margin-bottom: 8px;'>🗓️ {day_str}</div>"
        if leaves_today:
            label_html += f"<div style='color: #d32f2f; margin-bottom: 8px; font-size: 11px;'><b>Άδειες:</b><br>{'<br>'.join(leaves_today)}</div>"
        if available_ext_crew:
            label_html += f"<div style='color: #0369a1; font-size: 11px;'><b>ΜΕΤΑ ΤΑ ΠΡΩΙΝΑ:</b><br>{'<br>'.join(available_ext_crew)}</div>"

        day_groups = [g for g in wk_groups.values() if g["Date"] == curr_date]

        # Οι μπλε μπάρες μπαίνουν πάντα κάτω από όλες τις άλλες μπάρες της ημέρας.
        # Δεν αλλάζει η αποθήκευση ούτε η λογική των βαρδιών· μόνο η οπτική στοίβαξη.
        blue_stack_hex = config.BLUE_STACK_HEX.lower()
        non_blue_groups = [g for g in day_groups if str(g.get("ColorHex", "")).lower() != blue_stack_hex]
        blue_groups = [g for g in day_groups if str(g.get("ColorHex", "")).lower() == blue_stack_hex]

        group_lanes = []

        non_blue_lanes = []
        for g in sorted(non_blue_groups, key=lambda x: x["StartTime"]):
            placed = False
            for idx, lane_end in enumerate(non_blue_lanes):
                if g["StartTime"] >= lane_end:
                    non_blue_lanes[idx] = g["EndTime"]
                    group_lanes.append((g, idx))
                    placed = True
                    break
            if not placed:
                non_blue_lanes.append(g["EndTime"])
                group_lanes.append((g, len(non_blue_lanes) - 1))

        blue_lanes = []
        blue_lane_offset = len(non_blue_lanes)
        for g in sorted(blue_groups, key=lambda x: x["StartTime"]):
            placed = False
            for idx, lane_end in enumerate(blue_lanes):
                if g["StartTime"] >= lane_end:
                    blue_lanes[idx] = g["EndTime"]
                    group_lanes.append((g, blue_lane_offset + idx))
                    placed = True
                    break
            if not placed:
                blue_lanes.append(g["EndTime"])
                group_lanes.append((g, blue_lane_offset + len(blue_lanes) - 1))

        total_lanes = len(non_blue_lanes) + len(blue_lanes)
        row_height = max(1, total_lanes) * LANE_STEP_PX + ROW_PAD_TOP_PX + ROW_PAD_BOTTOM_PX
        bg_color_row = "#eef2ff" if curr_date == get_local_today() else ("#f8fafc" if i % 2 == 1 else "#ffffff")

        html += f"<div style='display: flex; min-width: max-content; border-bottom: 2px solid #e2e8f0; background-color: {bg_color_row}; min-height: {row_height}px;'>"
        html += f"<div style='width: 230px; min-width: 230px; position: sticky; left: 0; z-index: 50; background-color: {bg_color_row}; border-right: 3px solid #1e293b; padding: 10px; box-sizing: border-box;'>{label_html}</div>"
        html += f"<div style='position: relative; width: {timeline_width_px}px; min-width: {timeline_width_px}px; background-image: linear-gradient(to right, rgba(148, 163, 184, 0.3) 1px, transparent 1px); background-size: calc(100% / 20) 100%; padding-top: {ROW_PAD_TOP_PX}px; padding-bottom: {ROW_PAD_BOTTOM_PX}px;'>"

        for g, lane_idx in group_lanes:
            def t2p(t_str):
                h, m = map(int, t_str.split(":"))
                if h < 4:
                    h += 24
                mins = (h - 4) * 60 + m
                return max(0, min(100, (mins / 1200.0) * 100))

            left_pct = t2p(g["StartTime"])
            width_pct = t2p(g["EndTime"]) - left_pct
            top_px = lane_idx * LANE_STEP_PX + ROW_PAD_TOP_PX

            emps_str = ", ".join(g["Employees"]).upper()
            proj_name = g["Project"].upper()
            arr_str = f"[Προσ: {g['ArrivalTime']}] " if g["ArrivalTime"] else ""
            if "ΧΩΡΙΣ ΠΡΟΣΩΠΙΚΟ" in emps_str:
                emps_str = "⚠️ " + emps_str

            base_text = f"{arr_str}{g['StartTime']}-{g['EndTime']} | {proj_name} | {emps_str}"
            if g["Notes"]:
                base_text += f" ({g['Notes'].upper()})"
            if g["is_cancelled"]:
                base_text = f"<s>{base_text}</s>"
                if g["cancel_reason"]:
                    base_text += f"<br><span style='color:#dc2626;'>[{g['cancel_reason'].upper()}]</span>"

            bg_color = g["ColorHex"]
            tooltip = base_text.replace("<br>", " ").replace('"', "&quot;").replace("'", "&#39;")

            safe_id = key_to_safe_id.get(g["Key"], "")

            bar_border = "4px solid #dc2626" if g.get("IsGeneral", False) else "1px solid rgba(0,0,0,0.5)"
            bar_shadow = (
                "0 0 0 2px rgba(220,38,38,0.35), 0 3px 8px rgba(0,0,0,0.25)"
                if g.get("IsGeneral", False)
                else "0 3px 6px rgba(0,0,0,0.15)"
            )

            html += (
                f"<a href='javascript:void(0);' id='{safe_id}' draggable='false' class='mygantt-bar' "
                f"style='position: absolute; left: {left_pct}%; width: {width_pct}%; top: {top_px}px; "
                f"background-color: {bg_color}; height: {BAR_HEIGHT_PX}px; border: {bar_border}; border-radius: 6px; "
                f"box-shadow: {bar_shadow}; display: flex; align-items: center; justify-content: center; "
                f"font-size: 11px; font-weight: bold; color: black; text-decoration: none; cursor: pointer; transition: all 0.1s; "
                f"box-sizing: border-box; overflow: hidden; z-index: 10; padding: 0; margin: 0; text-align: center;' title='{tooltip}'>"
                f"<div style='line-height: 1.15; pointer-events: none; width: 100%; padding: 0 4px; display: -webkit-box; "
                f"-webkit-line-clamp: {TEXT_LINES}; -webkit-box-orient: vertical; overflow: hidden;'>{base_text}</div></a>"
            )

        html += "</div></div>"

    html += "</div>"

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

      if (savedScrollLeft !== null) {
          s.scrollLeft = parseFloat(savedScrollLeft);
      } else {
          setTimeout(function(){ s.scrollLeft = s.scrollWidth * 0.10; }, 50);
      }

      if (savedScrollTop !== null) {
          s.scrollTop = parseFloat(savedScrollTop);
      }

      var isDown = false;
      var startX = 0;
      var scrollLeftStart = 0;
      var moved = false;
      var DRAG_THRESHOLD = 5;
      window.gIsDragging = false;

      function onScroll() {
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
        e.preventDefault();
      }

      function onClickCapture(e) {
        var link = e.target.closest('a.mygantt-bar');
        if (link && (window.gIsDragging || moved)) {
          e.preventDefault();
          e.stopPropagation();
        }
      }

      s.addEventListener('scroll', onScroll);
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
      document.addEventListener('click', onClickCapture, true);

      window.ganttDragCleanup = function () {
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
        document.removeEventListener('click', onClickCapture, true);
      };
    })();
    """

    b64_js = base64.b64encode(js_code.encode("utf-8")).decode("utf-8")
    html += f"<img src='x' style='display:none;' onerror='eval(atob(\"{b64_js}\"))'>"

    return html
